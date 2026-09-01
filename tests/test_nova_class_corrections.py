"""Ahmed's ground-truth corrections must beat the speech recognizer.

Deepgram cannot produce subscripts, function application, or Greek letters from
speech. In the real COT3400 lecture on 2026-08-31 it heard "GNRO and larger or
equal to N zero" for `0 <= f(n) <= cg(n) for all n >= n_0`, and the post-class
model then promoted that mis-hearing into a *definition* -- "The condition GNRO
>= N is a property stated in the lecture slide". A wrong transcript does not
stay a transcript problem; it becomes fabricated course knowledge.

The existing TerminologyInterpreter could not express any of these repairs: it
matched single tokens only, so a two-word phrase like "n zero" was structurally
impossible to correct, and its confusion table was two hardcoded entries in
source. These tests cover the course-scoped, user-authored correction file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nova_capture.terminology import TerminologyInterpreter
from nova_school.corrections import load_course_corrections, parse_corrections


def test_a_multi_word_phrase_can_be_corrected(tmp_path: Path) -> None:
    """The single-token limit was the blocker for every real notation repair."""
    interpreter = TerminologyInterpreter([], corrections=[("n zero", "n_0")])

    result = interpreter.interpret("larger or equal to n zero")

    assert result.interpreted == "larger or equal to n_0"
    assert result.corrections == (("n zero", "n_0"),)


def test_the_longest_matching_rule_wins() -> None:
    """"important city presentation" must not be half-eaten by "city presentation"."""
    interpreter = TerminologyInterpreter(
        [],
        corrections=[
            ("city presentation", "in-class presentation"),
            ("important city presentation", "in-class presentation"),
        ],
    )

    result = interpreter.interpret("she announced an important city presentation")

    assert result.interpreted == "she announced an in-class presentation"


def test_corrections_are_case_insensitive_but_do_not_shout() -> None:
    interpreter = TerminologyInterpreter([], corrections=[("gnro", "g(n)")])

    assert interpreter.interpret("GNRO is non negative").interpreted == (
        "g(n) is non negative"
    )


def test_a_correction_only_replaces_whole_words() -> None:
    """"a low" must not fire inside "allow" or "below"."""
    interpreter = TerminologyInterpreter([], corrections=[("a low", "f(n)")])

    result = interpreter.interpret("we allow a low bound below zero")

    assert result.interpreted == "we allow f(n) bound below zero"


def test_corrections_run_before_fuzzy_term_repair() -> None:
    """User ground truth is authoritative; fuzzy matching must not undo it."""
    interpreter = TerminologyInterpreter(
        ["asymptotic", "algorithm"],
        corrections=[("consents", "constants")],
    )

    result = interpreter.interpret("the consents c and n zero")

    assert "constants" in result.interpreted
    assert "consents" not in result.interpreted


def test_existing_single_token_repair_still_works() -> None:
    """Regression: the CEN4065 behavior that shipped must not be lost."""
    interpreter = TerminologyInterpreter(["aggregation", "composition"])

    assert interpreter.interpret("aggression").interpreted == "aggregation"


def test_no_corrections_means_unchanged_text() -> None:
    interpreter = TerminologyInterpreter([], corrections=[])

    result = interpreter.interpret("nothing here should move")

    assert not result.changed


# --- the course-scoped rules file -------------------------------------------


def test_the_rules_file_format_is_simple_enough_to_hand_edit() -> None:
    text = """
# COT3400 — STT Corrections

Prose that is not a rule is ignored.

## Notation

n zero => n_0
GNRO => g(n)

# commented out => never applied

## Announcements

important city presentation => in-class presentation
"""

    rules = parse_corrections(text)

    assert ("n zero", "n_0") in rules
    assert ("GNRO", "g(n)") in rules
    assert ("important city presentation", "in-class presentation") in rules
    assert not any(heard == "commented out" for heard, _ in rules)


def test_a_malformed_line_is_skipped_not_fatal() -> None:
    """A hand-edited file must never be able to break class processing."""
    rules = parse_corrections("good => fine\nthis line has no arrow\n=> \nx =>\n")

    assert rules == (("good", "fine"),)


def test_rules_are_ordered_longest_first_so_application_is_deterministic() -> None:
    rules = parse_corrections("a b => X\na b c d => Y\na b c => Z\n")

    assert [heard for heard, _ in rules] == ["a b c d", "a b c", "a b"]


def test_a_course_without_a_rules_file_loads_nothing(tmp_path: Path) -> None:
    assert load_course_corrections("COT3400", classes_root=tmp_path) == ()


def test_the_rules_file_is_read_from_the_course_folder(tmp_path: Path) -> None:
    course = tmp_path / "COT3400"
    course.mkdir()
    (course / "STT-Corrections.md").write_text("n zero => n_0\n", encoding="utf-8")

    assert load_course_corrections("COT3400", classes_root=tmp_path) == (
        ("n zero", "n_0"),
    )


def test_the_rules_file_never_becomes_grounding_material(tmp_path: Path) -> None:
    """It lives beside Materials/, never inside it, or it feeds itself back in."""
    from nova_school.corrections import course_corrections_path

    path = course_corrections_path("COT3400", classes_root=tmp_path)

    assert path.name == "STT-Corrections.md"
    assert "Materials" not in path.parts


@pytest.mark.parametrize("bad", ["", "   ", "\n\n"])
def test_an_empty_rules_file_is_harmless(bad: str) -> None:
    assert parse_corrections(bad) == ()


# --- end to end: the real COT3400 failure -----------------------------------


def test_corrections_reach_the_derived_evidence_but_never_the_raw_journal(
    tmp_path: Path,
) -> None:
    """The exact 2026-08-31 failure, end to end.

    Deepgram produced "GNRO and larger or equal to N zero". Uncorrected, the
    post-class model turned that into a definition in Lecture.md. Corrections
    must reach the evidence that feeds generation, while `transcript.jsonl`
    stays exactly as recorded.
    """
    from nova_capture.evidence import EvidenceItem, Provenance, SessionEvidence
    from nova_capture.postprocess import apply_course_corrections

    evidence = SessionEvidence(
        session_id="s",
        course="COT3400",
        title="Class Session",
        items=[
            EvidenceItem(
                evidence_id="e1",
                kind="transcript",
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=573.2,
                text="A better able to see that GNRO and larger or equal to N zero",
            )
        ],
    )

    changed = apply_course_corrections(
        evidence, (("GNRO", "g(n)"), ("N zero", "n_0"))
    )

    assert changed == 1
    item = evidence.items[0]
    assert "g(n)" in item.text and "n_0" in item.text
    assert "GNRO" not in item.text
    # The original stays recoverable for anyone auditing the note.
    assert "GNRO" in item.attributes["raw_text"]
    assert ["GNRO", "g(n)"] in item.attributes["corrections"]


def test_a_course_with_no_rules_leaves_evidence_untouched() -> None:
    from nova_capture.evidence import EvidenceItem, Provenance, SessionEvidence
    from nova_capture.postprocess import apply_course_corrections

    evidence = SessionEvidence(
        session_id="s",
        course="COT3400",
        title="Class Session",
        items=[
            EvidenceItem(
                evidence_id="e1",
                kind="transcript",
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=1.0,
                text="untouched",
            )
        ],
    )

    assert apply_course_corrections(evidence, ()) == 0
    assert evidence.items[0].text == "untouched"
    assert "raw_text" not in evidence.items[0].attributes


def test_prose_that_merely_mentions_the_arrow_is_not_a_rule() -> None:
    """Caught on real data: the file's own instructions parsed as a rule.

    `STT-Corrections.md` explains its own format in prose -- "One rule per
    line, `heard => actual`" -- and that sentence contains the separator. It
    was being imported as a correction whose heard-side was a paragraph.

    A real rule is a short phrase. Prose is not.
    """
    text = (
        "Left side is what Deepgram heard, right side is what was actually\n"
        "said. One rule per line, `heard => actual`.\n"
        "\n"
        "GNRO => g(n)\n"
    )

    rules = parse_corrections(text)

    assert rules == (("GNRO", "g(n)"),)


def test_a_rule_side_containing_a_backtick_is_rejected() -> None:
    assert parse_corrections("`heard` => actual") == ()


def test_a_sentence_is_rejected_as_a_heard_phrase() -> None:
    assert parse_corrections("This is a sentence. And another => nope") == ()


def test_an_absurdly_long_heard_side_is_rejected() -> None:
    assert parse_corrections(("word " * 40) + "=> nope") == ()


def test_a_legitimately_long_phrase_still_works() -> None:
    """The guard must not reject real multi-word corrections."""
    rules = parse_corrections("important city presentation => in-class presentation")

    assert rules == (("important city presentation", "in-class presentation"),)
