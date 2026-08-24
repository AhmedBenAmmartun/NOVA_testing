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
    ) -> None:
        self.threshold = min(0.95, max(0.74, float(threshold)))
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

    @staticmethod
    def _preserve_case(source: str, target: str) -> str:
        if source.isupper():
            return target.upper()
        if source[:1].isupper():
            return target[:1].upper() + target[1:]
        return target

    def interpret(self, text: str) -> TerminologyInterpretation:
        raw = " ".join((text or "").split()).strip()
        if not raw or not self._single_terms:
            return TerminologyInterpretation(raw, raw)

        corrections: list[tuple[str, str]] = []

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

        interpreted = _WORD.sub(replace, raw)
        return TerminologyInterpretation(raw, interpreted, tuple(corrections))
