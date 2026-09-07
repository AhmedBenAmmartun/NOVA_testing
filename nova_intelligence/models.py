from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    UNKNOWN = "UNKNOWN"
    STALE = "STALE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    source_kind: str
    source: str
    observed_at: str
    digest: str = ""
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "source_kind": self.source_kind,
            "source": self.source,
            "observed_at": self.observed_at,
            "digest": self.digest,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Fact:
    key: str
    value: Any
    status: FactStatus
    provenance: tuple[ProvenanceRef, ...] = field(default_factory=tuple)
    freshness: str = "unknown"
    confidence: float = 1.0
    note: str = ""

    def with_status(self, status: FactStatus, *, freshness: str | None = None) -> "Fact":
        return replace(
            self,
            status=FactStatus(status),
            freshness=self.freshness if freshness is None else str(freshness),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "status": self.status.value,
            "freshness": self.freshness,
            "confidence": round(max(0.0, min(1.0, float(self.confidence))), 4),
            "note": self.note,
            "provenance": [item.as_dict() for item in self.provenance],
        }


@dataclass(frozen=True, slots=True)
class ProjectState:
    schema_version: int
    project_id: str
    generated_at: str
    identity: Mapping[str, Fact]
    repository: Mapping[str, Fact]
    active_work: Mapping[str, Fact]
    systems: Mapping[str, Fact]
    issues: tuple[dict[str, Any], ...]
    decisions: tuple[dict[str, Any], ...]
    tests: Mapping[str, Fact]
    failed_approaches: tuple[dict[str, Any], ...]
    continuity: Mapping[str, Fact]
    conflicts: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "generated_at": self.generated_at,
            "identity": {key: fact.as_dict() for key, fact in self.identity.items()},
            "repository": {key: fact.as_dict() for key, fact in self.repository.items()},
            "active_work": {key: fact.as_dict() for key, fact in self.active_work.items()},
            "systems": {key: fact.as_dict() for key, fact in self.systems.items()},
            "issues": list(self.issues),
            "decisions": list(self.decisions),
            "tests": {key: fact.as_dict() for key, fact in self.tests.items()},
            "failed_approaches": list(self.failed_approaches),
            "continuity": {key: fact.as_dict() for key, fact in self.continuity.items()},
            "conflicts": list(self.conflicts),
        }

    def fact_count(self) -> int:
        groups = (
            self.identity,
            self.repository,
            self.active_work,
            self.systems,
            self.tests,
            self.continuity,
        )
        return sum(len(group) for group in groups)


@dataclass(frozen=True, slots=True)
class ContextPacket:
    generated_at: str
    base: Mapping[str, Any]
    project: Mapping[str, Any] | None
    project_status: str
    influence_allowed: bool
    reason: str
    provenance_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "base": dict(self.base),
            "project": None if self.project is None else dict(self.project),
            "project_status": self.project_status,
            "influence_allowed": self.influence_allowed,
            "reason": self.reason,
            "provenance_count": self.provenance_count,
        }
