"""Live notes: useful early, durable always, and never in the audio path."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nova_capture.live_notes import (
    LiveNotesBatcher,
    LiveNotesQueue,
    LiveNotesWorker,
    NoteBatch,
    parse_note_payload,
)
from nova_capture.models import SpeakerRole, TranscriptSegment


def _segment(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        start_seconds=start,
        end_seconds=end,
        text=text,
        speaker=SpeakerRole.UNKNOWN,
        speaker_id="0",
    )


def _lecture(seconds: float, *, words_per_segment: int = 20, step: float = 5.0):
    position = 0.0
    index = 0
    while position < seconds:
        index += 1
        yield _segment(
            position,
            position + step,
            " ".join(f"concept{index}" for _ in range(words_per_segment)),
        )
        position += step


# --- batching --------------------------------------------------------------


def test_first_batch_closes_within_two_minutes_of_lecture() -> None:
    batcher = LiveNotesBatcher()
    first = None
    for segment in _lecture(180.0):
        batch = batcher.feed(segment)
        if batch is not None:
            first = batch
            break

    assert first is not None, "notes must not wait for the end of class"
    assert first.end_seconds <= 120.0
    assert first.reason == "interval"


def test_a_single_sentence_never_triggers_a_model_call() -> None:
    batcher = LiveNotesBatcher()
    assert batcher.feed(_segment(0.0, 3.0, "Good morning everyone.")) is None
    assert batcher.feed(_segment(3.0, 6.0, "Today we start chapter four.")) is None
    assert batcher.batches_emitted == 0


def test_word_budget_closes_a_batch_before_the_interval() -> None:
    batcher = LiveNotesBatcher(interval_seconds=600.0, word_trigger=200)
    batch = None
    for segment in _lecture(120.0, words_per_segment=40, step=1.0):
        batch = batcher.feed(segment)
        if batch is not None:
            break

    assert batch is not None
    assert batch.reason == "word_budget"
    assert batch.words >= 200


def test_flush_emits_whatever_is_left() -> None:
    batcher = LiveNotesBatcher()
    batcher.feed(_segment(0.0, 4.0, "aggregation means a whole part relationship"))
    batch = batcher.flush(reason="finalize")
    assert batch is not None
    assert batch.reason == "finalize"
    assert batcher.flush() is None


# --- durable queue ---------------------------------------------------------


def test_queue_survives_a_restart(tmp_path: Path) -> None:
    queue = LiveNotesQueue(tmp_path)
    first = NoteBatch(1, 0.0, 60.0, 200, ["[0.0s] [Speaker 0] one"], "interval")
    second = NoteBatch(2, 60.0, 120.0, 200, ["[60.0s] [Speaker 0] two"], "interval")
    queue.enqueue(first)
    queue.enqueue(second)
    queue.mark_processed(first)

    reopened = LiveNotesQueue(tmp_path)
    pending = reopened.pending()
    assert [item.index for item in pending] == [2]
    assert reopened.processed_count == 1


def test_parse_note_payload_tolerates_fenced_json() -> None:
    payload = parse_note_payload('```json\n{"current_topic": "Joins"}\n```')
    assert payload == {"current_topic": "Joins"}
    assert parse_note_payload("no json here") is None
    assert parse_note_payload(None) is None


# --- worker behaviour ------------------------------------------------------


def _worker(tmp_path: Path, generate, **overrides) -> LiveNotesWorker:
    options = {
        "session_path": tmp_path,
        "course": "COP3710",
        "title": "Class Session",
        "generate": generate,
        "retry_seconds": 0.0,
        "max_attempts_per_batch": 2,
    }
    options.update(overrides)
    return LiveNotesWorker(**options)


def test_notes_file_exists_before_any_model_has_answered(tmp_path: Path) -> None:
    async def never_called(_prompt: str) -> str | None:  # pragma: no cover
        raise AssertionError("no model call should have happened yet")

    worker = _worker(tmp_path, never_called)
    text = (tmp_path / "live_notes.md").read_text(encoding="utf-8")
    assert "# Live Class Notes" in text
    assert "Not resolved yet" in text
    assert worker.status == "active"


def test_worker_folds_evidence_into_the_notes(tmp_path: Path) -> None:
    async def generate(_prompt: str) -> str:
        return json.dumps(
            {
                "current_topic": "Normalization",
                "key_concepts": ["Third normal form removes transitive dependencies"],
                "definitions": ["A superkey uniquely identifies a row"],
                "assignments": ["Project 2 is due Friday"],
            }
        )

    worker = _worker(tmp_path, generate)
    batch = NoteBatch(1, 0.0, 90.0, 300, ["[0.0s] [Teacher] normalization"], "interval")

    assert asyncio.run(worker.process_one(batch))

    text = (tmp_path / "live_notes.md").read_text(encoding="utf-8")
    assert "Normalization" in text
    assert "Third normal form removes transitive dependencies" in text
    assert "## Assignments / Deadlines" in text
    assert "Project 2 is due Friday" in text
    assert worker.document.covered_until_seconds == pytest.approx(90.0)


def test_repeated_evidence_is_not_duplicated(tmp_path: Path) -> None:
    async def generate(_prompt: str) -> str:
        return json.dumps({"key_concepts": ["Indexes speed up lookups"]})

    worker = _worker(tmp_path, generate)
    for index in (1, 2, 3):
        batch = NoteBatch(index, 0.0, 90.0 * index, 300, ["line"], "interval")
        assert asyncio.run(worker.process_one(batch))

    text = (tmp_path / "live_notes.md").read_text(encoding="utf-8")
    assert text.count("Indexes speed up lookups") == 1


def test_topic_changes_are_reported_to_the_session(tmp_path: Path) -> None:
    topics: list[tuple[str, float]] = []

    payloads = iter(
        [
            json.dumps({"current_topic": "Entity Relationship Models"}),
            json.dumps({"current_topic": "Normalization"}),
        ]
    )

    async def generate(_prompt: str) -> str:
        return next(payloads)

    worker = _worker(tmp_path, generate, on_topic=lambda t, s: topics.append((t, s)))
    asyncio.run(worker.process_one(NoteBatch(1, 0.0, 60.0, 300, ["a"], "interval")))
    asyncio.run(worker.process_one(NoteBatch(2, 60.0, 120.0, 300, ["b"], "interval")))

    assert topics == [("Entity Relationship Models", 0.0), ("Normalization", 60.0)]
    assert worker.document.topics == ["Entity Relationship Models", "Normalization"]


def test_provider_failure_degrades_notes_and_keeps_the_evidence(tmp_path: Path) -> None:
    async def failing(_prompt: str) -> str:
        raise RuntimeError("groq: 503 service unavailable")

    worker = _worker(tmp_path, failing)
    worker.feed(_segment(0.0, 5.0, "one two three"))
    worker.flush(reason="test")

    async def scenario() -> None:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert worker.status == "degraded"
    assert "503" in str(worker.last_error)
    # The evidence is still queued for post-class refinement.
    assert [item.index for item in worker.queue.pending()] == [1]
    assert "degraded" in (tmp_path / "live_notes.md").read_text(encoding="utf-8")


def test_provider_recovery_drains_the_backlog(tmp_path: Path) -> None:
    """A provider outage must cost latency, never evidence."""
    state = {"fail": True}

    async def flaky(_prompt: str) -> str:
        if state["fail"]:
            raise RuntimeError("provider down")
        return json.dumps({"key_concepts": ["Recovered concept"]})

    worker = _worker(tmp_path, flaky)
    batch = NoteBatch(1, 0.0, 90.0, 300, ["evidence"], "interval")
    worker._enqueue(batch)

    async def scenario() -> None:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        assert worker.status == "degraded"

        state["fail"] = False
        worker._enqueue(
            NoteBatch(2, 90.0, 180.0, 300, ["more evidence"], "interval")
        )
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())

    assert worker.status == "active"
    assert "Recovered concept" in (tmp_path / "live_notes.md").read_text(encoding="utf-8")


def test_unusable_model_output_is_treated_as_a_failure_not_a_note(
    tmp_path: Path,
) -> None:
    async def rambling(_prompt: str) -> str:
        return "I'm sorry, I can't help with that."

    worker = _worker(tmp_path, rambling)
    assert not asyncio.run(
        worker.process_one(NoteBatch(1, 0.0, 60.0, 300, ["x"], "interval"))
    )
    assert worker.status == "degraded"
    assert worker.queue.processed_count == 0


def test_feeding_notes_never_raises_into_the_transcript_path(tmp_path: Path) -> None:
    async def generate(_prompt: str) -> str:  # pragma: no cover - not reached
        return "{}"

    worker = _worker(tmp_path, generate)
    for segment in _lecture(300.0):
        worker.feed(segment, speaker_label="Teacher")

    # Batches queued durably, model never touched by feed().
    assert worker.queue.pending()
    assert worker.generated_count == 0


def test_restore_pending_requeues_unprocessed_work(tmp_path: Path) -> None:
    async def generate(_prompt: str) -> str:
        return json.dumps({"key_concepts": ["restored"]})

    first = _worker(tmp_path, generate)
    first._enqueue(NoteBatch(1, 0.0, 60.0, 300, ["a"], "interval"))

    second = _worker(tmp_path, generate)
    assert second.restore_pending() == 1
    assert second.pending_count == 1
