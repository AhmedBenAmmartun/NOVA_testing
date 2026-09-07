from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from .models import Fact, FactStatus


class FreshnessState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    name: str
    fresh_for_seconds: float
    expire_after_seconds: float

    def __post_init__(self) -> None:
        if self.fresh_for_seconds < 0:
            raise ValueError("fresh_for_seconds cannot be negative")
        if self.expire_after_seconds < self.fresh_for_seconds:
            raise ValueError("expire_after_seconds must be >= fresh_for_seconds")


GIT_STATUS_POLICY = FreshnessPolicy("git_status", 15.0, 120.0)
RUNTIME_POLICY = FreshnessPolicy("runtime", 5.0, 30.0)
FILE_POLICY = FreshnessPolicy("file", 300.0, 3600.0)
DOC_POLICY = FreshnessPolicy("documentation", 900.0, 86_400.0)
TEST_POLICY = FreshnessPolicy("test_evidence", 3600.0, 86_400.0)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assess_freshness(
    observed_at: str,
    policy: FreshnessPolicy,
    *,
    now: datetime | None = None,
) -> FreshnessState:
    observed = _parse_iso(observed_at)
    if observed is None:
        return FreshnessState.UNKNOWN

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    age = max(0.0, (current.astimezone(timezone.utc) - observed).total_seconds())

    if age <= policy.fresh_for_seconds:
        return FreshnessState.FRESH
    if age <= policy.expire_after_seconds:
        return FreshnessState.STALE
    return FreshnessState.EXPIRED


def apply_freshness(fact: Fact, policy: FreshnessPolicy) -> Fact:
    if fact.status in {FactStatus.UNKNOWN, FactStatus.CONFLICT}:
        return fact

    if not fact.provenance:
        return fact.with_status(FactStatus.STALE, freshness=FreshnessState.UNKNOWN.value)

    state = assess_freshness(fact.provenance[0].observed_at, policy)
    if state is FreshnessState.FRESH:
        return fact.with_status(fact.status, freshness=state.value)
    if state in {FreshnessState.STALE, FreshnessState.EXPIRED}:
        return fact.with_status(FactStatus.STALE, freshness=state.value)
    return fact.with_status(FactStatus.STALE, freshness=FreshnessState.UNKNOWN.value)
