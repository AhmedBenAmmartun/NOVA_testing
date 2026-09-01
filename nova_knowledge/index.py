from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import os
import re
import tempfile

from .extractors import extract_document
from .fingerprint import sha256_file, short_material_id


@dataclass(slots=True)
class IndexedChunk:
    chunk_id: str
    material_id: str
    sha256: str
    course_code: str
    source_name: str
    material_kind: str
    section_id: str
    title: str
    text: str
    page: int | None = None
    slide: int | None = None
    extractor: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


class CourseKnowledgeIndex:
    """Local-only, rebuildable JSONL index. Stores no required full source paths."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        output: list[dict] = []
        for raw in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                output.append(value)
        return output

    def material_hashes(self) -> set[str]:
        return {str(r.get("sha256", "")) for r in self.records() if r.get("sha256")}

    def rebuild(self, chunks: list[IndexedChunk]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                for chunk in chunks:
                    handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return self.path


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def chunks_from_file(path: str | Path, *, course_code: str) -> list[IndexedChunk]:
    source = Path(path).expanduser().resolve()
    digest = sha256_file(source)
    material_id = short_material_id(digest)
    document = extract_document(source)
    output: list[IndexedChunk] = []
    for section in document.sections:
        text = _clean_text(section.text)
        title = _clean_text(section.title)
        if not text and not title:
            continue
        output.append(
            IndexedChunk(
                chunk_id=f"{material_id}:{section.section_id}",
                material_id=material_id,
                sha256=digest,
                course_code=course_code,
                source_name=source.name,
                material_kind=document.kind,
                section_id=section.section_id,
                title=title,
                text=text,
                page=section.page,
                slide=section.slide,
                extractor=document.extractor,
            )
        )
    return output


def merge_unique(existing: list[IndexedChunk], additions: list[IndexedChunk]) -> list[IndexedChunk]:
    by_id: dict[str, IndexedChunk] = {chunk.chunk_id: chunk for chunk in existing}
    for chunk in additions:
        by_id.setdefault(chunk.chunk_id, chunk)
    return sorted(by_id.values(), key=lambda c: (c.course_code, c.source_name.lower(), c.section_id))
