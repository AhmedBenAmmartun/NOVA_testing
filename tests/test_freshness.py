from __future__ import annotations

from datetime import datetime, timedelta, timezone

from nova_intelligence.freshness import (
    FreshnessPolicy,
    FreshnessState,
    apply_freshness,
    assess_freshness,
)
from nova_intelligence.models import Fact, FactStatus, ProvenanceRef


def _iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def test_assess_freshness_transitions() -> None:
    policy = FreshnessPolicy("test", 10, 20)
    now = datetime.now(timezone.utc)

    fresh = assess_freshness((now - timedelta(seconds=5)).isoformat(), policy, now=now)
    stale = assess_freshness((now - timedelta(seconds=15)).isoformat(), policy, now=now)
    expired = assess_freshness((now - timedelta(seconds=30)).isoformat(), policy, now=now)

    assert fresh is FreshnessState.FRESH
    assert stale is FreshnessState.STALE
    assert expired is FreshnessState.EXPIRED


def test_apply_freshness_never_upgrades_unknown() -> None:
    fact = Fact("x", None, FactStatus.UNKNOWN)
    result = apply_freshness(fact, FreshnessPolicy("x", 1, 2))
    assert result.status is FactStatus.UNKNOWN


def test_apply_freshness_downgrades_old_verified_fact() -> None:
    prov = ProvenanceRef("git", "status", _iso(100))
    fact = Fact("branch", "main", FactStatus.VERIFIED, provenance=(prov,))
    result = apply_freshness(fact, FreshnessPolicy("git", 1, 2))
    assert result.status is FactStatus.STALE
    assert result.freshness == "expired"
