"""`session.json` must not assert measurements it has not taken yet.

During the real COT3400 lecture on 2026-08-31, `session.json` read:

    audio_chunks: 0, audio_seconds: 0.0, audio_integrity_ok: false,
    recorder_mode: "none", recorder_isolated: false,
    transcript_segment_count: 0, speaker_ids: []

while `health.json` correctly reported 84 chunks, an isolated recorder process,
and a healthy recording. Both files were describing the same live session and
only one of them was true.

The fields are not wrong on purpose: they are *finalization outputs* that live
in a struct written from session start, so until `finalize()` runs they hold
dataclass defaults. The defect is that nothing distinguishes "measured as zero"
from "not measured yet" -- `audio_integrity_ok: false` reads as *the recording
is damaged* when it means *nobody has checked*.

This is the same trust bug as the postprocess status file: a record stating
something with confidence that it has no basis for. The fix is the same shape.
`health.json` stays the live truth; `session.json` stops pretending to be.
"""

from __future__ import annotations

import json
from pathlib import Path

from nova_capture.models import ClassSessionMetadata
from nova_capture.status import session_metrics


def _write(session: Path, name: str, payload: dict) -> None:
    session.mkdir(parents=True, exist_ok=True)
    (session / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_a_fresh_session_does_not_claim_its_metrics_are_final() -> None:
    metadata = ClassSessionMetadata(session_id="s", course="COT3400", title="Class Session")

    assert metadata.metrics_finalized is False


def test_live_metrics_are_reported_as_provisional_not_as_zero(
    tmp_path: Path,
) -> None:
    """The exact COT3400 discrepancy: session.json zeros, health.json truth."""
    _write(
        tmp_path,
        "session.json",
        {
            "session_id": "s",
            "course": "COT3400",
            "status": "recording",
            "audio_chunks": 0,
            "audio_seconds": 0.0,
            "audio_integrity_ok": False,
            "recorder_mode": "none",
            "recorder_isolated": False,
            "metrics_finalized": False,
        },
    )
    _write(
        tmp_path,
        "health.json",
        {
            "session_active": True,
            "audio_written_until": 2444.57,
            "workers": {
                "audio": {
                    "status": "recording",
                    "chunks": 84,
                    "recorded_seconds": 2444.57,
                    "mode": "process",
                    "isolated": True,
                }
            },
        },
    )

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is False
    assert metrics["source"] == "health"
    # The live truth, not the placeholder zeros.
    assert metrics["audio_chunks"] == 84
    assert metrics["recorder_mode"] == "process"
    assert metrics["recorder_isolated"] is True
    assert metrics["audio_seconds"] == 2444.57


def test_an_unmeasured_integrity_flag_is_unknown_not_false(tmp_path: Path) -> None:
    """`false` means damaged. Before anyone scans, the honest answer is None."""
    _write(
        tmp_path,
        "session.json",
        {"session_id": "s", "audio_integrity_ok": False, "metrics_finalized": False},
    )

    assert session_metrics(tmp_path)["audio_integrity_ok"] is None


def test_finalized_metrics_are_taken_from_the_session_record(tmp_path: Path) -> None:
    """Once finalize() has run, session.json IS the authority. health may be stale."""
    _write(
        tmp_path,
        "session.json",
        {
            "session_id": "s",
            "status": "completed",
            "audio_chunks": 122,
            "audio_seconds": 4005.07,
            "audio_integrity_ok": True,
            "recorder_mode": "process",
            "recorder_isolated": True,
            "transcript_segment_count": 729,
            "metrics_finalized": True,
        },
    )
    _write(tmp_path, "health.json", {"workers": {"audio": {"chunks": 3}}})

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is True
    assert metrics["source"] == "session"
    assert metrics["audio_chunks"] == 122
    assert metrics["audio_integrity_ok"] is True
    assert metrics["transcript_segment_count"] == 729


def test_an_older_session_without_the_flag_is_treated_as_finalized(
    tmp_path: Path,
) -> None:
    """Sessions recorded before this change already hold real finalize() values.

    Their `session.json` has no `metrics_finalized` key at all. Treating those
    as provisional would discard correct historical measurements, so a stopped
    session without the flag is trusted.
    """
    _write(
        tmp_path,
        "session.json",
        {
            "session_id": "s",
            "status": "completed_with_warnings",
            "stopped_at": "2026-08-31T17:01:10+00:00",
            "audio_chunks": 122,
            "audio_integrity_ok": True,
        },
    )

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is True
    assert metrics["audio_chunks"] == 122


def test_a_still_recording_session_without_the_flag_is_provisional(
    tmp_path: Path,
) -> None:
    """The COT3400 case: no flag, still recording, so the zeros mean nothing."""
    _write(
        tmp_path,
        "session.json",
        {"session_id": "s", "status": "recording", "audio_chunks": 0},
    )
    _write(tmp_path, "health.json", {"workers": {"audio": {"chunks": 84}}})

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is False
    assert metrics["audio_chunks"] == 84


def test_no_health_file_leaves_live_metrics_unknown_rather_than_zero(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "session.json",
        {"session_id": "s", "status": "recording", "metrics_finalized": False},
    )

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is False
    assert metrics["audio_chunks"] is None
    assert metrics["audio_integrity_ok"] is None


def test_a_missing_session_file_is_not_an_error(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)

    metrics = session_metrics(tmp_path)

    assert metrics["finalized"] is False
    assert metrics["audio_chunks"] is None


def test_finalize_marks_the_metrics_as_final() -> None:
    """Regression guard: the finalize() write must set the flag.

    If a future edit adds a metric to finalize() but forgets the flag, every
    reader silently goes back to trusting placeholder zeros.
    """
    source = Path("class_capture.py").read_text(encoding="utf-8")
    write_at = source.index("transcript_segment_count=segment_count")
    # The finalize() metadata write ends where its error handling begins.
    end = source.index("except Exception", write_at)

    assert "metrics_finalized=True" in source[write_at:end]
