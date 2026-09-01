"""Course-scoped, user-authored corrections for what the recognizer misheard.

Speech recognition cannot produce `n_0`, `f(n)`, `cg(n)` or Greek letters from
spoken mathematics, and the failure does not stay contained: on 2026-08-31 a
real COT3400 lecture was transcribed as "GNRO and larger or equal to N zero",
and the post-class model turned that into a stated definition. Once a
mis-hearing reaches generation it becomes fabricated course knowledge.

Only the person who was in the room knows what was actually said, so these
rules are ground truth supplied by Ahmed, not something NOVA may infer. They
are applied deterministically and before any fuzzy repair.

The file lives at ``<classes root>/<COURSE>/STT-Corrections.md`` -- beside
``Materials/`` and deliberately never inside it, so the corrections can never be
picked up as course material and fed back in as lecture content.
"""

from __future__ import annotations

import re
from pathlib import Path

from .paths import class_knowledge_root

#: `heard => actual`, one per line. Chosen because it survives hand-editing in
#: Obsidian and reads correctly as prose in a rendered Markdown note.
_RULE = re.compile(r"^(?P<heard>[^=#][^=]*?)\s*=>\s*(?P<actual>.+?)\s*$")

CORRECTIONS_FILENAME = "STT-Corrections.md"

#: A correction is a short spoken phrase, not a paragraph. The file explains its
#: own format in prose -- "One rule per line, `heard => actual`" -- and that
#: sentence contains the separator, so it parsed as a rule whose heard-side was
#: a paragraph. Caught by running against Ahmed's real file.
_MAX_PHRASE_WORDS = 12
_MAX_PHRASE_CHARS = 80


def _looks_like_a_phrase(value: str) -> bool:
    """Reject prose that merely happens to contain the separator."""
    if len(value) > _MAX_PHRASE_CHARS:
        return False
    if len(value.split()) > _MAX_PHRASE_WORDS:
        return False
    if "`" in value:
        return False
    # A sentence boundary means this is prose, not a phrase someone said.
    return ". " not in value


def course_corrections_path(
    course_code: str,
    *,
    classes_root: str | Path | None = None,
) -> Path:
    root = Path(classes_root) if classes_root is not None else class_knowledge_root()
    return root / course_code.strip() / CORRECTIONS_FILENAME


def parse_corrections(text: str) -> tuple[tuple[str, str], ...]:
    """Read `heard => actual` rules, longest phrase first.

    Ordering is part of the contract, not an implementation detail: applying
    "city presentation" before "important city presentation" would leave a
    half-rewritten phrase behind. Longest-first makes the result deterministic
    regardless of the order Ahmed happened to type the rules in.

    Anything that is not a well-formed rule -- prose, headings, comments, a
    half-typed line -- is skipped. A hand-edited file must never be able to
    break class processing.
    """
    rules: list[tuple[str, str]] = []
    seen: set[str] = set()

    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _RULE.match(stripped)
        if match is None:
            continue
        heard = " ".join(match.group("heard").split())
        actual = " ".join(match.group("actual").split())
        if not heard or not actual:
            continue
        if not _looks_like_a_phrase(heard) or not _looks_like_a_phrase(actual):
            continue
        key = heard.casefold()
        if key in seen:
            continue
        seen.add(key)
        rules.append((heard, actual))

    rules.sort(key=lambda rule: (-len(rule[0]), rule[0].casefold()))
    return tuple(rules)


def load_course_corrections(
    course_code: str,
    *,
    classes_root: str | Path | None = None,
) -> tuple[tuple[str, str], ...]:
    """Load a course's correction rules, or nothing if there are none."""
    path = course_corrections_path(course_code, classes_root=classes_root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError, OSError):
        return ()
    return parse_corrections(text)


def sync_corrections_to_store(
    course_code: str,
    store,
    *,
    classes_root: str | Path | None = None,
) -> int:
    """Import Ahmed's hand-written rules into the structured store.

    The file stays the human-editable surface -- he reads and edits it in
    Obsidian, and it must not become opaque database rows. The store adds what
    a flat file cannot express: confidence, status, scope, evidence, and
    counts.

    These rules arrive as ``user_file``, which is a trusted source, so they are
    confirmed on arrival. There is nothing for NOVA to verify about a rule the
    person who was in the room wrote himself. Corrections NOVA *infers* enter
    the same store as candidates and must earn confirmation separately.

    Returns the number of rules imported, for the run log.
    """
    rules = load_course_corrections(course_code, classes_root=classes_root)
    for heard, actual in rules:
        store.observe_correction(
            heard,
            actual,
            course_code=course_code,
            source="user_file",
            detail=f"Authored by Ahmed in {CORRECTIONS_FILENAME} for {course_code}.",
        )
    return len(rules)


def active_corrections_for(
    course_code: str,
    store,
    *,
    classes_root: str | Path | None = None,
) -> tuple[tuple[str, str], ...]:
    """The rules that may actually be applied to this course's derived text.

    File rules are synced first so a fresh edit takes effect immediately, then
    the store decides what is applicable. A candidate NOVA inferred but has not
    verified is deliberately absent: it is retained and inspectable, but it does
    not get to change what NOVA believes.
    """
    sync_corrections_to_store(course_code, store, classes_root=classes_root)
    return tuple(
        (record.heard_text, record.corrected_text)
        for record in store.active_corrections(course_code=course_code)
    )
