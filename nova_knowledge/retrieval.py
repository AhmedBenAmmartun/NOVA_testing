from __future__ import annotations

from dataclasses import dataclass
import math
import re
from collections import Counter

from .models import EvidenceSource

_STOP = {
    "the","a","an","and","or","of","to","in","is","are","was","were","be","been","for","on","with","as","at","by","from","this","that","these","those","it","its","into","about","we","you","they","he","she","i"
}


def tokenize(value: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_+-]{2,}", value) if t.lower() not in _STOP]


@dataclass(slots=True)
class RetrievalHit:
    score: float
    chunk: dict

    @property
    def locator(self) -> str:
        if self.chunk.get("slide") is not None:
            return f"slide:{self.chunk['slide']}"
        if self.chunk.get("page") is not None:
            return f"page:{self.chunk['page']}"
        return str(self.chunk.get("section_id", "section"))

    def to_dict(self) -> dict:
        return {
            "score": round(float(self.score), 4),
            "course_code": self.chunk.get("course_code"),
            "source_name": self.chunk.get("source_name"),
            "material_id": self.chunk.get("material_id"),
            "section_id": self.chunk.get("section_id"),
            "title": self.chunk.get("title"),
            "locator": self.locator,
            "text": self.chunk.get("text", ""),
        }


def search_records(records: list[dict], query: str, *, course_code: str | None = None, limit: int = 8) -> list[RetrievalHit]:
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    filtered = [r for r in records if not course_code or str(r.get("course_code", "")).lower() == course_code.lower()]
    if not filtered:
        return []

    doc_tokens = [tokenize(f"{r.get('title','')} {r.get('text','')}") for r in filtered]
    df = Counter()
    for tokens in doc_tokens:
        df.update(set(tokens))
    n_docs = max(1, len(filtered))
    phrase = re.sub(r"\s+", " ", query.lower()).strip()
    hits: list[RetrievalHit] = []
    for record, tokens in zip(filtered, doc_tokens):
        if not tokens:
            continue
        tf = Counter(tokens)
        score = 0.0
        for token in q_tokens:
            if tf[token] <= 0:
                continue
            idf = math.log((n_docs + 1) / (df[token] + 1)) + 1.0
            score += (1.0 + math.log(tf[token])) * idf
        title = str(record.get("title", "")).lower()
        source = str(record.get("source_name", "")).lower()
        if any(token in tokenize(title) for token in q_tokens):
            score += 1.25
        if any(token in tokenize(source) for token in q_tokens):
            score += 0.75
        body = f"{title} {record.get('text','')}".lower()
        if len(phrase) >= 4 and phrase in body:
            score += 2.0
        if score > 0:
            hits.append(RetrievalHit(score=score, chunk=record))
    hits.sort(key=lambda h: (-h.score, str(h.chunk.get("source_name", "")), str(h.chunk.get("section_id", ""))))
    return hits[: max(1, int(limit))]


def hits_to_evidence(hits: list[RetrievalHit]) -> list[EvidenceSource]:
    output: list[EvidenceSource] = []
    for hit in hits:
        chunk = hit.chunk
        output.append(
            EvidenceSource(
                source_id=str(chunk.get("chunk_id") or f"{chunk.get('material_id','')}:{chunk.get('section_id','')}"),
                kind="course_material",
                name=str(chunk.get("source_name", "material")),
                sha256=str(chunk.get("sha256", "")),
                page=chunk.get("page"),
                slide=chunk.get("slide"),
                metadata={
                    "course_code": str(chunk.get("course_code", "")),
                    "section_id": str(chunk.get("section_id", "")),
                    "retrieval_score": f"{hit.score:.4f}",
                },
            )
        )
    return output
