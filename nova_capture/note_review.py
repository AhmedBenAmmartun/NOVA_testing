"""Independent evidence check on generated notes, before Ahmed reads them.

The corrections layer repairs mishearings someone already knows about. The one
that actually cost a lecture was novel: Deepgram heard `g(n) >= 0` as "GNRO",
and generation turned that into a stated definition in `Lecture.md` --
attributed to a slide. No correction rule existed because nobody had seen it.

The evidence that would have caught it was already on disk. The professor was
teaching *from* three slide decks, and "GNRO" appears in none of them. A
definition whose central term has zero corroboration in the course materials,
in a lecture taught directly from those materials, is a fabrication signal.

Two deliberate constraints:

* **No model call.** Asking the same model whether it believes itself is not
  independent evidence; the course materials are. This module is deterministic
  and cheap enough to run on every generation.
* **Mark, never delete.** A real term the slides happen not to contain must
  survive with a flag. Deleting on a heuristic would lose real lecture content,
  and the reviewer's job is to make doubt visible, not to decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A token worth checking: long enough to be a technical term, not ordinary
#: prose. Short words are skipped because English is full of them and they carry
#: no signal either way.
_MIN_TERM_LENGTH = 4

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_'-]*")

#: Words that appear in a definition without being *about* anything. Flagging
#: these would make the reviewer noise, and noise gets ignored.
_STOPWORDS = frozenset(
    """
    about above after again against algorithm all also always among another any
    anything are because been before being below between both bring called can
    cannot case cases come common complete condition consider considered
    constant constants course define defined defines definition describe
    describes different does done during each either else enough every example
    examples explain explained explains first following from function functions
    general generally given gives grow growth happens have here however
    important input inputs into itself just know known large larger less like
    lower made make makes many mean means might more most much must name need
    never next node nodes note notes number numbers often only order other
    others output outputs over part particular per possible practice problem
    problems professor property proportional rate refer referred related
    result results right same says scenario several should show shows similar
    simple since situation slide slides small some something sometimes still
    such take takes term terms than that their them then there these they
    thing things think this those three through time times together took
    total two under understand upper used uses using usually value values
    very want way ways well were what when where which while will with
    within without would write writes
    """.split()
)


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    """One claim whose central term nothing corroborates."""

    term: str
    claim: str
    reason: str


def corroborating_terms(materials: str) -> frozenset[str]:
    """Every term the course materials actually contain, casefolded.

    This is the independent evidence. It is the professor's own slides and
    handouts -- not anything NOVA generated, and not the transcript, which is
    the very thing under suspicion.
    """
    text = (materials or "").casefold()
    words = {word for word in _WORD.findall(text) if len(word) >= _MIN_TERM_LENGTH}
    # Multi-word phrases matter too ("insertion sort"), so expose the raw text
    # for substring checks by the caller via this set plus adjacent pairs.
    tokens = _WORD.findall(text)
    pairs = {
        f"{first} {second}"
        for first, second in zip(tokens, tokens[1:])
        if len(first) >= 3 and len(second) >= 3
    }
    return frozenset(words | pairs)


def _suspect_terms(claim: str, corroborated: frozenset[str]) -> list[str]:
    """Distinctive words in a claim that the materials never mention."""
    found: list[str] = []
    for word in _WORD.findall(claim):
        if len(word) < _MIN_TERM_LENGTH:
            continue
        lowered = word.casefold()
        if lowered in _STOPWORDS or lowered in corroborated:
            continue
        # A word that is ordinary English in every respect except that the
        # slides did not happen to use it is weak evidence. Require the token
        # to look technical: an unusual capitalization pattern, a digit, or a
        # compound whose parts are themselves unfamiliar.
        if not _looks_technical(word, corroborated):
            continue
        found.append(word)
    return found


def _looks_technical(word: str, corroborated: frozenset[str]) -> bool:
    if any(character.isdigit() for character in word):
        return True
    if "-" in word or "_" in word:
        # "lower-order" and "all-pairs" are ordinary English wearing a hyphen;
        # "Floyd-Warshall" is not. The difference is whether the PARTS are
        # themselves familiar, so judge the compound by its pieces rather than
        # by the punctuation.
        parts = [part for part in re.split(r"[-_]", word) if part]
        return not all(
            part.casefold() in _STOPWORDS or part.casefold() in corroborated
            for part in parts
        )
    # ALLCAPS or InternalCaps -- GNRO, ZORBLAT, Floyd-Warshall.
    stripped = word.replace("-", "").replace("_", "")
    if stripped.isupper() and len(stripped) >= _MIN_TERM_LENGTH:
        return True
    return any(character.isupper() for character in word[1:])


def review_definitions(
    definitions: list[str] | tuple[str, ...],
    *,
    materials: str,
) -> tuple[ReviewFinding, ...]:
    """Flag definitions whose central term nothing in the materials supports.

    Returns empty when there are no materials: absence of evidence is not
    evidence of fabrication, and flagging everything for a course with no
    slides would make the reviewer noise.
    """
    if not (materials or "").strip():
        return ()

    corroborated = corroborating_terms(materials)
    findings: list[ReviewFinding] = []
    seen: set[str] = set()

    for claim in definitions:
        text = " ".join((claim or "").split())
        if not text:
            continue
        for term in _suspect_terms(text, corroborated):
            if term.casefold() in seen:
                continue
            seen.add(term.casefold())
            findings.append(
                ReviewFinding(
                    term=term,
                    claim=text,
                    reason=(
                        f"'{term}' appears nowhere in this course's materials. "
                        "This lecture is taught from those materials, so a "
                        "definition resting on an uncorroborated term may be "
                        "built on a transcription error. Verify against the "
                        "audio before relying on it."
                    ),
                )
            )

    return tuple(findings)
