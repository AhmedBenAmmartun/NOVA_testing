from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


_WORD = re.compile(r"\b[A-Za-z][A-Za-z'-]{3,}\b")

# Conservative confusions observed in actual classroom STT or common enough to
# justify a direct correction only when the target is already a known course term.
_KNOWN_STT_CONFUSIONS = {
    "aggression": "aggregation",
    "compulsion": "composition",
}


@dataclass(frozen=True, slots=True)
class TerminologyInterpretation:
    raw: str
    interpreted: str
    corrections: tuple[tuple[str, str], ...] = ()

    @property
    def changed(self) -> bool:
        return self.raw != self.interpreted


class TerminologyInterpreter:
    """Repair only high-confidence STT near-misses using trusted course terms."""

    def __init__(
        self,
        terms: list[str] | tuple[str, ...],
        *,
        threshold: float = 0.78,
        corrections: list[tuple[str, str]] | tuple[tuple[str, str], ...] = (),
    ) -> None:
        self.threshold = min(0.95, max(0.74, float(threshold)))
        # Ground truth from the person who was in the room. Unlike the fuzzy
        # repair below, these are exact and may span several words, which is
        # the only way to reach spoken mathematics ("n zero" -> "n_0").
        self._corrections = tuple(
            (" ".join(str(heard).split()), " ".join(str(actual).split()))
            for heard, actual in corrections
            if str(heard).strip() and str(actual).strip()
        )
        self._correction_pattern = self._build_correction_pattern()
        values: list[str] = []
        seen: set[str] = set()
        for value in terms:
            cleaned = " ".join(str(value or "").split()).strip()
            # Automatic token repair is intentionally limited to single terms.
            if not cleaned or " " in cleaned or len(cleaned) < 6:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            values.append(cleaned)
        self._single_terms = tuple(values)
        self._term_by_key = {value.casefold(): value for value in values}

    def _build_correction_pattern(self) -> re.Pattern[str] | None:
        """One alternation, longest phrase first, so the longest rule wins.

        Sorting by length here is what stops "city presentation" from eating
        half of "important city presentation" -- Python's ``|`` is first-match,
        not longest-match, so the ordering has to be built in.
        """
        if not self._corrections:
            return None
        ordered = sorted(self._corrections, key=lambda rule: -len(rule[0]))
        # \b would not anchor a rule ending in punctuation, so require a
        # non-word neighbour explicitly. This keeps "a low" out of "allow".
        alternation = "|".join(re.escape(heard) for heard, _ in ordered)
        return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)

    def _apply_corrections(
        self,
        text: str,
        corrections: list[tuple[str, str]],
    ) -> str:
        if self._correction_pattern is None:
            return text
        replacements = {heard.casefold(): actual for heard, actual in self._corrections}

        def replace(match: re.Match[str]) -> str:
            found = match.group(0)
            actual = replacements.get(" ".join(found.split()).casefold())
            if actual is None or actual == found:
                return found
            corrections.append((found, actual))
            return actual

        return self._correction_pattern.sub(replace, text)

    @staticmethod
    def _preserve_case(source: str, target: str) -> str:
        if source.isupper():
            return target.upper()
        if source[:1].isupper():
            return target[:1].upper() + target[1:]
        return target

    def interpret(self, text: str) -> TerminologyInterpretation:
        raw = " ".join((text or "").split()).strip()
        if not raw:
            return TerminologyInterpretation(raw, raw)

        corrections: list[tuple[str, str]] = []

        # Ahmed's rules are authoritative, so they run first and the fuzzy pass
        # below then works on already-corrected text. Doing it the other way
        # round would let a near-miss guess overwrite a known-correct answer.
        working = self._apply_corrections(raw, corrections)

        if not self._single_terms:
            return TerminologyInterpretation(raw, working, tuple(corrections))

        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            lowered = token.casefold()

            if lowered in self._term_by_key:
                return token

            direct = _KNOWN_STT_CONFUSIONS.get(lowered)
            if direct and direct in self._term_by_key:
                replacement = self._preserve_case(token, self._term_by_key[direct])
                corrections.append((token, replacement))
                return replacement

            best_term = None
            best_score = 0.0
            for candidate in self._single_terms:
                candidate_lower = candidate.casefold()
                if abs(len(candidate_lower) - len(lowered)) > 3:
                    continue
                score = SequenceMatcher(None, lowered, candidate_lower).ratio()
                if score > best_score:
                    best_score = score
                    best_term = candidate

            if best_term is None or best_score < self.threshold:
                return token
            if len(lowered) < 7 and best_score < 0.86:
                return token

            replacement = self._preserve_case(token, best_term)
            corrections.append((token, replacement))
            return replacement

        interpreted = _WORD.sub(replace, working)
        return TerminologyInterpretation(raw, interpreted, tuple(corrections))
