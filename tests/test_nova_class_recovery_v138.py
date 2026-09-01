"""Fixes forced by the real CEN4934 class on 2026-08-28.

That session recorded 73.7 minutes of audio for a 107-minute class, finalized
as "failed", and produced no post-class notes. Four separate defects caused it,
and each one gets a test here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from nova_capture.audio_chunks import ChunkedAudioRecorder, read_manifest, scan_audio_dir
from nova_capture.class_budget import ClassCloudUsageBudget
from nova_capture.question_detection import (
    is_rhetorical_classroom_filler,
    should_answer_question,
)
from nova_capture.supervisor import CaptureEvent


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "class_capture.py").read_text(encoding="utf-8-sig")


# --- 1. a stalled microphone is recoverable ---------------------------------


def test_a_device_gap_is_recorded_in_the_manifest(tmp_path: Path) -> None:
    """The audio files hold only real audio; the timeline still says where."""
    recorder = ChunkedAudioRecorder(
        tmp_path / "audio", sample_rate=800, chunk_seconds=1.0, fsync=False
    )
    recorder.start()
    recorder.write_pcm(b"\x01\x00" * 1600)      # 2 s
    recorder.note_gap(30.0, reason="audio_device_stall_30s")
    recorder.write_pcm(b"\x01\x00" * 1600)      # 2 s more
    recorder.stop()

    assert recorder.recorded_seconds == pytest.approx(4.0)
    assert recorder.gap_seconds == pytest.approx(30.0)
    assert recorder.timeline_seconds == pytest.approx(34.0)

    records = read_manifest(tmp_path / "audio")
    gaps = [item for item in records if item.get("kind") == "gap"]
    assert len(gaps) == 1
    assert gaps[0]["seconds"] == pytest.approx(30.0)

    # Chunks after the gap sit at their true position in the class, so the
    # transcript still lines up with the audio.
    chunks = [item for item in records if item.get("kind") != "gap"]
    assert chunks[-1]["end_seconds"] == pytest.approx(34.0)


def test_a_recorded_gap_is_not_reported_as_damage(tmp_path: Path) -> None:
    recorder = ChunkedAudioRecorder(
        tmp_path / "audio", sample_rate=800, chunk_seconds=1.0, fsync=False
    )
    recorder.start()
    recorder.write_pcm(b"\x01\x00" * 1600)
    recorder.note_gap(30.0, reason="audio_device_stall_30s")
    recorder.write_pcm(b"\x01\x00" * 1600)
    recorder.stop()

    report = scan_audio_dir(tmp_path / "audio")
    assert report.healthy, "an explained gap is not corruption"
    assert report.timestamp_gaps == [], "the gap already accounts for the jump"
    assert len(report.device_gaps) == 1
    assert report.gap_seconds == pytest.approx(30.0)
    assert report.recorded_seconds == pytest.approx(4.0)
    assert report.timeline_seconds == pytest.approx(34.0)


def test_a_resumed_recorder_keeps_the_gap_offset(tmp_path: Path) -> None:
    first = ChunkedAudioRecorder(
        tmp_path / "audio", sample_rate=800, chunk_seconds=1.0, fsync=False
    )
    first.start()
    first.write_pcm(b"\x01\x00" * 800)
    first.note_gap(30.0, reason="stall")
    first.stop()

    second = ChunkedAudioRecorder(
        tmp_path / "audio", sample_rate=800, chunk_seconds=1.0, fsync=False
    )
    second.start()
    assert second.gap_seconds == pytest.approx(30.0)
    second.write_pcm(b"\x01\x00" * 800)
    second.stop()

    records = [r for r in read_manifest(tmp_path / "audio") if r.get("kind") != "gap"]
    assert records[-1]["end_seconds"] == pytest.approx(32.0)


def test_the_supervisor_restarts_a_dead_recorder() -> None:
    assert "async def restart_recorder(" in SOURCE
    assert "await restart_recorder(detail)" in SOURCE
    assert "NOVA_CLASS_RECORDER_MAX_RESTARTS" in SOURCE
    assert "CaptureEvent.AUDIO_RESTARTED" in SOURCE
    assert CaptureEvent.AUDIO_RESTARTED.value == "AUDIO_RESTARTED"


def test_audio_failure_is_reported_once_not_every_heartbeat() -> None:
    """The 2026-08-28 session wrote 302 identical AUDIO_FAILED events."""
    assert "audio_failure_reported" in SOURCE
    assert "if not audio_failure_reported:" in SOURCE
    assert "nonlocal audio_failure_reported" in SOURCE


def test_the_device_timeout_is_no_longer_instantly_fatal() -> None:
    from nova_capture import recorder_process

    assert recorder_process.DEFAULT_DEVICE_TIMEOUT_SECONDS >= 25.0
    assert recorder_process.DEFAULT_DEVICE_RECOVERY_ATTEMPTS >= 1


# --- 2. Ctrl+C is a stop, not a crash ---------------------------------------


def test_user_initiated_close_is_recognised_as_a_stop() -> None:
    assert "_close_reason_is_user_stop" in SOURCE
    assert '"user_initiated"' in SOURCE
    assert 'supervisor.request_stop(f"agent_session_closed:{reason}")' in SOURCE


def test_a_user_stop_does_not_trigger_a_transcription_restart() -> None:
    handler = SOURCE.split('live_session.on("close")')[1].split("return live_session")[0]
    stop_at = handler.index("_close_reason_is_user_stop")
    restart_at = handler.index("schedule_transcription_restart")
    assert stop_at < restart_at, (
        "a user-initiated close must be handled before the restart path; "
        "on 2026-08-28 Ctrl+C logged 'restarting class transcription'"
    )


# --- 3. STT outages are actually recorded -----------------------------------


def test_an_stt_error_opens_a_transcript_gap() -> None:
    """LiveKit retries internally, so 'close' never fires for a real outage."""
    handler = SOURCE.split('live_session.on("error")')[1].split(
        'live_session.on("close")'
    )[0]
    assert "supervisor.stt_gap_start(" in handler


# --- 4. question precision and budget ---------------------------------------


SYNTHETIC_FALSE_POSITIVES = [
    # Synthetic ASR-like fragments: same grammatical/noise shapes as the
    # regression cases, but no verbatim classroom speech is committed.
    "Alex, What is this?",
    "The chart, sir?",
    "Do not do it.",
    "What are the?",
    "Why you not?",
    "Is there now?",
    "What that is?",
    "Was gonna head back to the lab.",
    "Any questions on that one?",
]

SYNTHETIC_QUESTIONS = [
    # Acronyms are a common short subject of technical questions; the first
    # cut of the precision rules rejected them.
    "What is API?",
    "What is JSON?",
    "What is cohesion.",
    "What is encapsulation",
    "Can you explain inheritance",
    "What is the difference between an interface and an abstract class?",
    "What type of diagram?",
    "Have you seen how many requests this service handles each minute?",
    "Like, where are you getting that value from?",
    "So what needs to be submitted?",
    "Aggregation or composition?",
]


@pytest.mark.parametrize("text", SYNTHETIC_FALSE_POSITIVES)
def test_synthetic_asr_garbage_does_not_spend_a_model_call(text: str) -> None:
    assert not should_answer_question(text)


@pytest.mark.parametrize("text", SYNTHETIC_QUESTIONS)
def test_synthetic_substantive_questions_still_get_answered(text: str) -> None:
    assert should_answer_question(text)


def test_rhetorical_openers_are_matched_by_prefix() -> None:
    assert is_rhetorical_classroom_filler("Any questions on that one?")
    assert is_rhetorical_classroom_filler("Any questions?")
    assert not is_rhetorical_classroom_filler("What is cohesion?")


def test_the_class_cloud_budget_survives_a_full_lecture(monkeypatch) -> None:
    """60/day ran out in under two hours of one real class."""
    monkeypatch.delenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", raising=False)
    assert ClassCloudUsageBudget().daily_request_limit >= 200


# --- version -----------------------------------------------------------------


def test_capture_version_records_these_fixes() -> None:
    match = re.search(r'^CAPTURE_VERSION\s*=\s*"([0-9.]+)"', SOURCE, re.MULTILINE)
    assert match is not None
    parts = tuple(int(value) for value in match.group(1).split("."))
    assert parts >= (1, 3, 8)
