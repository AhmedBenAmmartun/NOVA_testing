from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal
import time

MaterialKind = Literal["slides", "pdf", "document", "text", "unknown"]
ImportDisposition = Literal["auto_import", "pending_review", "reject"]


@dataclass(slots=True, frozen=True)
class CourseDescriptor:
    code: str
    name: str = ""
    aliases: tuple[str, ...] = ()

    def tokens(self) -> tuple[str, ...]:
        values = [self.code, self.name, *self.aliases]
        return tuple(v.strip() for v in values if v and v.strip())


@dataclass(slots=True)
class ExtractedSection:
    section_id: str
    title: str
    text: str
    page: int | None = None
    slide: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ExtractedDocument:
    kind: MaterialKind
    title: str
    sections: list[ExtractedSection] = field(default_factory=list)
    extractor: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def searchable_text(self) -> str:
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        for section in self.sections:
            if section.title:
                parts.append(section.title)
            if section.text:
                parts.append(section.text)
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
            "extractor": self.extractor,
            "warnings": list(self.warnings),
        }


@dataclass(slots=True)
class CourseClassification:
    course_code: str | None
    confidence: float
    disposition: ImportDisposition
    reasons: list[str] = field(default_factory=list)
    alternatives: list[tuple[str, float]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "course_code": self.course_code,
            "confidence": round(float(self.confidence), 4),
            "disposition": self.disposition,
            "reasons": list(self.reasons),
            "alternatives": [[code, round(float(score), 4)] for code, score in self.alternatives],
        }


@dataclass(slots=True)
class MaterialRecord:
    material_id: str
    sha256: str
    source_name: str
    imported_name: str
    course_code: str | None
    confidence: float
    disposition: ImportDisposition
    material_kind: MaterialKind
    document_title: str
    imported_at: float = field(default_factory=time.time)
    extractor: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["schema_version"] = 1
        return payload


@dataclass(slots=True)
class EvidenceSource:
    source_id: str
    kind: str
    name: str
    sha256: str = ""
    page: int | None = None
    slide: int | None = None
    timestamp_seconds: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class EvidenceManifest:
    session_id: str
    course_code: str
    created_at: float = field(default_factory=time.time)
    transcript_name: str = ""
    audio_name: str = ""
    marker_name: str = ""
    materials: list[EvidenceSource] = field(default_factory=list)
    prior_notes: list[EvidenceSource] = field(default_factory=list)
    generated_outputs: list[EvidenceSource] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "course_code": self.course_code,
            "created_at": self.created_at,
            "transcript_name": self.transcript_name,
            "audio_name": self.audio_name,
            "marker_name": self.marker_name,
            "materials": [x.to_dict() for x in self.materials],
            "prior_notes": [x.to_dict() for x in self.prior_notes],
            "generated_outputs": [x.to_dict() for x in self.generated_outputs],
        }
