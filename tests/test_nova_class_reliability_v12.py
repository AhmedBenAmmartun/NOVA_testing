from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nova_capture import (
    ClassCaptureSession,
    ClassCaptureStorage,
    QuestionAssembler,
    SpeakerRole,
    TranscriptSegment,
)
from nova_capture import control
from nova_school.automation import SchoolAutomationService
from nova_school.organizer import (
    OrganizeResult,
    SchoolMaterialOrganizer,
    classify_file,
)
from nova_school.registry import CourseProfile, CourseRegistry


def _registry(path: Path) -> CourseRegistry:
    registry = CourseRegistry(path)
    registry.save(
        [
            CourseProfile(
                code="CEN4065",
                name="Software Architecture and Design",
                aliases=["CEN 4065", "SWDesign"],
                keywords=["UML", "SOLID", "cohesion", "coupling"],
            ),
            CourseProfile(
                code="COP3710",
                name="Introduction to Data Engineering",
                aliases=["COP 3710", "Data Engineering"],
                keywords=["ETL", "pipeline", "database", "SQL"],
            ),
        ]
    )
    return registry


def test_session_defaults_notes_on_once_v13_postprocess_exists(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "CEN4065",
        "Architecture",
        storage=ClassCaptureStorage(tmp_path),
    )
    path = session.start()

    metadata = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert metadata["notes_enabled"] is True
    assert metadata["capture_version"] == "1.3"
    assert metadata["status"] == "recording"

    for name in (
        "transcript.jsonl",
        "transcript.txt",
        "markers.jsonl",
        "questions.jsonl",
        "topics.jsonl",
    ):
        assert (path / name).exists(), name


def test_readable_transcript_is_derived_from_jsonl(tmp_path: Path) -> None:
    session = ClassCaptureSession(
        "CEN4065",
        "Architecture",
        storage=ClassCaptureStorage(tmp_path),
    )
    path = session.start()
    assert session.transcript is not None

    session.transcript.append(
        TranscriptSegment(
            12.0,
            14.0,
            "UML models software structure.",
            speaker=SpeakerRole.UNKNOWN,
            speaker_id="0",
        )
    )

    jsonl = (path / "transcript.jsonl").read_text(encoding="utf-8")
    readable = (path / "transcript.txt").read_text(encoding="utf-8")
    assert '"speaker_id": "0"' in jsonl
    assert "[speaker=0] UML models software structure." in readable


def test_question_assembler_merges_fragmented_stt_question() -> None:
    assembler = QuestionAssembler()

    parts = [
        TranscriptSegment(0, 2, "What is the difference between", speaker_id="0"),
        TranscriptSegment(2, 3, "aggregation", speaker_id="0"),
        TranscriptSegment(3, 4, "and composition?", speaker_id="0"),
    ]

    questions = []
    for part in parts:
        questions.extend(assembler.feed(part))

    assert len(questions) == 1
    assert questions[0].question == (
        "What is the difference between aggregation and composition?"
    )
    assert questions[0].speaker is SpeakerRole.UNKNOWN
    assert questions[0].speaker_id == "0"


def test_stop_with_no_active_session_does_not_leave_stale_signal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(control, "control_root", lambda: tmp_path)

    assert control.request_stop() is None
    assert not control.stop_request_path().exists()


def test_duplicate_capture_claim_is_rejected_and_release_recovers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(control, "control_root", lambda: tmp_path)

    first = control.claim_active_session(
        session_id="first",
        course="CEN4065",
        session_path=tmp_path / "first",
    )
    assert first.session_id == "first"

    with pytest.raises(control.ActiveClassCaptureError):
        control.claim_active_session(
            session_id="second",
            course="COP3710",
            session_path=tmp_path / "second",
        )

    assert control.release_active_session("first")

    second = control.claim_active_session(
        session_id="second",
        course="COP3710",
        session_path=tmp_path / "second",
    )
    assert second.session_id == "second"
    assert control.release_active_session("second")


def test_stop_request_is_bound_to_specific_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(control, "control_root", lambda: tmp_path)

    control.claim_active_session(
        session_id="session-a",
        course="CEN4065",
        session_path=tmp_path / "session-a",
    )
    active = control.request_stop()
    assert active is not None

    payload = json.loads(
        control.stop_request_path().read_text(encoding="utf-8")
    )
    assert payload["target_session_id"] == "session-a"
    control.release_active_session("session-a")


class _FakeOrganizer:
    def __init__(self) -> None:
        self.calls = 0

    def organize(self, path: Path) -> OrganizeResult:
        self.calls += 1
        return OrganizeResult(
            str(path),
            str(path) + ".copy",
            "CEN4065",
            1.0,
            "organized",
            ["test"],
        )


def test_download_watcher_persists_handled_signatures(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        source = downloads / "CEN4065_notes.txt"
        source.write_text("UML", encoding="utf-8")
        state = tmp_path / "downloads_state.json"

        first_organizer = _FakeOrganizer()
        first = SchoolAutomationService(
            organizer=first_organizer,
            download_directories=(downloads,),
            poll_seconds=1,
            state_path=state,
        )
        assert await first.scan_once() == []
        results = await first.scan_once()
        assert len(results) == 1
        assert first_organizer.calls == 1
        assert state.exists()

        second_organizer = _FakeOrganizer()
        second = SchoolAutomationService(
            organizer=second_organizer,
            download_directories=(downloads,),
            poll_seconds=1,
            state_path=state,
        )
        assert await second.scan_once() == []
        assert second_organizer.calls == 0

    asyncio.run(scenario())


def test_classifier_refuses_ambiguous_tie(tmp_path: Path) -> None:
    registry = CourseRegistry(tmp_path / "courses.json")
    registry.save(
        [
            CourseProfile(
                code="AAA1000",
                name="Alpha",
                aliases=["shared course"],
            ),
            CourseProfile(
                code="BBB1000",
                name="Beta",
                aliases=["shared course"],
            ),
        ]
    )
    source = tmp_path / "shared course notes.txt"
    source.write_text("", encoding="utf-8")

    result = classify_file(
        source,
        registry=registry,
        inspect_content=False,
    )
    assert result.course is None
    assert result.confidence == pytest.approx(0.65)
    assert "ambiguous" in " ".join(result.reasons).lower()


def test_organizer_turns_failures_into_error_results(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "CEN4065_notes.txt"
    source.write_text("UML", encoding="utf-8")

    organizer = SchoolMaterialOrganizer(
        registry=_registry(tmp_path / "courses.json")
    )

    import nova_school.organizer as module

    def fail_root(code: str) -> Path:
        raise PermissionError("test failure")

    monkeypatch.setattr(module, "course_materials_root", fail_root)

    result = organizer.organize(source)
    assert result.status == "error"
    assert "PermissionError" in " ".join(result.reasons)


def test_root_capture_tracks_context_questions_and_lifecycle() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(encoding="utf-8-sig")

    assert "claim_active_session(" in source
    assert "heartbeat_active_session(" in source
    assert "release_active_session(" in source
    assert "capture.context.add_transcript(segment)" in source
    assert "QuestionAssembler()" in source
    assert "notes_enabled=postprocess_enabled" in source
