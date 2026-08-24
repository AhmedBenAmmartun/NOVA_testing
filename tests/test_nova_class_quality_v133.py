from __future__ import annotations

import json
from pathlib import Path

from nova_capture.intelligence import LiveQAManager
from nova_capture.models import QuestionRecord, SpeakerRole, TranscriptSegment
from nova_capture.question_detection import looks_like_question, should_answer_question
from nova_capture.questions import QuestionAssembler
from nova_capture.speakers import SpeakerResolution, SpeakerRoleTracker
from nova_school.context import CourseContextLibrary


def test_single_speaker_is_not_auto_promoted_to_teacher() -> None:
    tracker = SpeakerRoleTracker(
        minimum_total_words=40,
        minimum_teacher_words=40,
        minimum_teacher_speech_seconds=15,
    )
    tracker.observe("0", " ".join(["architecture"] * 220), elapsed_seconds=180)
    assert tracker.resolve("0").role is SpeakerRole.UNKNOWN
    tracker.finalize_roles()
    assert tracker.teacher_speaker_id() is None
    assert tracker.snapshot()["inference_reason"] == "insufficient_distinct_speakers"


def test_demo_session_does_not_mislabel_late_dominant_speaker_as_teacher() -> None:
    tracker = SpeakerRoleTracker(
        minimum_total_words=180,
        dominance_ratio=1.55,
        minimum_share=0.58,
        minimum_teacher_words=100,
        minimum_teacher_speech_seconds=40,
        teacher_start_window_seconds=90,
    )
    tracker.observe("0", " ".join(["first"] * 113), elapsed_seconds=12.8)
    tracker.observe("1", " ".join(["second"] * 227), elapsed_seconds=127.5)
    tracker.finalize_roles()
    assert tracker.teacher_speaker_id() is None
    assert tracker.snapshot()["inference_reason"] == "dominant_speaker_started_too_late"
    assert tracker.resolve("0").label == "Speaker 0"
    assert tracker.resolve("1").label == "Speaker 1"


def test_completed_lecture_can_still_resolve_strong_teacher() -> None:
    tracker = SpeakerRoleTracker(
        minimum_total_words=180,
        dominance_ratio=1.55,
        minimum_share=0.58,
        minimum_teacher_words=100,
        minimum_teacher_speech_seconds=40,
    )
    tracker.observe("0", " ".join(["architecture"] * 300), elapsed_seconds=5)
    tracker.observe("1", " ".join(["question"] * 60), elapsed_seconds=150)
    tracker.finalize_roles()
    assert tracker.teacher_speaker_id() == "0"
    assert tracker.resolve("0").role is SpeakerRole.PROFESSOR
    assert tracker.resolve("1").role is SpeakerRole.STUDENT


def test_statement_fragments_are_not_questions() -> None:
    assert not looks_like_question("can just stick there.")
    assert not looks_like_question("Have an Indian professor.")
    assert not should_answer_question("can just stick there.")
    assert not should_answer_question("Have an Indian professor.")


def test_real_unpunctuated_questions_still_work() -> None:
    assert looks_like_question("Can you explain dependency inversion")
    assert looks_like_question("Is the one for our actual chapter.")
    assert should_answer_question("What is cohesion.")


def test_discourse_leadin_keeps_split_question_together() -> None:
    assembler = QuestionAssembler()
    first = assembler.feed(
        TranscriptSegment(0, 1, "Like, where are you", speaker_id="1")
    )
    assert first == []
    second = assembler.feed(
        TranscriptSegment(1, 2, "getting theta from?", speaker_id="1")
    )
    assert len(second) == 1
    assert second[0].question == "Like, where are you getting theta from?"


def test_prior_generated_notes_cannot_pollute_stt_keyterms(
    tmp_path: Path,
    monkeypatch,
) -> None:
    material = tmp_path / "lecture.txt"
    prior = tmp_path / "Source Transcript.md"
    material.write_text(
        "Aggregation composition repository repository repository",
        encoding="utf-8",
    )
    prior.write_text(
        "aggression aggression aggression compulsion compulsion compulsion",
        encoding="utf-8",
    )
    library = CourseContextLibrary("CEN4065", session_path=tmp_path)
    monkeypatch.setattr(
        library,
        "_candidate_files",
        lambda: [
            (material, "course_material"),
            (prior, "prior_note"),
        ],
    )
    terms = library.build_stt_keyterms(
        ["aggregation", "composition"],
        limit=100,
        max_material_terms=30,
    )
    lowered = {item.casefold() for item in terms}
    assert "aggregation" in lowered
    assert "composition" in lowered
    assert "repository" in lowered
    assert "aggression" not in lowered
    assert "compulsion" not in lowered


def test_live_qa_rebuild_uses_final_role_map(tmp_path: Path) -> None:
    manager = LiveQAManager(
        session_path=tmp_path,
        material_context_provider=lambda _query: ("", []),
    )
    question = QuestionRecord(
        5.0,
        "What is cohesion?",
        speaker=SpeakerRole.UNKNOWN,
        speaker_id="0",
    )
    manager._record_event(question, "Cohesion groups related responsibilities.", [], None)
    before = (tmp_path / "Live Q&A.md").read_text(encoding="utf-8")
    assert "— unknown" in before

    def resolver(_speaker_id):
        return SpeakerResolution(SpeakerRole.PROFESSOR, "Teacher", 0.9)

    manager.rebuild_log(resolver)
    after = (tmp_path / "Live Q&A.md").read_text(encoding="utf-8")
    assert "— professor" in after
    events = [
        json.loads(line)
        for line in (tmp_path / "live_qa_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events[0]["speaker_id"] == "0"
    assert events[0]["speaker_at_answer"] == "unknown"


def test_root_capture_finalizes_roles_and_q_and_a_consistently() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(encoding="utf-8-sig")
    assert 'CAPTURE_VERSION = "1.3.' in source
    assert "speaker_tracker.finalize_roles()" in source
    assert "qa_manager.rebuild_log(speaker_tracker.resolve)" in source
