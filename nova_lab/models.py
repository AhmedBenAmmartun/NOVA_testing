"""Lifecycle data models for NOVA Lab."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FeatureState(str, Enum):
    LAB = "lab"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS: dict[FeatureState, frozenset[FeatureState]] = {
    FeatureState.LAB: frozenset({FeatureState.CANDIDATE}),
    FeatureState.CANDIDATE: frozenset({FeatureState.LAB, FeatureState.ACTIVE}),
    FeatureState.ACTIVE: frozenset({FeatureState.RETIRED}),
    FeatureState.RETIRED: frozenset({FeatureState.LAB}),
}


class InvalidTransitionError(ValueError):
    """Raised when a feature tries to skip the lifecycle."""


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    feature_id: str
    capability_id: str
    name: str
    status: FeatureState = FeatureState.LAB
    branch: str = ""
    worktree: str = ""
    base_ref: str = ""
    test_profile: str = "official"
    version: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    promoted_at: str | None = None
    retired_at: str | None = None
    rollback_ref: str = ""
    #: The exact commit SHA that passed the required trusted gates when this
    #: feature entered CANDIDATE. Frozen at that moment -- a later change to
    #: the Lab worktree must never be mistaken for what was actually gated.
    candidate_commit: str = ""
    #: The TestEvidenceRecord.evidence_id that justified the LAB -> CANDIDATE
    #: transition, so a future trusted release supervisor can trace exactly
    #: which gate run approved this candidate.
    candidate_evidence_id: str = ""

    def __post_init__(self) -> None:
        if not self.feature_id.strip():
            raise ValueError("feature_id cannot be empty")
        if not self.capability_id.strip():
            raise ValueError("capability_id cannot be empty")
        if not self.name.strip():
            raise ValueError("name cannot be empty")

    def transition(self, target: FeatureState) -> "FeatureRecord":
        target = FeatureState(target)
        if target is self.status:
            return self
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"Invalid NOVA Lab transition: {self.status.value} -> {target.value}"
            )

        now = _now()
        changes: dict[str, Any] = {"status": target, "updated_at": now}
        if target is FeatureState.ACTIVE:
            changes["promoted_at"] = now
        if target is FeatureState.RETIRED:
            changes["retired_at"] = now
        if target is FeatureState.LAB and self.status is FeatureState.RETIRED:
            changes["retired_at"] = None
        if target is FeatureState.LAB and self.status is FeatureState.CANDIDATE:
            # A rejected candidate returns to LAB with a clean slate: the old
            # commit/evidence pairing is stale and must not be mistaken for a
            # still-valid candidate designation if this feature re-enters
            # CANDIDATE later with fresh evidence.
            changes["candidate_commit"] = ""
            changes["candidate_evidence_id"] = ""

        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["notes"] = list(self.notes)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeatureRecord":
        payload = dict(data)
        payload["status"] = FeatureState(payload.get("status", FeatureState.LAB.value))
        payload["notes"] = tuple(payload.get("notes", ()))
        return cls(**payload)
