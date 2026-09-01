"""Nothing downstream of the microphone may end a class.

Two kinds of check live here:

* a full 2h30m torture scenario in which STT, the network, and the notes
  provider all fail at different points, driven through the real supervisor,
  the real chunked recorder, the real notes worker, and the real speaker
  tracker;
* structural assertions on ``class_capture.py`` itself, because the wiring
  order (audio before STT, restart instead of finalize) is the actual fix for
  the 2026-08-27 failure and a refactor must not quietly undo it.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from nova_capture.audio_chunks import ChunkedAudioRecorder, scan_audio_dir
from nova_capture.live_notes import LiveNotesBatcher, LiveNotesWorker
from nova_capture.models import SpeakerRole, TranscriptSegment
from nova_capture.speakers import SpeakerRoleTracker
from nova_capture.supervisor import (
    CaptureEvent,
    ClassSessionSupervisor,
    SessionOutcome,
    WorkerStatus,
    read_events,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "class_capture.py").read_text(encoding="utf-8-sig")

TORTURE_SECONDS = 150 * 60
SAMPLE_RATE = 400
CHUNK_SECONDS = 30.0

PROFESSOR_LINE = (
    "Alright, let's look at the slide. Recall that a foreign key references "
    "the primary key of another relation, and this will be on the exam."
)
STUDENT_LINE = "Is that the same as a candidate key?"
GUEST_LINE = (
    "Thanks for having me. I work at a data platform company and my team "
    "spends most of its time on distributed query execution."
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _segment(start: float, text: str, speaker_id: str) -> TranscriptSegment:
    return TranscriptSegment(
        start_seconds=start,
        end_seconds=start + 5.0,
        text=text,
        speaker=SpeakerRole.UNKNOWN,
        speaker_id=speaker_id,
    )


@pytest.fixture(scope="module")
def torture(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("torture")
    return asyncio.run(_run_torture(root))


async def _run_torture(root: Path) -> dict:
    clock = FakeClock()
    supervisor = ClassSessionSupervisor(
        session_id="2026-08-28_10-00-00_torture",
        course="COP3710",
        session_path=root,
        clock=clock,
        health_interval_seconds=0.0,
    )
    supervisor.open()

    recorder = ChunkedAudioRecorder(
        root / "audio",
        sample_rate=SAMPLE_RATE,
        chunk_seconds=CHUNK_SECONDS,
        fsync=False,
        clock=clock,
    )
    recorder.start()
    supervisor.set_worker("audio", WorkerStatus.RECORDING)
    supervisor.set_worker("stt", WorkerStatus.CONNECTED)

    providers = {"notes": True}

    async def generate(_prompt: str) -> str:
        if not providers["notes"]:
            raise RuntimeError("provider unreachable")
        return json.dumps(
            {
                "current_topic": "Relational keys",
                "key_concepts": [f"concept at {clock.now:.0f}s"],
            }
        )

    notes = LiveNotesWorker(
        session_path=root,
        course="COP3710",
        title="Class Session",
        generate=generate,
        batcher=LiveNotesBatcher(interval_seconds=75.0, word_trigger=800),
        retry_seconds=0.0,
        max_attempts_per_batch=1,
    )
    notes_task = asyncio.create_task(notes.run())
    supervisor.set_worker("notes", WorkerStatus.ACTIVE)

    speakers = SpeakerRoleTracker()
    timeline: dict[str, dict] = {}
    block = b"\x01\x00" * SAMPLE_RATE
    stt_online = True

    for second in range(TORTURE_SECONDS):
        recorder.write_pcm(block)
        clock.advance(1.0)

        # 00:20 -- the exact 2026-08-27 failure: the STT worker disappears.
        if second == 20 * 60:
            stt_online = False
            supervisor.stt_gap_start("agent_session_closed:ERROR")
            timeline["stt_lost"] = {
                "chunks": recorder.chunk_count,
                "recorded": recorder.recorded_seconds,
                "session_id": supervisor.session_id,
                "finalized": supervisor.finalized,
            }

        # 00:21 -- transcription is rebuilt. Same session, same recording.
        if second == 21 * 60:
            supervisor.stt_restarted()
            stt_online = True
            timeline["stt_restarted"] = {
                "chunks": recorder.chunk_count,
                "session_id": supervisor.session_id,
            }

        # 00:45 -- the network goes; the notes provider starts failing.
        if second == 45 * 60:
            providers["notes"] = False
            supervisor.record_event(CaptureEvent.PROVIDER_FAILED, provider="notes")

        # 01:10 -- still failing; the recording must not have noticed.
        if second == 70 * 60:
            timeline["provider_down"] = {
                "chunks": recorder.chunk_count,
                "recorded": recorder.recorded_seconds,
                "notes_status": notes.status,
                "pending": len(notes.queue.pending()),
                "audio_status": supervisor.worker_status("audio").value,
            }

        # 01:20 -- the provider comes back and the backlog drains.
        if second == 80 * 60:
            providers["notes"] = True
            supervisor.record_event(CaptureEvent.PROVIDER_RECOVERED, provider="notes")

        if second % 5 == 0 and stt_online:
            elapsed = float(second)
            if second < 90 * 60:
                speaker_id = "0" if second % 60 else "1"
                text = PROFESSOR_LINE if speaker_id == "0" else STUDENT_LINE
            else:
                # 01:30 -- a guest presenter takes over the room.
                speaker_id = "2" if second % 60 else "1"
                text = GUEST_LINE if speaker_id == "2" else STUDENT_LINE

            resolved = speakers.observe(speaker_id, text, elapsed_seconds=elapsed)
            notes.feed(_segment(elapsed, text, speaker_id), speaker_label=resolved.label)
            supervisor.transcription_progress(elapsed)

        if second % 60 == 0:
            supervisor.audio_progress(
                recorded_seconds=recorder.recorded_seconds,
                chunks=recorder.chunk_count,
                last_chunk=recorder.last_sequence,
                last_write_age_seconds=0.0,
            )
            await asyncio.sleep(0)

    timeline["guest_live"] = speakers.live_assessment("2").as_dict()

    # Explicit user stop.
    supervisor.request_stop("user_requested")
    notes.flush(reason="finalize")
    await notes.drain(timeout_seconds=5.0)
    notes_task.cancel()
    try:
        await notes_task
    except asyncio.CancelledError:
        pass

    recorder.stop()
    supervisor.audio_progress(
        recorded_seconds=recorder.recorded_seconds,
        chunks=recorder.chunk_count,
        last_chunk=recorder.last_sequence,
        last_write_age_seconds=0.0,
        status=WorkerStatus.STOPPED,
    )
    speakers.finalize_roles()
    outcome = supervisor.finalize()

    return {
        "root": root,
        "supervisor": supervisor,
        "recorder": recorder,
        "notes": notes,
        "speakers": speakers,
        "timeline": timeline,
        "outcome": outcome,
    }


# --- torture assertions -----------------------------------------------------


def test_audio_survives_the_stt_worker_disappearing(torture: dict) -> None:
    marks = torture["timeline"]
    assert marks["stt_lost"]["chunks"] > 0
    assert not marks["stt_lost"]["finalized"], "the session must not end with STT"
    assert marks["stt_restarted"]["chunks"] > marks["stt_lost"]["chunks"]


def test_the_whole_sitting_keeps_one_session_id(torture: dict) -> None:
    supervisor: ClassSessionSupervisor = torture["supervisor"]
    marks = torture["timeline"]
    assert marks["stt_lost"]["session_id"] == supervisor.session_id
    assert marks["stt_restarted"]["session_id"] == supervisor.session_id
    assert supervisor.stt_reconnects == 1


def test_provider_outage_never_touches_the_recording(torture: dict) -> None:
    marks = torture["timeline"]["provider_down"]
    assert marks["audio_status"] == "recording"
    assert marks["recorded"] > 60 * 60, "audio kept growing through the outage"
    assert marks["notes_status"] == "degraded"
    assert marks["pending"] >= 1, "unprocessed note evidence stayed queued"


def test_notes_backlog_drains_after_the_provider_recovers(torture: dict) -> None:
    notes: LiveNotesWorker = torture["notes"]
    assert notes.status == "active"
    assert notes.generated_count > 0
    text = (torture["root"] / "live_notes.md").read_text(encoding="utf-8")
    assert "Relational keys" in text


def test_guest_presenter_is_distinguished_from_the_professor(torture: dict) -> None:
    speakers: SpeakerRoleTracker = torture["speakers"]
    assert "Guest" in torture["timeline"]["guest_live"]["label"]
    assert speakers.teacher_speaker_id() == "0"
    assert speakers.resolve("2").role is SpeakerRole.GUEST


def test_two_and_a_half_hours_of_audio_is_intact(torture: dict) -> None:
    report = scan_audio_dir(torture["root"] / "audio")
    assert report.chunk_count == int(TORTURE_SECONDS / CHUNK_SECONDS)
    assert report.recorded_seconds == pytest.approx(TORTURE_SECONDS, abs=1.0)
    assert report.sequence_gaps == []
    assert report.timestamp_gaps == []
    assert report.healthy


def test_the_torture_run_finalizes_once_with_an_honest_outcome(torture: dict) -> None:
    supervisor: ClassSessionSupervisor = torture["supervisor"]
    # It was a clean user stop, but STT was lost for a minute -- so the outcome
    # must say "completed with warnings", never a bare "completed".
    assert torture["outcome"] is SessionOutcome.COMPLETED_WITH_WARNINGS
    assert supervisor.unrecovered_gap_count == 1

    events = [entry["event"] for entry in read_events(supervisor.session_path)]
    assert events.count(CaptureEvent.SESSION_FINALIZED.value) == 1
    assert CaptureEvent.PROVIDER_FAILED.value in events
    assert CaptureEvent.PROVIDER_RECOVERED.value in events


# --- structural guarantees in class_capture.py ------------------------------


def test_recording_starts_before_any_transcription_work() -> None:
    """P0 ordering: nothing that can fail may run before the recorder."""
    recorder_at = SOURCE.index("create_durable_recorder")
    stt_at = SOURCE.index("build_transcription_session()\n        await start_")
    assert recorder_at < stt_at


def test_transcription_loss_triggers_recovery_not_finalization() -> None:
    assert 'live_session.on("close")' in SOURCE
    assert "schedule_transcription_restart(reason)" in SOURCE
    assert "supervisor.stt_gap_start(" in SOURCE
    # The close handler must not be able to finalize the class.
    close_handler = SOURCE.split('live_session.on("close")')[1].split("return live_session")[0]
    assert "finalize(" not in close_handler
    assert "ctx.shutdown" not in close_handler


def test_a_crash_shutdown_deliberately_leaves_the_recorder_running() -> None:
    assert "NOVA_CLASS_KEEP_AUDIO_ON_CRASH" in SOURCE
    assert "keep_recording = (" in SOURCE
    assert "AUDIO STILL RECORDING" in SOURCE


def test_stop_reports_the_outcome_the_supervisor_actually_resolved() -> None:
    assert "outcome = supervisor.finalize(" in SOURCE
    assert "capture.stop(status=outcome.value)" in SOURCE
    assert "FINALIZATION PROBLEMS" in SOURCE


def test_the_durable_recorder_and_health_files_are_wired_in() -> None:
    assert "ClassSessionSupervisor(" in SOURCE
    assert "write_supervisor_heartbeat(session_path)" in SOURCE
    assert "supervisor.write_health(force=True)" in SOURCE
    assert "persist_live_speakers()" in SOURCE
    assert "LiveNotesWorker(" in SOURCE


def test_capture_version_moved_forward_for_this_work() -> None:
    match = re.search(r'^CAPTURE_VERSION\s*=\s*"([0-9.]+)"', SOURCE, re.MULTILINE)
    assert match is not None
    parts = tuple(int(value) for value in match.group(1).split("."))
    assert parts >= (1, 3, 7)


def test_class_capture_writes_a_durable_log_of_its_own() -> None:
    """The 38m36s stop had no log. That must never be true again."""
    assert "_configure_capture_log(session_path)" in SOURCE
    assert "class_capture.log" in SOURCE
