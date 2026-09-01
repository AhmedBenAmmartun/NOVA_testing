"""Start once, stop cleanly, and always be able to stop the recorder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova_capture import control
from nova_capture.audio_chunks import ChunkedAudioRecorder
from nova_capture.recorder_process import stop_file
from nova_capture.status import latest_session_path, render_status, status_json
from nova_capture.supervisor import ClassSessionSupervisor, WorkerStatus


@pytest.fixture
def control_root(tmp_path: Path, monkeypatch):
    root = tmp_path / "_control"
    root.mkdir()
    monkeypatch.setattr(control, "control_root", lambda: root)
    return root


def _session(tmp_path: Path, *, seconds: float = 6.0) -> Path:
    session = tmp_path / "session"
    recorder = ChunkedAudioRecorder(
        session / "audio",
        sample_rate=400,
        chunk_seconds=2.0,
        fsync=False,
    )
    recorder.start()
    recorder.write_pcm(b"\x01\x00" * int(seconds * 400))
    recorder.write_state(status="recording")
    return session


# --- duplicate start --------------------------------------------------------


def test_second_start_is_rejected_and_the_first_class_is_untouched(
    tmp_path: Path, control_root: Path
) -> None:
    first = control.claim_active_session(
        session_id="session-1",
        course="COP3710",
        session_path=tmp_path / "session-1",
    )

    with pytest.raises(control.ActiveClassCaptureError) as error:
        control.claim_active_session(
            session_id="session-2",
            course="COP3710",
            session_path=tmp_path / "session-2",
        )
    assert "already active" in str(error.value)

    still_active = control.read_active_session(clean_stale=False)
    assert still_active is not None
    assert still_active.session_id == first.session_id
    control.release_active_session("session-1")


def test_the_claim_remembers_where_the_recorder_is_writing(
    tmp_path: Path, control_root: Path
) -> None:
    session = tmp_path / "session-1"
    control.claim_active_session(
        session_id="session-1", course="COP3710", session_path=session
    )
    payload = json.loads(control.last_session_path().read_text(encoding="utf-8"))
    assert payload["session_id"] == "session-1"
    assert Path(payload["session_path"]) == session.resolve()
    control.release_active_session("session-1")


# --- clean stop -------------------------------------------------------------


def test_stop_request_also_signals_the_separate_recorder_process(
    tmp_path: Path, control_root: Path
) -> None:
    """The recorder is a different process; a stop must actually reach it."""
    session = _session(tmp_path)
    control.claim_active_session(
        session_id="session-1", course="COP3710", session_path=session
    )

    active = control.request_stop()
    assert active is not None
    assert stop_file(session).is_file()
    payload = json.loads(stop_file(session).read_text(encoding="utf-8"))
    assert payload["reason"] == "user_requested"
    control.release_active_session("session-1")


def test_an_orphaned_recorder_can_still_be_stopped(
    tmp_path: Path, control_root: Path
) -> None:
    """The intelligence process died; the recording must not be unstoppable."""
    session = _session(tmp_path)
    control.claim_active_session(
        session_id="session-1", course="COP3710", session_path=session
    )
    # The intelligence process vanishes without releasing anything.
    control.active_state_path().unlink()
    control.active_lock_path().unlink()

    assert control.read_active_session(clean_stale=True) is None
    stopped = control.stop_orphaned_recorder()
    assert stopped is not None
    assert Path(stopped) == session
    assert stop_file(session).is_file()


def test_no_orphan_stop_when_the_recorder_already_finished(
    tmp_path: Path, control_root: Path
) -> None:
    session = _session(tmp_path)
    ChunkedAudioRecorder(
        session / "audio", sample_rate=400, fsync=False
    ).write_state(status="stopped")
    control.claim_active_session(
        session_id="session-1", course="COP3710", session_path=session
    )
    control.active_state_path().unlink()

    assert control.stop_orphaned_recorder() is None


# --- status -----------------------------------------------------------------


def test_status_reports_the_recording_not_the_process(tmp_path: Path) -> None:
    session = _session(tmp_path)
    supervisor = ClassSessionSupervisor(
        session_id="session-1",
        course="COP3710",
        session_path=session,
    )
    supervisor.open()
    supervisor.audio_progress(
        recorded_seconds=6.0,
        chunks=3,
        last_chunk=3,
        last_write_age_seconds=0.3,
    )
    supervisor.set_worker("stt", WorkerStatus.CONNECTED)
    supervisor.set_worker("notes", WorkerStatus.ACTIVE)
    supervisor.transcription_progress(3.0)
    supervisor.write_health(force=True)
    (session / "session.json").write_text(
        json.dumps({"session_id": "session-1", "course": "COP3710", "status": "recording"}),
        encoding="utf-8",
    )

    text = render_status(session)
    assert "NOVA CLASS CAPTURE" in text
    assert "Course:   COP3710" in text
    assert "AUDIO:       RECORDING" in text
    assert "Chunks:      3" in text
    assert "STT:         CONNECTED" in text
    assert "NOTES:       ACTIVE" in text
    assert "Integrity:   OK" in text
    assert "STT reconnects:   0" in text


def test_status_flags_a_damaged_recording(tmp_path: Path) -> None:
    session = _session(tmp_path)
    next(iter(sorted((session / "audio").glob("*.wav")))).unlink()

    text = render_status(session)
    assert "Integrity:   NEEDS REVIEW" in text
    assert "missing chunks" in text


def test_status_json_is_machine_readable(tmp_path: Path) -> None:
    session = _session(tmp_path)
    payload = status_json(session)
    assert payload["session_path"] == str(session)
    assert payload["audio_integrity"]["chunk_count"] == 3
    assert payload["recorder"]["status"] == "recording"
    json.dumps(payload)


def test_latest_session_is_found_under_the_capture_root(tmp_path: Path) -> None:
    course = tmp_path / "COP3710"
    older = course / "2026-08-01_09-00-00_aaaa"
    newer = course / "2026-08-02_09-00-00_bbbb"
    for path in (older, newer):
        path.mkdir(parents=True)
        (path / "session.json").write_text("{}", encoding="utf-8")

    import os
    import time

    os.utime(older, (time.time() - 500, time.time() - 500))
    assert latest_session_path(tmp_path) == newer


# --- agent-facing verification ---------------------------------------------


def test_end_class_capture_accepts_chunked_audio_as_saved(tmp_path: Path) -> None:
    from tools.class_capture import _verify_saved_audio

    session = _session(tmp_path)
    ok, detail = _verify_saved_audio(session)
    assert ok
    assert "3 chunks" in detail


def test_end_class_capture_still_accepts_a_legacy_single_wav(tmp_path: Path) -> None:
    from tools.class_capture import _verify_saved_audio

    session = tmp_path / "legacy"
    session.mkdir()
    (session / "audio.wav").write_bytes(b"RIFF" + b"x" * 100)
    ok, detail = _verify_saved_audio(session)
    assert ok
    assert "legacy" in detail


def test_end_class_capture_never_claims_audio_that_is_not_there(tmp_path: Path) -> None:
    from tools.class_capture import _verify_saved_audio

    session = tmp_path / "empty"
    session.mkdir()
    ok, detail = _verify_saved_audio(session)
    assert not ok
    assert "no audio" in detail


# --- finalization metadata schema ------------------------------------------
#
# On 2026-08-28 a real CEN4934 class finalized with
# `AttributeError: Unknown class-session metadata field: stt_restarts`.
# session.json was never updated -- it still said status="recording" with zero
# counts -- and post-class notes were never generated. The V1.3.7 tests passed
# because they asserted on class_capture.py *source strings* and never executed
# finalize() against a real ClassCaptureSession. These tests close that gap.


def _update_metadata_keywords() -> set[str]:
    """Every keyword class_capture.py passes to capture.update_metadata()."""
    import ast

    source = (Path(__file__).resolve().parents[1] / "class_capture.py").read_text(
        encoding="utf-8-sig"
    )
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "update_metadata"
            and isinstance(func.value, ast.Name)
            and func.value.id == "capture"
        ):
            names.update(kw.arg for kw in node.keywords if kw.arg)
    return names


def test_every_metadata_field_capture_writes_actually_exists() -> None:
    from nova_capture.models import ClassSessionMetadata

    written = _update_metadata_keywords()
    assert written, "class_capture.py must write session metadata"

    known = set(ClassSessionMetadata.__dataclass_fields__)
    missing = sorted(written - known)
    assert not missing, (
        "class_capture.py writes metadata fields ClassSessionMetadata does not "
        f"define, so finalization will raise AttributeError: {missing}"
    )


def test_the_v137_durable_capture_fields_round_trip(tmp_path: Path) -> None:
    from nova_capture.session import ClassCaptureSession
    from nova_capture.storage import ClassCaptureStorage

    session = ClassCaptureSession(
        "COP3710",
        "Class Session",
        storage=ClassCaptureStorage(tmp_path),
        capture_version="1.3.7",
    )
    path = session.start()

    session.update_metadata(
        transcript_segment_count=1679,
        question_count=86,
        speaker_ids=["0", "1", "2"],
        speaker_roles={},
        live_answers_enabled=True,
        postprocess_enabled=True,
        stt_restarts=1,
        audio_chunks=222,
        audio_seconds=4424.58,
        audio_integrity_ok=True,
        pipeline="livekit",
        recorder_mode="process",
        recorder_isolated=True,
    )
    session.stop(status="completed_with_warnings")

    payload = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert payload["status"] == "completed_with_warnings"
    assert payload["transcript_segment_count"] == 1679
    assert payload["stt_restarts"] == 1
    assert payload["audio_chunks"] == 222
    assert payload["recorder_isolated"] is True
    assert payload["pipeline"] == "livekit"


def test_unknown_metadata_fields_are_still_rejected(tmp_path: Path) -> None:
    """The guard that caught the bug must stay -- typos must not pass silently."""
    from nova_capture.session import ClassCaptureSession
    from nova_capture.storage import ClassCaptureStorage

    session = ClassCaptureSession(
        "COP3710", "Class Session", storage=ClassCaptureStorage(tmp_path)
    )
    session.start()
    with pytest.raises(AttributeError):
        session.update_metadata(definitely_not_a_field=1)


def test_metadata_is_written_before_the_outcome_is_resolved() -> None:
    """A metadata failure must be able to downgrade the session outcome."""
    source = (Path(__file__).resolve().parents[1] / "class_capture.py").read_text(
        encoding="utf-8-sig"
    )
    write_at = source.index("transcript_segment_count=segment_count")
    resolve_at = source.index("outcome = supervisor.finalize(")
    assert write_at < resolve_at, (
        "supervisor.finalize() resolves the outcome, so the metadata write must "
        "happen first or a metadata error is reported after the fact"
    )
