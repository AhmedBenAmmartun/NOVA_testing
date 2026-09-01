"""Live speaker intelligence: confidence that grows, and never a forced answer."""

from __future__ import annotations

from nova_capture.models import SpeakerRole
from nova_capture.speakers import SpeakerRoleTracker


LECTURE = (
    "Alright everyone, let's look at the slide. Today we are covering "
    "normalization and I want you to recall that a superkey uniquely "
    "identifies a row in a relation, which matters for the exam."
)
PLAIN_LECTURE = (
    "So the value moves through the pipeline and then it comes out the other "
    "side and that is basically the whole idea of how this part works here."
)
STUDENT = "Wait, is that on the exam?"


def _feed(tracker, speaker, text, at, times=1):
    for index in range(times):
        tracker.observe(speaker, text, elapsed_seconds=at + index)


def test_confidence_grows_from_unknown_to_professor() -> None:
    """The progression the status display promises: 0.35 -> 0.63 -> 0.91."""
    tracker = SpeakerRoleTracker()

    # 00:20 -- barely any evidence.
    _feed(tracker, "0", PLAIN_LECTURE, 20.0)
    early = tracker.live_assessment("0")
    assert early.role is SpeakerRole.UNKNOWN
    assert early.confidence < 0.45

    # 00:45 -- a real lecture voice plus a student, evidence still partial.
    _feed(tracker, "0", LECTURE, 45.0, times=2)
    _feed(tracker, "1", STUDENT, 70.0)
    middle = tracker.live_assessment("0")
    assert middle.confidence > early.confidence
    assert middle.label in {"Probable Professor", "Professor"}

    # 02:00 -- a lecture's worth of evidence.
    _feed(tracker, "0", LECTURE, 120.0, times=12)
    _feed(tracker, "1", STUDENT, 200.0, times=2)
    late = tracker.live_assessment("0")
    assert late.confidence > middle.confidence
    assert late.role is SpeakerRole.PROFESSOR
    assert late.label == "Professor"
    assert late.confidence >= 0.75


def test_live_labels_never_leak_into_the_authoritative_transcript_role() -> None:
    """Live estimates are for the human watching, not for the study documents."""
    tracker = SpeakerRoleTracker()
    _feed(tracker, "0", LECTURE, 10.0, times=15)
    _feed(tracker, "1", STUDENT, 200.0, times=2)

    assert tracker.live_assessment("0").role is SpeakerRole.PROFESSOR
    # Until finalize_roles(), the transcript still says Speaker 0.
    assert tracker.resolve("0").role is SpeakerRole.UNKNOWN
    assert tracker.resolve("0").label == "Speaker 0"


def test_talk_time_alone_never_earns_the_professor_label() -> None:
    """A monologue with no course-running language stays 'probable' forever."""
    tracker = SpeakerRoleTracker()
    _feed(tracker, "0", PLAIN_LECTURE, 5.0, times=40)
    _feed(tracker, "1", STUDENT, 300.0)

    assessment = tracker.live_assessment("0")
    assert assessment.confidence <= 0.70
    assert assessment.role is not SpeakerRole.PROFESSOR
    assert "no course-running language yet" in assessment.reasons


def test_unknown_stays_possible_when_evidence_is_weak() -> None:
    tracker = SpeakerRoleTracker()
    tracker.observe("0", "Hello.", elapsed_seconds=1.0)
    assessment = tracker.live_assessment("0")
    assert assessment.role is SpeakerRole.UNKNOWN
    assert assessment.stage == "bootstrap"
    assert assessment.confidence < 0.3


def test_a_speaker_with_no_evidence_is_reported_honestly() -> None:
    tracker = SpeakerRoleTracker()
    assessment = tracker.live_assessment("7")
    assert assessment.stage == "no_evidence"
    assert assessment.confidence == 0.0
    assert tracker.live_assessment(None).role is SpeakerRole.UNKNOWN


def test_guest_presenter_does_not_steal_the_professor_identity() -> None:
    """The professor opens the class; the guest talks more. Roles must hold."""
    tracker = SpeakerRoleTracker()

    # Professor runs the first ten minutes.
    _feed(tracker, "0", LECTURE, 10.0, times=6)
    _feed(tracker, "1", STUDENT, 200.0, times=2)

    # A guest arrives at 00:12 and out-talks everyone for the rest of class.
    guest_text = (
        "Thanks for having me. I work at a database company and my team "
        "spends most of its time on query planning and storage engines."
    )
    _feed(tracker, "2", guest_text, 720.0, times=25)

    assert tracker.live_assessment("2").role is not SpeakerRole.PROFESSOR
    assert "Guest" in tracker.live_assessment("2").label

    tracker.finalize_roles()
    assert tracker.teacher_speaker_id() == "0"
    assert tracker.resolve("2").role is SpeakerRole.GUEST
    assert tracker.resolve("2").label == "Guest Speaker"
    assert "2" in tracker.guest_speaker_ids()


def test_interaction_shape_is_part_of_the_evidence() -> None:
    tracker = SpeakerRoleTracker()
    for index in range(6):
        tracker.observe("0", LECTURE, elapsed_seconds=10.0 + index * 30)
        tracker.observe(str(index % 3 + 1), STUDENT, elapsed_seconds=25.0 + index * 30)

    assessment = tracker.live_assessment("0")
    assert any("answered by" in reason for reason in assessment.reasons)


def test_live_snapshot_is_persistable_and_marked_provisional() -> None:
    tracker = SpeakerRoleTracker()
    _feed(tracker, "0", LECTURE, 10.0, times=5)
    _feed(tracker, "1", STUDENT, 120.0)

    snapshot = tracker.live_snapshot()
    assert snapshot["kind"] == "live_provisional"
    assert "provisional" in str(snapshot["note"]).casefold()
    assert set(snapshot["assessments"]) == {"0", "1"}
    assert snapshot["assessments"]["0"]["confidence"] >= 0.0
    assert snapshot["evidence"]["0"]["instructional_signals"] > 0

    import json

    json.dumps(snapshot)  # must be serializable mid-class


def test_manual_teacher_override_is_immediate_and_certain() -> None:
    tracker = SpeakerRoleTracker(teacher_speaker_id="3")
    assessment = tracker.live_assessment("3")
    assert assessment.role is SpeakerRole.PROFESSOR
    assert assessment.confidence == 1.0
    assert assessment.stage == "manual_override"


def test_role_map_carries_both_the_final_and_the_live_view() -> None:
    tracker = SpeakerRoleTracker()
    _feed(tracker, "0", LECTURE, 10.0, times=10)
    _feed(tracker, "1", STUDENT, 200.0, times=2)
    tracker.finalize_roles()

    role_map = tracker.role_map()
    assert role_map["0"]["role"] == "professor"
    assert role_map["0"]["live_role"] in {"professor", "unknown"}
    assert "live_confidence" in role_map["0"]
    assert tracker.snapshot()["version"] == 3
