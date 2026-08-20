from __future__ import annotations

import json
import wave
from pathlib import Path

from nova_capture import (
    ClassCaptureSession,
    ClassCaptureState,
    ClassCaptureStorage,
    LocalWaveRecorder,
    MarkerKind,
    QuestionRecord,
    SpeakerRole,
    TranscriptSegment,
)


def test_class_capture_uses_explicit_local_root(tmp_path: Path) -> None:
    storage = ClassCaptureStorage(tmp_path / "capture")
    session = ClassCaptureSession(
        "COP 4610",
        "CPU Scheduling",
        storage=storage,
    )
    path = session.start()
    assert path.is_relative_to((tmp_path / "capture").resolve())
    assert "AI Agent" not in str(path)
    assert session.state is ClassCaptureState.ACTIVE


def test_session_metadata_is_written_and_stopped(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "COP 4610",
        "Round Robin",
        storage=ClassCaptureStorage(tmp_path),
    )
    path = session.start()
    initial = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert initial["course"] == "COP 4610"
    assert initial["stopped_at"] is None

    session.stop()
    final = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert final["stopped_at"] is not None
    assert session.state is ClassCaptureState.STOPPED


def test_transcript_keeps_timestamp_speaker_topic(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "COP 4610",
        "Scheduling",
        storage=ClassCaptureStorage(tmp_path),
    )
    session.start()
    assert session.transcript is not None
    segment = TranscriptSegment(
        10.0,
        14.5,
        "A smaller quantum improves responsiveness.",
        speaker=SpeakerRole.PROFESSOR,
        speaker_confidence=0.86,
        topic="Round Robin",
    )
    session.transcript.append(segment)
    recent = session.transcript.recent(1)
    assert recent[0].speaker is SpeakerRole.PROFESSOR
    assert recent[0].topic == "Round Robin"


def test_markers_inherit_current_topic(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "COP 4610",
        "Scheduling",
        storage=ClassCaptureStorage(tmp_path),
    )
    session.start()
    session.context.set_topic("Round Robin", subtopic="Quantum")
    marker = session.mark(
        31.4,
        "Professor repeated the context-switch tradeoff.",
        kind=MarkerKind.EXAM_LIKELY,
    )
    assert marker.topic == "Round Robin"
    assert marker.kind is MarkerKind.EXAM_LIKELY


def test_student_question_record_keeps_answer_and_study_value(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "COP 4610",
        "Scheduling",
        storage=ClassCaptureStorage(tmp_path),
    )
    session.start()
    assert session.questions is not None
    question = QuestionRecord(
        31.5,
        "Is a smaller quantum always better?",
        answer="No. Very small quantum values increase context-switch overhead.",
        speaker=SpeakerRole.STUDENT,
        topic="Round Robin",
        study_value="high",
    )
    session.questions.add(question)
    stored = session.questions.items()
    assert stored[0].speaker is SpeakerRole.STUDENT
    assert stored[0].answer is not None
    assert stored[0].study_value == "high"


def test_lecture_context_tracks_topic_changes(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "COP 4610",
        "Scheduling",
        storage=ClassCaptureStorage(tmp_path),
    )
    session.start()
    session.context.set_topic("SJF")
    session.context.set_topic("Round Robin", subtopic="Quantum")
    snapshot = session.context.snapshot()
    assert snapshot["prior_topic"] == "SJF"
    assert snapshot["current_topic"] == "Round Robin"
    assert snapshot["current_subtopic"] == "Quantum"


def test_local_wave_recorder_pause_resume_and_valid_wav(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    recorder = LocalWaveRecorder(
        path,
        sample_rate=16_000,
        channels=1,
        sample_width=2,
    )
    recorder.start()
    recorder.write_pcm(b"\x00\x00" * 160)
    recorder.pause()
    recorder.write_pcm(b"\x01\x00" * 160)
    recorder.resume()
    recorder.write_pcm(b"\x02\x00" * 160)
    recorder.stop()

    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 320


def test_foundation_does_not_auto_activate_microphone() -> None:
    root = Path(__file__).resolve().parents[1]
    combined = "\n".join(
        (root / "nova_capture" / name).read_text(encoding="utf-8-sig")
        for name in (
            "session.py",
            "recorder.py",
            "storage.py",
        )
    )
    assert "getUserMedia" not in combined
    assert "setMicrophone" not in combined
    assert "MicrophoneTrack" not in combined
