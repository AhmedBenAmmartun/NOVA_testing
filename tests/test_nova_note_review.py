"""Catch a mishearing before it becomes a definition in Ahmed's notes.

The corrections layer only fixes mishearings someone already knows about. The
one that actually cost a lecture was novel: Deepgram heard `g(n) >= 0` as
"GNRO", and the post-class model wrote

    "The condition GNRO >= N is a property stated in the lecture slide."

into `Lecture.md` -- as a *definition*, attributed to a slide. Nobody had a
correction rule for "GNRO" because nobody had seen it before.

The independent evidence that would have caught it is sitting right there: the
professor was teaching *from* three slide decks, and "GNRO" appears in none of
them. A definition whose central term has zero corroboration in the course
materials is a fabrication signal.

This is deliberately NOT another language-model pass. Asking the same model
whether it believes itself is not independent evidence -- the course materials
are. So the check is deterministic and cheap, and it marks uncertainty rather
than deleting content: a real term the materials happen not to contain should
be flagged for review, never silently dropped.
"""

from __future__ import annotations

import pytest

from nova_capture.note_review import (
    ReviewFinding,
    corroborating_terms,
    review_definitions,
)

# Text standing in for the real COT 3400 asymptotic-analysis deck.
MATERIALS = """
Loop invariants help us understand why an algorithm is correct.
O(g(n)) = { f(n) : there exist positive constants c and n0 such that
0 <= f(n) <= c g(n) for all n >= n0 }.
Insertion sort takes c1 * n^2 to sort n items. Merge sort takes c2 n lg n.
Asymptotic upper bound. Big O notation. Worst case running time.
"""


def test_a_term_present_in_the_materials_is_corroborated() -> None:
    assert "insertion sort" in corroborating_terms(MATERIALS)


def test_a_misheard_token_is_not_corroborated() -> None:
    """The whole point: GNRO is in no slide, because nobody ever wrote it."""
    assert "gnro" not in corroborating_terms(MATERIALS)


# --- the review ---------------------------------------------------------------


def test_the_real_fabricated_definition_is_flagged() -> None:
    """Verbatim from the 2026-08-31 Lecture.md."""
    definitions = [
        "The condition GNRO >= N is a property stated in the lecture slide "
        "for algorithm analysis."
    ]

    findings = review_definitions(definitions, materials=MATERIALS)

    assert len(findings) == 1
    assert "GNRO" in findings[0].term


def test_a_genuine_definition_is_not_flagged() -> None:
    """The guard is worthless if it cries wolf on real content."""
    definitions = [
        "Big O notation provides an asymptotic upper bound on the running "
        "time of an algorithm, ignoring constants and lower-order terms."
    ]

    assert review_definitions(definitions, materials=MATERIALS) == ()


def test_a_definition_about_insertion_sort_survives() -> None:
    definitions = [
        "Insertion sort takes time roughly proportional to n^2 in the worst case."
    ]

    assert review_definitions(definitions, materials=MATERIALS) == ()


def test_ordinary_english_is_never_treated_as_a_suspect_term() -> None:
    """Common words are not evidence of fabrication."""
    definitions = [
        "The professor explained that we usually consider the situation where "
        "the input is already arranged before anything happens."
    ]

    assert review_definitions(definitions, materials=MATERIALS) == ()


def test_several_fabrications_are_each_reported() -> None:
    definitions = [
        "The condition GNRO is a property of the slide.",
        "A ZORBLAT bound describes the growth rate.",
    ]

    findings = review_definitions(definitions, materials=MATERIALS)

    assert {finding.term for finding in findings} == {"GNRO", "ZORBLAT"}


def test_a_finding_says_what_is_wrong_and_where() -> None:
    """A reviewer that only says "suspicious" cannot be acted on."""
    definitions = ["The condition GNRO >= N is a property stated in the slide."]

    finding = review_definitions(definitions, materials=MATERIALS)[0]

    assert finding.term == "GNRO"
    assert "GNRO" in finding.claim
    assert finding.reason


def test_findings_mark_uncertainty_rather_than_deleting_content() -> None:
    """A real term the slides happen not to contain must survive, flagged.

    Deleting content on a heuristic would lose real lecture material. The
    reviewer's job is to make doubt visible, not to decide.
    """
    definitions = ["The Floyd-Warshall algorithm computes all-pairs shortest paths."]

    findings = review_definitions(definitions, materials=MATERIALS)

    assert findings
    assert all(isinstance(item, ReviewFinding) for item in findings)
    assert all(item.claim for item in findings), "the claim text is preserved"


def test_no_materials_means_no_verdict(caplog) -> None:
    """Without evidence there is nothing to check against.

    Flagging everything when the course has no slides would make the reviewer
    noise. Absence of evidence is not evidence of fabrication.
    """
    definitions = ["The condition GNRO >= N is a property."]

    assert review_definitions(definitions, materials="") == ()


def test_an_empty_note_reviews_clean() -> None:
    assert review_definitions([], materials=MATERIALS) == ()


@pytest.mark.parametrize("noise", ["", "   ", "\n"])
def test_blank_definitions_are_ignored(noise: str) -> None:
    assert review_definitions([noise], materials=MATERIALS) == ()


def test_the_reviewer_does_not_call_a_model() -> None:
    """Section 2: independent evidence, not repeated generation.

    Asking the same model whether it believes itself is not verification. This
    module must stay deterministic -- and cheap enough to run every time.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "nova_capture" / "note_review.py"
    ).read_text(encoding="utf-8")

    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            assert "provider" not in name
            assert "intelligence" not in name
            assert not name.startswith("openai")


# --- NOVA's own output is not evidence for NOVA's own output ----------------


def test_prior_generated_notes_are_excluded_from_verification_evidence(
    tmp_path, monkeypatch
) -> None:
    """Found on real data: the fabrication was corroborating itself.

    `CourseContextLibrary.build_context` mixes course materials with
    `prior_note` sources from the Sessions folder -- which are NOVA's OWN
    generated notes. On the real COT3400 course, "GNRO" appeared in
    `Lecture.md`, `Study.md` and `Questions.md`, so checking a definition
    against that pool found "corroboration" and flagged nothing.

    That is circular. For grounding a live answer, prior notes are useful
    continuity. For VERIFYING generated content they are disqualified, because
    the thing under suspicion cannot vouch for itself. This is the same
    boundary `HUMAN_PROVENANCE` already draws in `nova_capture/evidence.py`.
    """
    from nova_school.context import CourseContextLibrary
    import nova_school.context as context_module

    course = tmp_path / "COT3400"
    (course / "Materials" / "Slides").mkdir(parents=True)
    (course / "Materials" / "Slides" / "deck.md").write_text(
        "Big O notation and asymptotic upper bounds.", encoding="utf-8"
    )
    sessions = course / "Sessions" / "2026-08-31"
    sessions.mkdir(parents=True)
    (sessions / "Lecture.md").write_text(
        "The condition GNRO >= N is a property stated in the lecture slide.",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        context_module, "course_materials_root", lambda code: course / "Materials"
    )
    monkeypatch.setattr(
        context_module, "course_sessions_root", lambda code: course / "Sessions"
    )

    library = CourseContextLibrary("COT3400")
    verification, kinds = library.verification_material()

    assert "Big O" in verification, "real course material must be present"
    assert "GNRO" not in verification, "NOVA's own note must not be evidence"
    assert "prior_note" not in kinds
