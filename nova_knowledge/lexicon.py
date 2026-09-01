from __future__ import annotations

from collections import Counter
import re

_STOP = {
    "about","after","again","also","because","before","being","between","could","does","each","from","have","into","more","most","other","over","same","some","such","than","that","their","there","these","they","this","those","through","under","using","very","what","when","where","which","while","with","would","your"
}


def build_course_lexicon(records: list[dict], *, course_code: str | None = None, limit: int = 200) -> list[dict]:
    selected = [r for r in records if not course_code or str(r.get("course_code", "")).lower() == course_code.lower()]
    singles: Counter[str] = Counter()
    acronyms: Counter[str] = Counter()
    phrases: Counter[str] = Counter()

    for record in selected:
        text = f"{record.get('title','')} {record.get('text','')}"
        for token in re.findall(r"\b[A-Z][A-Z0-9_-]{1,9}\b", text):
            acronyms[token] += 1
        words = [w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z0-9_+-]{3,}\b", text)]
        words = [w for w in words if w not in _STOP]
        singles.update(words)
        for n in (2, 3):
            for i in range(len(words) - n + 1):
                phrase = " ".join(words[i:i+n])
                if all(part not in _STOP for part in words[i:i+n]):
                    phrases[phrase] += 1

    candidates: dict[str, float] = {}
    for term, count in acronyms.items():
        candidates[term] = max(candidates.get(term, 0), count * 4.0)
    for term, count in singles.items():
        if count >= 2:
            candidates[term] = max(candidates.get(term, 0), count * 1.0)
    for term, count in phrases.items():
        if count >= 2:
            candidates[term] = max(candidates.get(term, 0), count * (1.4 if term.count(" ") == 1 else 1.8))

    ranked = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))[: max(1, int(limit))]
    return [{"term": term, "score": round(score, 3)} for term, score in ranked]
