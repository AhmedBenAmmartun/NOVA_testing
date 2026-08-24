from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nova_capture.intelligence import LiveQAManager
from nova_capture.models import QuestionRecord, SpeakerRole, TranscriptSegment
from nova_capture.presentation import build_presentation, parse_outline
from nova_capture.question_detection import (
    is_rhetorical_classroom_filler,
    looks_like_question,
    should_answer_question,
)
from nova_capture.questions import QuestionAssembler, QuestionJournal
from nova_capture.speakers import SpeakerRoleTracker
from nova_capture import postprocess
from nova_school.context import CourseContextLibrary, attach_material_to_session


def test_question_detector_handles_missing_question_mark_and_rhetorical_filler() -> None:
    assert looks_like_question("Can you explain composition")
    assert looks_like_question("What is cohesion.")
    assert not looks_like_question("Composition is strong ownership.")
    assert is_rhetorical_classroom_filler("Any questions?")
    assert not should_answer_question("Any questions?")
    assert should_answer_question("What is composition")


def test_question_assembler_detects_question_punctuated_as_statement() -> None:
    assembler = QuestionAssembler()
    outputs = assembler.feed(
        TranscriptSegment(0, 3, "Can you explain the observer pattern.", speaker_id="1")
    )
    assert len(outputs) == 1
    assert outputs[0].question == "Can you explain the observer pattern."



def test_question_assembler_separates_unpunctuated_statement_from_new_question() -> None:
    assembler = QuestionAssembler()
    assert assembler.feed(TranscriptSegment(0, 2, "Today we cover UML", speaker_id="0")) == []
    outputs = assembler.feed(TranscriptSegment(2, 4, "What is aggregation?", speaker_id="0"))
    assert len(outputs) == 1
    assert outputs[0].question == "What is aggregation?"

def test_speaker_tracker_does_not_assume_first_voice_is_teacher() -> None:
    tracker = SpeakerRoleTracker(
        observation_seconds=20,
        minimum_total_words=20,
        dominance_ratio=1.35,
        minimum_share=0.45,
        minimum_teacher_words=40,
        minimum_teacher_speech_seconds=15,
    )
    # A student speaks first, briefly. Automatic classroom roles remain raw
    # during capture instead of being locked from partial evidence.
    tracker.observe("student-first", "Is this the right room", elapsed_seconds=2)
    assert tracker.resolve("student-first").role is SpeakerRole.UNKNOWN

    professor_text = " ".join(["architecture"] * 90)
    tracker.observe("professor", professor_text, elapsed_seconds=25)
    tracker.observe("professor", professor_text, elapsed_seconds=35)

    assert tracker.teacher_speaker_id() is None
    assert tracker.resolve("professor").role is SpeakerRole.UNKNOWN

    tracker.finalize_roles()
    assert tracker.teacher_speaker_id() == "professor"
    assert tracker.resolve("professor").role is SpeakerRole.PROFESSOR
    assert tracker.resolve("student-first").role is SpeakerRole.STUDENT


def test_speaker_tracker_supports_manual_teacher_override() -> None:
    tracker = SpeakerRoleTracker(teacher_speaker_id="7")
    assert tracker.resolve("7").role is SpeakerRole.PROFESSOR
    assert tracker.resolve("9").role is SpeakerRole.STUDENT
    assert tracker.resolve("7").confidence == 1.0


def test_question_journal_rewrites_answer_and_role(tmp_path: Path) -> None:
    journal = QuestionJournal(tmp_path / "questions.jsonl")
    question = journal.add(
        QuestionRecord(1.5, "What is UML?", speaker_id="2")
    )
    journal.update_answer(question, "Unified Modeling Language.")

    class Resolver:
        role = SpeakerRole.STUDENT

    journal.apply_speaker_roles(lambda _: Resolver())
    payload = json.loads((tmp_path / "questions.jsonl").read_text(encoding="utf-8"))
    assert payload["answer"] == "Unified Modeling Language."
    assert payload["speaker"] == "student"


def test_attach_material_copies_without_deleting_original(tmp_path: Path) -> None:
    source = tmp_path / "CEN4065 slides.txt"
    source.write_text("UML SOLID cohesion", encoding="utf-8")
    session = tmp_path / "session"
    session.mkdir()

    first = attach_material_to_session(source, session)
    second = attach_material_to_session(source, session)

    assert source.exists()
    assert Path(first.destination).exists()
    assert first.destination == second.destination
    lines = (session / "attachments.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2


def test_course_context_reads_session_attachment_and_prior_note(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import nova_school.context as module

    materials = tmp_path / "materials"
    sessions = tmp_path / "sessions"
    session = tmp_path / "raw"
    materials.mkdir()
    sessions.mkdir()
    session.mkdir()
    (session / "Materials").mkdir()

    (materials / "slides.txt").write_text("Observer pattern and UML", encoding="utf-8")
    prior = sessions / "2026-08-20" / "lecture"
    prior.mkdir(parents=True)
    (prior / "Lecture.md").write_text("Cohesion and coupling", encoding="utf-8")
    (session / "Materials" / "project.txt").write_text("Bookstore observer implementation", encoding="utf-8")

    monkeypatch.setattr(module, "course_materials_root", lambda _: materials)
    monkeypatch.setattr(module, "course_sessions_root", lambda _: sessions)

    library = CourseContextLibrary("CEN4065", session_path=session, max_chars=20_000)
    context, sources = library.build_context("observer")

    assert "Bookstore observer implementation" in context
    assert "Observer pattern and UML" in context
    assert any(item.source_kind == "prior_note" for item in sources)


def test_live_qa_logs_grounded_answer(tmp_path: Path, monkeypatch) -> None:
    import nova_capture.intelligence as module

    async def fake_route(task: str, *, role: str = "reasoning") -> str:
        assert "UML" in task
        assert "course material" in task
        return "UML is a modeling language used to represent software structure and behavior."

    async def fake_popup(question: str, answer: str) -> None:
        return None

    monkeypatch.setattr(module, "_route", fake_route)
    monkeypatch.setattr(module, "show_answer_popup", fake_popup)

    manager = LiveQAManager(
        session_path=tmp_path,
        material_context_provider=lambda query: (
            "course material: UML diagrams",
            [],
        ),
    )
    question = QuestionRecord(5.0, "What is UML?", speaker_id="1")
    answer = asyncio.run(
        manager.answer(
            question,
            recent_segments=[TranscriptSegment(0, 4, "Today we use UML", speaker_id="0")],
            course_code="CEN4065",
            course_name="Software Architecture and Design",
            current_topic="UML",
        )
    )
    assert answer is not None
    log = (tmp_path / "Live Q&A.md").read_text(encoding="utf-8")
    assert "What is UML?" in log
    assert "modeling language" in log


def test_outline_builds_real_pptx(tmp_path: Path) -> None:
    outline = "# UML\n- Diagrams model software\n- Class diagrams show structure\n# SOLID\n- Design principles"
    parsed = parse_outline(outline)
    assert parsed[0][0] == "UML"
    target = build_presentation(
        outline,
        tmp_path / "Presentation.pptx",
        course="CEN4065",
        title="Class Session",
    )
    assert target.exists()
    assert target.stat().st_size > 1000


def test_postprocess_falls_back_without_ai_and_writes_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session = tmp_path / "raw" / "CEN4065" / "session1"
    session.mkdir(parents=True)
    (session / "session.json").write_text(
        json.dumps(
            {
                "session_id": "session1",
                "course": "CEN4065",
                "title": "UML Lecture",
                "started_at": "2026-08-23T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (session / "transcript.jsonl").write_text(
        json.dumps(
            {
                "start_seconds": 0,
                "end_seconds": 5,
                "text": "UML models software structure.",
                "speaker": "unknown",
                "speaker_id": "0",
            }
        ) + "\n",
        encoding="utf-8",
    )
    (session / "questions.jsonl").write_text("", encoding="utf-8")
    (session / "speaker_roles.json").write_text(
        json.dumps(
            {
                "speakers": {
                    "0": {"label": "Teacher", "role": "professor", "confidence": 0.9}
                }
            }
        ),
        encoding="utf-8",
    )

    output_root = tmp_path / "vault_sessions"
    monkeypatch.setattr(postprocess, "course_sessions_root", lambda _: output_root)

    import nova_school.context as context_module
    monkeypatch.setattr(context_module, "course_materials_root", lambda _: tmp_path / "materials")
    monkeypatch.setattr(context_module, "course_sessions_root", lambda _: tmp_path / "prior")

    async def unavailable(task: str, *, role: str = "reasoning"):
        return None

    monkeypatch.setattr(postprocess, "_route", unavailable)

    folder = asyncio.run(postprocess.process_session(session))
    for name in (
        "Source Transcript.md",
        "Evidence.md",
        "Lecture.md",
        "Summary.md",
        "Study.md",
        "Questions.md",
        "Presentation Outline.md",
        "Presentation.pptx",
    ):
        assert (folder / name).exists(), name

    source = (folder / "Source Transcript.md").read_text(encoding="utf-8")
    assert "Teacher" in source
    state = json.loads((session / "postprocess.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed"


def test_root_capture_wires_v13_intelligence_without_replacing_capture_architecture() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(encoding="utf-8-sig")
    assert 'CAPTURE_VERSION = "1.3' in source
    assert "ClassCaptureSession(" in source
    assert "LocalMicrophoneCapture(" in source
    assert "SpeakerRoleTracker(" in source
    assert "QuestionAssembler()" in source
    assert "LiveQAManager(" in source
    assert "CourseContextLibrary(" in source
    assert "launch_postprocess(" in source
    assert '"diarize": True' in source
    assert '"keyterm": keyterms' in source
    assert "class LocalAudioRecorder" not in source
    assert "class ClassSessionStore" not in source


def test_recent_download_scan_only_organizes_matching_course(tmp_path: Path, monkeypatch) -> None:
    import nova_school.context as module
    import nova_school.organizer as organizer_module

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    matching = downloads / "CEN4065_UML_notes.txt"
    other = downloads / "COP3710_ETL_notes.txt"
    matching.write_text("UML SOLID cohesion", encoding="utf-8")
    other.write_text("ETL pipeline SQL", encoding="utf-8")

    from nova_school.registry import CourseProfile, CourseRegistry
    registry_path = tmp_path / "courses.json"
    registry = CourseRegistry(registry_path)
    registry.save([
        CourseProfile(code="CEN4065", name="Architecture", keywords=["UML", "SOLID", "cohesion"]),
        CourseProfile(code="COP3710", name="Data", keywords=["ETL", "pipeline", "SQL"]),
    ])

    monkeypatch.setattr(module, "default_download_directories", lambda: (downloads,), raising=False)
    # The helper imports inside the function, so patch the source modules.
    import nova_school.automation as auto_module
    import nova_school.registry as registry_module
    monkeypatch.setattr(auto_module, "default_download_directories", lambda: (downloads,))
    monkeypatch.setattr(registry_module, "default_registry_path", lambda: registry_path)
    monkeypatch.setattr(organizer_module, "course_materials_root", lambda code: tmp_path / "vault" / code)
    monkeypatch.setattr(organizer_module, "school_runtime_root", lambda: tmp_path / "runtime")

    results = module.organize_recent_downloads_for_course("CEN4065")
    assert len(results) == 1
    assert results[0].course_code == "CEN4065"
    assert matching.exists()
    assert other.exists()
