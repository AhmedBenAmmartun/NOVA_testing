from __future__ import annotations

import re
from pathlib import Path

from nova_capture.models import TranscriptSegment
from nova_capture.questions import QuestionDeduplicator, TurnQuestionBuffer


#: The capture version that introduced turn-aware live questions. This test
#: exists to protect that architecture, so it asserts a *floor* rather than an
#: exact pin — the implementation is expected to move forward (it is at 1.3.6 as
#: of commit 776c53d), and a forward bump is not a regression. Reverting below
#: this version, or dropping the constant entirely, still fails.
TURN_AWARE_MINIMUM_VERSION = (1, 3, 4)

_CAPTURE_VERSION = re.compile(r'^CAPTURE_VERSION\s*=\s*"([0-9]+(?:\.[0-9]+)*)"', re.MULTILINE)


def _declared_capture_version(source: str) -> tuple[int, ...]:
    match = _CAPTURE_VERSION.search(source)
    assert match is not None, "class_capture.py must declare a CAPTURE_VERSION constant"
    return tuple(int(part) for part in match.group(1).split("."))


def test_turn_buffer_waits_for_turn_boundary() -> None:
    buffer = TurnQuestionBuffer()
    buffer.feed(TranscriptSegment(0.0, 1.0, "Like, where are you?", speaker_id="0"))
    # No question decision happens while chunks are still arriving.
    assert buffer._segments  # internal buffer intentionally retains the chunk
    outputs = buffer.flush()
    assert len(outputs) == 1
    assert outputs[0].text == "Like, where are you?"


def test_turn_buffer_merges_split_wh_continuation() -> None:
    buffer = TurnQuestionBuffer()
    buffer.feed(TranscriptSegment(0.0, 1.0, "Like, where are you?", speaker_id="0"))
    buffer.feed(TranscriptSegment(1.0, 2.0, "Getting the data from?", speaker_id="0"))
    outputs = buffer.flush()
    assert len(outputs) == 1
    assert outputs[0].text == "Like, where are you getting the data from?"
    assert outputs[0].is_question is True


def test_turn_buffer_keeps_speaker_boundaries_separate() -> None:
    buffer = TurnQuestionBuffer()
    buffer.feed(TranscriptSegment(0.0, 1.0, "What is cohesion?", speaker_id="0"))
    buffer.feed(TranscriptSegment(1.0, 2.0, "I think it groups related things.", speaker_id="1"))
    outputs = buffer.flush()
    assert len(outputs) == 2
    assert outputs[0].speaker_id == "0"
    assert outputs[1].speaker_id == "1"


def test_question_deduplicator_suppresses_rephrases_in_window() -> None:
    dedupe = QuestionDeduplicator(window_seconds=15.0)
    assert not dedupe.is_duplicate(
        "Getting the data from?",
        timestamp_seconds=100.0,
    )
    assert dedupe.is_duplicate(
        "You know, where are you getting your data from?",
        timestamp_seconds=108.0,
    )
    assert dedupe.is_duplicate(
        "Where are you getting data from?",
        timestamp_seconds=112.0,
    )


def test_question_deduplicator_allows_question_after_window() -> None:
    dedupe = QuestionDeduplicator(window_seconds=15.0)
    assert not dedupe.is_duplicate("What are watchers?", timestamp_seconds=10.0)
    assert not dedupe.is_duplicate("What are watchers?", timestamp_seconds=30.0)


def test_root_capture_uses_turn_boundary_and_serial_answer_queue() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(encoding="utf-8-sig")
    assert _declared_capture_version(source) >= TURN_AWARE_MINIMUM_VERSION, (
        "class_capture.py regressed below the turn-aware live-question version"
    )
    assert 'live_session.on("conversation_item_added")' in source
    assert 'schedule_turn_flush(0.45, "turn_commit")' in source
    assert 'schedule_turn_flush(3.5, "fallback")' in source
    assert "TurnQuestionBuffer()" in source
    assert "QuestionDeduplicator(window_seconds=15.0)" in source
    assert "asyncio.Queue(maxsize=8)" in source
    assert 'name="nova-class-live-answer-worker"' in source
    assert "answer_queue.put_nowait(question)" in source
    assert "answer_queue.join()" in source
    # V1.3.3's per-question fan-out must be gone.
    assert "pending_answers" not in source
