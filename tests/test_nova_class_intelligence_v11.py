from __future__ import annotations

import asyncio
import json
import wave
from datetime import datetime
from pathlib import Path

from nova_capture import (
    ClassCaptureSession,
    ClassCaptureStorage,
    LocalMicrophoneCapture,
    LocalWaveRecorder,
    SpeakerRole,
    TranscriptSegment,
)
from nova_runtime import NovaRuntime
from nova_school.automation import SchoolAutomationService
from nova_school.organizer import SchoolMaterialOrganizer, classify_file
from nova_school.registry import CourseProfile, CourseRegistry
from nova_school.resolver import resolve_current_course
from nova_school.vocabulary import course_stt_keyterms


def registry(tmp_path: Path) -> CourseRegistry:
    item = CourseRegistry(tmp_path / "courses.json")
    item.save(
        [
            CourseProfile(
                code="CEN4065",
                name="Software Architecture and Design",
                aliases=["CEN 4065", "SWDesign"],
                keywords=["UML", "SOLID", "cohesion", "coupling"],
            ),
            CourseProfile(
                code="COT3400",
                name="Design and Analysis of Algorithms",
                aliases=["COT 3400", "Algorithms"],
                keywords=["algorithm", "complexity"],
            ),
        ]
    )
    return item


def test_verified_schedule_resolves_one_course(tmp_path: Path) -> None:
    item = registry(tmp_path)
    item.add_meeting("CEN4065", "Thursday", "14:00", "15:15")
    current = resolve_current_course(
        datetime(2026, 8, 20, 14, 30),
        registry=item,
    )
    assert current is not None
    assert current.code == "CEN4065"


def test_schedule_does_not_guess(tmp_path: Path) -> None:
    assert resolve_current_course(
        datetime(2026, 8, 20, 14, 30),
        registry=registry(tmp_path),
    ) is None


def test_filename_classification(tmp_path: Path) -> None:
    source = tmp_path / "CEN4065_Intro-lec2 (SWDesign).ppt"
    source.write_bytes(b"fixture")
    result = classify_file(
        source,
        registry=registry(tmp_path),
        inspect_content=False,
    )
    assert result.course is not None
    assert result.course.code == "CEN4065"
    assert result.confidence >= 0.80


def test_course_keyterms_are_unique(tmp_path: Path) -> None:
    course = registry(tmp_path).get("CEN4065")
    assert course is not None
    terms = course_stt_keyterms(course)
    assert "CEN4065" in terms
    assert "UML" in terms
    assert len(terms) == len({term.casefold() for term in terms})


def test_organizer_copies_without_deleting_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "CEN4065_week1.txt"
    source.write_text("UML SOLID cohesion", encoding="utf-8")

    import nova_school.organizer as module

    monkeypatch.setattr(
        module,
        "course_materials_root",
        lambda code: tmp_path / "vault" / code,
    )
    monkeypatch.setattr(
        module,
        "school_runtime_root",
        lambda: tmp_path / "runtime",
    )

    organizer = SchoolMaterialOrganizer(registry=registry(tmp_path))
    result = organizer.organize(source)

    assert result.status == "organized"
    assert source.exists()
    assert result.destination is not None
    assert Path(result.destination).exists()

    again = organizer.organize(source)
    assert again.status == "already_organized"
    assert again.destination == result.destination


def test_raw_speaker_id_is_preserved(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "CEN4065",
        "UML",
        storage=ClassCaptureStorage(tmp_path),
    )
    path = session.start()
    assert session.transcript is not None

    session.transcript.append(
        TranscriptSegment(
            0.0,
            3.5,
            "Is that composition?",
            speaker=SpeakerRole.UNKNOWN,
            speaker_id="speaker_2",
            is_question=True,
        )
    )

    payload = json.loads(
        (path / "transcript.jsonl").read_text(encoding="utf-8").strip()
    )
    assert payload["speaker"] == "unknown"
    assert payload["speaker_id"] == "speaker_2"


class FakeStream:
    def __init__(self, *, callback, **kwargs) -> None:
        self.callback = callback

    def start(self) -> None:
        self.callback(b"\x01\x00" * 160, 160, None, None)

    def stop(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_microphone_adapter_uses_shared_recorder(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    recorder = LocalWaveRecorder(
        path,
        sample_rate=16_000,
        channels=1,
        sample_width=2,
    )
    microphone = LocalMicrophoneCapture(
        recorder,
        stream_factory=FakeStream,
    )
    microphone.start()
    microphone.stop()

    with wave.open(str(path), "rb") as handle:
        assert handle.getnframes() == 160


def test_download_automation_is_runtime_managed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    async def scenario() -> None:
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        source = downloads / "CEN4065_notes.txt"
        source.write_text("UML SOLID cohesion", encoding="utf-8")

        import nova_school.organizer as module

        monkeypatch.setattr(
            module,
            "course_materials_root",
            lambda code: tmp_path / "vault" / code,
        )
        monkeypatch.setattr(
            module,
            "school_runtime_root",
            lambda: tmp_path / "runtime",
        )

        service = SchoolAutomationService(
            organizer=SchoolMaterialOrganizer(
                registry=registry(tmp_path)
            ),
            download_directories=(downloads,),
            poll_seconds=1,
        )

        assert await service.scan_once() == []
        results = await service.scan_once()
        assert len(results) == 1
        assert results[0].status == "organized"

        runtime = NovaRuntime()
        job_id = await service.start(runtime)
        assert runtime.jobs.snapshot(job_id) is not None
        await runtime.shutdown()

    asyncio.run(scenario())


def test_root_capture_has_no_duplicate_runtime_classes() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(encoding="utf-8-sig")

    assert "class LocalAudioRecorder" not in source
    assert "class ClassSessionStore" not in source
    assert "ClassCaptureSession(" in source
    assert "LocalMicrophoneCapture(" in source
    assert '"diarize": True' in source
    assert '"keyterm": keyterms' in source
