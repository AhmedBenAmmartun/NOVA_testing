"""A correction must earn its way from guess to knowledge.

The flat `STT-Corrections.md` file works because Ahmed wrote every line himself:
each rule is already ground truth. It cannot represent anything NOVA *noticed*,
because it has no way to say "I think I saw this twice and I am not sure yet".

That is the whole difficulty. A correction NOVA infers is a guess, and one
guess must never become permanent knowledge -- that is how a mishearing turns
into a fabricated definition, which is exactly what `GNRO >= N` did to a real
COT3400 lecture. So an inferred correction starts as a *candidate*, accumulates
independent evidence, and only becomes applicable once it is confirmed.

Two things stay true throughout:

* The raw transcript is never rewritten. Corrections apply to the derived view.
* Only CONFIRMED corrections are applied. A candidate is retained, counted, and
  visible -- but it does not get to change what NOVA believes.

Scope matters as much as confidence. "consents" -> "constants" is right in an
algorithms lecture and wrong in a conversation about consent forms, so a
correction records where it applies and the most specific scope wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nova_knowledge.knowledge_db import (
    CorrectionScope,
    CorrectionStatus,
    KnowledgeStore,
)


@pytest.fixture
def store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(tmp_path / "knowledge.sqlite3")


# --- the store exists and follows the repo's SQLite conventions --------------


def test_the_store_creates_itself_and_records_its_schema_version(store) -> None:
    assert store.schema_version() >= 1


def test_the_store_is_reopenable(tmp_path: Path) -> None:
    first = KnowledgeStore(tmp_path / "k.sqlite3")
    first.observe_correction("GNRO", "g(n)", course_code="COT3400")

    second = KnowledgeStore(tmp_path / "k.sqlite3")

    assert second.find_correction("GNRO", course_code="COT3400") is not None


# --- candidate -> confirmed ---------------------------------------------------


def test_an_observed_correction_starts_as_a_candidate(store) -> None:
    """NOVA noticing something is not NOVA knowing it."""
    record = store.observe_correction("GNRO", "g(n)", course_code="COT3400")

    assert record.status is CorrectionStatus.CANDIDATE
    assert record.times_seen == 1
    assert record.times_confirmed == 0


def test_a_candidate_is_not_applied(store) -> None:
    """The load-bearing rule: an unverified guess changes nothing."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")

    assert store.active_corrections(course_code="COT3400") == ()


def test_seeing_the_same_thing_again_counts_but_does_not_confirm(store) -> None:
    """Repetition is not verification. The recognizer can be wrong twice."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    record = store.observe_correction("GNRO", "g(n)", course_code="COT3400")

    assert record.times_seen == 2
    assert record.status is CorrectionStatus.CANDIDATE


def test_user_confirmation_promotes_a_candidate(store) -> None:
    """Ahmed was in the room. His confirmation is the strongest evidence."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")

    record = store.confirm_correction(
        "GNRO", course_code="COT3400", source="user", detail="Ahmed confirmed"
    )

    assert record.status is CorrectionStatus.CONFIRMED
    assert record.times_confirmed == 1


def test_a_confirmed_correction_becomes_active(store) -> None:
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    store.confirm_correction("GNRO", course_code="COT3400", source="user")

    active = store.active_corrections(course_code="COT3400")

    assert ("GNRO", "g(n)") in [(r.heard_text, r.corrected_text) for r in active]


def test_a_user_authored_rule_is_confirmed_on_arrival(store) -> None:
    """Rules Ahmed typed into STT-Corrections.md are already ground truth."""
    record = store.observe_correction(
        "consents", "constants", course_code="COT3400", source="user_file"
    )

    assert record.status is CorrectionStatus.CONFIRMED


# --- contradiction ------------------------------------------------------------


def test_contradiction_lowers_confidence(store) -> None:
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    store.confirm_correction("GNRO", course_code="COT3400", source="user")
    before = store.find_correction("GNRO", course_code="COT3400").confidence

    after = store.contradict_correction(
        "GNRO", course_code="COT3400", detail="heard clearly as GNR-oh"
    )

    assert after.confidence < before


def test_enough_contradiction_retires_a_rule(store) -> None:
    """Evidence against must be able to undo evidence for."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    store.confirm_correction("GNRO", course_code="COT3400", source="user")

    for _ in range(5):
        record = store.contradict_correction("GNRO", course_code="COT3400")

    assert record.status is CorrectionStatus.REJECTED
    assert store.active_corrections(course_code="COT3400") == ()


def test_a_rejected_rule_is_retained_not_deleted(store) -> None:
    """History is evidence. A retired rule explains a past note revision."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    for _ in range(6):
        store.contradict_correction("GNRO", course_code="COT3400")

    assert store.find_correction("GNRO", course_code="COT3400") is not None


# --- scope --------------------------------------------------------------------


def test_a_course_correction_does_not_leak_into_another_course(store) -> None:
    """"consents"->"constants" is right in algorithms, wrong in a consent form."""
    store.observe_correction(
        "consents", "constants", course_code="COT3400", source="user_file"
    )

    assert store.active_corrections(course_code="COP3710") == ()


def test_a_global_correction_applies_everywhere(store) -> None:
    store.observe_correction(
        "novah", "NOVA", scope=CorrectionScope.GLOBAL, source="user_file"
    )

    assert store.active_corrections(course_code="COT3400")


def test_the_most_specific_scope_wins(store) -> None:
    """A course rule must beat a global one for the same heard text."""
    store.observe_correction(
        "big o", "Big O", scope=CorrectionScope.GLOBAL, source="user_file"
    )
    store.observe_correction(
        "big o", "O(g(n))", course_code="COT3400", source="user_file"
    )

    active = {r.heard_text: r.corrected_text for r in store.active_corrections(
        course_code="COT3400"
    )}

    assert active["big o"] == "O(g(n))"


# --- provenance ---------------------------------------------------------------


def test_every_correction_records_why_nova_believes_it(store) -> None:
    """Section 10: a note must be able to answer "why do you believe this?"."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    store.confirm_correction(
        "GNRO",
        course_code="COT3400",
        source="course_material",
        detail="slide 19 of COT 3400 - 3 Asymptotic analysis.pptx",
    )

    evidence = store.correction_evidence("GNRO", course_code="COT3400")

    assert any("slide 19" in item.detail for item in evidence)


def test_evidence_records_its_kind_and_time(store) -> None:
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")
    store.confirm_correction(
        "GNRO", course_code="COT3400", source="user", detail="confirmed in class"
    )

    item = store.correction_evidence("GNRO", course_code="COT3400")[-1]

    assert item.source == "user"
    assert item.recorded_at


def test_nova_does_not_fabricate_evidence_it_does_not_have(store) -> None:
    """An observation with no stated evidence must not invent one."""
    store.observe_correction("GNRO", "g(n)", course_code="COT3400")

    evidence = store.correction_evidence("GNRO", course_code="COT3400")

    assert all(item.detail for item in evidence)


# --- the real failures, as regression fixtures (section 22) -------------------


@pytest.mark.parametrize(
    ("heard", "corrected"),
    [("GNRO", "g(n)"), ("consents", "constants"), ("n zero", "n_0")],
)
def test_the_real_cot3400_corrections_round_trip(store, heard, corrected) -> None:
    store.observe_correction(
        heard, corrected, course_code="COT3400", source="user_file"
    )

    active = {r.heard_text: r.corrected_text for r in store.active_corrections(
        course_code="COT3400"
    )}

    assert active[heard] == corrected


def test_a_future_occurrence_retrieves_the_earlier_correction(store) -> None:
    """Section 5: a past correction is evidence for the next occurrence."""
    store.observe_correction(
        "GNRO", "g(n)", course_code="COT3400", source="user_file"
    )

    found = store.find_correction("GNRO", course_code="COT3400")

    assert found is not None
    assert found.corrected_text == "g(n)"
    assert found.status is CorrectionStatus.CONFIRMED


# --- the vault file feeds the store (section 9: clear ownership) -------------


def test_hand_written_rules_import_as_confirmed(tmp_path: Path) -> None:
    """The file is the human surface; the store is the structured memory."""
    from nova_school.corrections import sync_corrections_to_store

    classes = tmp_path / "Classes"
    (classes / "COT3400").mkdir(parents=True)
    (classes / "COT3400" / "STT-Corrections.md").write_text(
        "GNRO => g(n)\nconsents => constants\n", encoding="utf-8"
    )
    store = KnowledgeStore(tmp_path / "k.sqlite3")

    imported = sync_corrections_to_store("COT3400", store, classes_root=classes)

    assert imported == 2
    active = {r.heard_text: r.corrected_text for r in store.active_corrections(
        course_code="COT3400"
    )}
    assert active == {"GNRO": "g(n)", "consents": "constants"}


def test_the_file_edit_takes_effect_without_a_restart(tmp_path: Path) -> None:
    from nova_school.corrections import active_corrections_for

    classes = tmp_path / "Classes"
    (classes / "COT3400").mkdir(parents=True)
    rules = classes / "COT3400" / "STT-Corrections.md"
    rules.write_text("GNRO => g(n)\n", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "k.sqlite3")

    assert len(active_corrections_for("COT3400", store, classes_root=classes)) == 1

    rules.write_text("GNRO => g(n)\nn zero => n_0\n", encoding="utf-8")

    assert len(active_corrections_for("COT3400", store, classes_root=classes)) == 2


def test_an_inferred_candidate_is_not_applied_alongside_file_rules(
    tmp_path: Path,
) -> None:
    """Section 6, end to end: one AI guess does not become permanent knowledge."""
    from nova_school.corrections import active_corrections_for

    classes = tmp_path / "Classes"
    (classes / "COT3400").mkdir(parents=True)
    (classes / "COT3400" / "STT-Corrections.md").write_text(
        "GNRO => g(n)\n", encoding="utf-8"
    )
    store = KnowledgeStore(tmp_path / "k.sqlite3")
    store.observe_correction(
        "a low", "f(n)", course_code="COT3400", source="inferred"
    )

    active = dict(active_corrections_for("COT3400", store, classes_root=classes))

    assert "GNRO" in active
    assert "a low" not in active, "an unverified guess must not be applied"


def test_a_confirmed_inference_joins_the_applied_set(tmp_path: Path) -> None:
    """And once evidence arrives, it does apply -- that is the learning."""
    from nova_school.corrections import active_corrections_for

    classes = tmp_path / "Classes"
    (classes / "COT3400").mkdir(parents=True)
    (classes / "COT3400" / "STT-Corrections.md").write_text("", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "k.sqlite3")
    store.observe_correction(
        "a low", "f(n)", course_code="COT3400", source="inferred"
    )
    store.confirm_correction(
        "a low",
        course_code="COT3400",
        source="user",
        detail="Ahmed confirmed after class",
    )

    active = dict(active_corrections_for("COT3400", store, classes_root=classes))

    assert active["a low"] == "f(n)"
