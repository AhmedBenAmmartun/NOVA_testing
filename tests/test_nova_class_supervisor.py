"""The supervisor owns the sitting; workers only report into it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova_capture.supervisor import (
    CaptureEvent,
    ClassSessionSupervisor,
    SessionOutcome,
    WorkerStatus,
    read_events,
    read_health,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def supervisor(tmp_path: Path):
    clock = FakeClock()
    item = ClassSessionSupervisor(
        session_id="session-1",
        course="COP3710",
        session_path=tmp_path,
        clock=clock,
        health_interval_seconds=0.0,
    )
    item.open()
    return item, clock


def _healthy(item: ClassSessionSupervisor) -> None:
    item.set_worker("audio", WorkerStatus.RECORDING)
    item.set_worker("stt", WorkerStatus.CONNECTED)
    item.set_worker("notes", WorkerStatus.ACTIVE)


def test_session_id_survives_every_worker_restart(supervisor) -> None:
    item, clock = supervisor
    _healthy(item)

    for _ in range(5):
        clock.advance(60.0)
        item.stt_gap_start("connection dropped")
        item.stt_restarted()
        clock.advance(5.0)
        item.transcription_progress(clock.now)

    assert item.session_id == "session-1"
    assert item.stt_reconnects == 5
    assert not item.finalized
    assert len(item.stt_gaps()) == 5


def test_worker_loss_does_not_end_the_session(supervisor) -> None:
    item, clock = supervisor
    _healthy(item)
    clock.advance(120.0)

    item.set_worker("stt", WorkerStatus.OFFLINE, detail="gave up", failed=True)
    item.set_worker("notes", WorkerStatus.DEGRADED, detail="provider down", failed=True)

    assert not item.finalized
    assert item.worker_status("audio") is WorkerStatus.RECORDING
    assert item.worker_is_healthy("audio")
    assert not item.worker_is_healthy("stt")


def test_audio_progress_tracks_the_recording_frontier(supervisor) -> None:
    item, _clock = supervisor
    item.audio_progress(
        recorded_seconds=615.0,
        chunks=31,
        last_chunk=31,
        last_write_age_seconds=0.4,
    )
    item.transcription_progress(612.5)

    assert item.audio_written_until == pytest.approx(615.0)
    assert item.transcription_confirmed_until == pytest.approx(612.5)
    assert item.transcript_lag_seconds == pytest.approx(2.5)


def test_stt_gap_is_opened_and_closed_with_audio_positions(supervisor) -> None:
    item, _clock = supervisor
    item.audio_progress(
        recorded_seconds=600.0, chunks=30, last_chunk=30, last_write_age_seconds=0.2
    )
    item.stt_gap_start("websocket closed")
    assert item.worker_status("stt") is WorkerStatus.RECOVERING

    item.audio_progress(
        recorded_seconds=640.0, chunks=32, last_chunk=32, last_write_age_seconds=0.2
    )
    item.transcription_progress(639.0)

    gaps = item.stt_gaps()
    assert len(gaps) == 1
    assert gaps[0]["start_seconds"] == pytest.approx(600.0)
    assert gaps[0]["end_seconds"] == pytest.approx(640.0)
    assert gaps[0]["backfilled"] is False
    assert item.unrecovered_gap_count == 1
    assert item.worker_status("stt") is WorkerStatus.CONNECTED


def test_clean_stop_resolves_to_completed(supervisor) -> None:
    item, _clock = supervisor
    _healthy(item)
    item.request_stop("user_requested")
    assert item.finalize() is SessionOutcome.COMPLETED


def test_stop_that_was_never_requested_is_never_reported_as_clean(supervisor) -> None:
    """The exact 2026-08-27 lie: status 'completed' for a class that was cut off."""
    item, _clock = supervisor
    _healthy(item)
    assert item.finalize() is SessionOutcome.COMPLETED_WITH_WARNINGS


def test_recovery_history_downgrades_the_outcome(supervisor) -> None:
    item, _clock = supervisor
    _healthy(item)
    item.stt_gap_start("dropped")
    item.transcription_progress(30.0)
    item.request_stop("user_requested")
    assert item.finalize() is SessionOutcome.COMPLETED_WITH_WARNINGS


def test_missing_audio_worker_is_a_failed_session(supervisor) -> None:
    item, _clock = supervisor
    item.set_worker("audio", WorkerStatus.FAILED, detail="device gone", failed=True)
    item.request_stop("user_requested")
    assert item.finalize() is SessionOutcome.FAILED


def test_finalization_error_can_never_be_reported_as_success(supervisor) -> None:
    item, _clock = supervisor
    _healthy(item)
    item.request_stop("user_requested")
    item.note_finalization_error("speaker_roles", RuntimeError("disk full"))

    assert item.finalize() is SessionOutcome.FAILED
    health = read_health(item.session_path)
    assert health is not None
    assert any("disk full" in entry for entry in health["finalization_errors"])


def test_health_file_shape_is_stable_and_useful(supervisor) -> None:
    item, clock = supervisor
    _healthy(item)
    clock.advance(5832.0)
    item.audio_progress(
        recorded_seconds=5830.0,
        chunks=194,
        last_chunk=194,
        last_write_age_seconds=0.4,
    )
    item.write_health(force=True)

    payload = json.loads((item.session_path / "health.json").read_text(encoding="utf-8"))
    assert payload["session_active"] is True
    assert payload["duration_seconds"] == pytest.approx(5832.0)
    assert payload["workers"]["audio"]["status"] == "recording"
    assert payload["workers"]["audio"]["last_chunk"] == 194
    assert payload["workers"]["stt"]["status"] == "connected"
    assert payload["recovery"]["stt_reconnects"] == 0
    assert "audio_integrity" in payload


def test_events_journal_records_the_story_of_the_class(supervisor) -> None:
    item, _clock = supervisor
    _healthy(item)
    item.stt_gap_start("dropped")
    item.stt_restarted()
    item.transcription_progress(42.0)
    item.request_stop("user_requested")
    item.finalize()

    events = [entry["event"] for entry in read_events(item.session_path)]
    assert events[0] == CaptureEvent.SESSION_STARTED.value
    assert CaptureEvent.STT_GAP_START.value in events
    assert CaptureEvent.STT_RESTART.value in events
    assert CaptureEvent.STT_GAP_END.value in events
    assert CaptureEvent.STOP_REQUESTED.value in events
    assert events[-1] == CaptureEvent.SESSION_FINALIZED.value


def test_event_journal_failure_never_raises(supervisor, monkeypatch) -> None:
    item, _clock = supervisor

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", explode)
    # Must not raise: a diagnostic journal can never take down a live class.
    item.record_event(CaptureEvent.WORKER_STATUS, worker="audio")
