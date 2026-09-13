"""A cloud request that returns nothing must cost nothing.

The bug this file pins, measured on 2026-09-01: the live class budget file
recorded 111 groq + 74 openai = 185 reserved requests against a 200/day cap,
while that day's class_capture.log showed only 4 successful groq selections and
84 ProviderUnavailableError failures. Roughly 180 of the 185 reserved units
bought nothing at all.

``nova_core/router.py`` reserved a unit *before* calling ``provider.generate()``
and never gave it back when generate() raised, so every unreachable-provider
attempt was billed as if it had answered. Class Intelligence made that worse:
``intelligence._route`` walks the cloud tier one provider at a time, so a single
class question during a full outage burned one unit per provider and still
returned None.

The cost is no longer merely wasted quota. Class Intelligence is cloud-first and
no longer falls back to a local model, so an exhausted budget means the lecture
gets no live notes at all.

The rule: a reservation is released when the provider call fails, a successful
call keeps its reservation, and the two budgets (general NOVA and class) stay
independent of each other.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nova_capture import intelligence
from nova_capture.class_budget import ClassCloudUsageBudget
from nova_core import (
    ModelRouter,
    NoProviderAvailableError,
    ProviderName,
    ProviderRegistry,
    load_configuration,
)
from nova_core.cloud_budget import CloudUsageBudget
from providers import ProviderResponse, ProviderUnavailableError
from providers.base import ModelProvider


class StubProvider(ModelProvider):
    """A provider that either answers or raises, and counts its calls."""

    def __init__(
        self,
        name: str,
        *,
        is_local: bool = False,
        reply: str | None = "cloud answer",
        error: Exception | None = None,
    ) -> None:
        super().__init__(model=f"{name}-test-model")
        self.name = name
        self.is_local = is_local
        self.reply = reply
        self.error = error
        self.calls: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return ProviderResponse(
            text=self.reply or "",
            provider=self.name,
            model=self.model,
            metadata={},
        )


def _class_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, limit: int
) -> ClassCloudUsageBudget:
    """A class budget isolated to tmp_path, never the real capture root."""

    monkeypatch.setenv(
        "NOVA_CLASS_CLOUD_USAGE_FILE", str(tmp_path / "class-budget.json")
    )
    monkeypatch.setenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", str(limit))
    monkeypatch.delenv("NOVA_CLASS_CLOUD_BUDGET_ENABLED", raising=False)
    return ClassCloudUsageBudget()


def _general_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, limit: int
) -> CloudUsageBudget:
    """A general NOVA budget isolated to tmp_path."""

    monkeypatch.setenv("NOVA_CLOUD_USAGE_FILE", str(tmp_path / "general-budget.json"))
    monkeypatch.setenv("NOVA_CLOUD_DAILY_REQUEST_LIMIT", str(limit))
    monkeypatch.delenv("NOVA_CLOUD_BUDGET_ENABLED", raising=False)
    return CloudUsageBudget()


def _router(
    budget,
    *,
    openai: StubProvider | None = None,
    groq: StubProvider | None = None,
    ollama: StubProvider | None = None,
) -> tuple[ModelRouter, dict[str, StubProvider]]:
    configuration = load_configuration()
    registry = ProviderRegistry(configuration)
    providers = {
        "openai": openai or StubProvider("openai"),
        "groq": groq or StubProvider("groq"),
        "ollama": ollama
        or StubProvider("ollama", is_local=True, reply="local answer"),
    }
    registry.register(ProviderName.OPENAI, providers["openai"])
    registry.register(ProviderName.GROQ, providers["groq"])
    registry.register(ProviderName.OLLAMA, providers["ollama"])
    router = ModelRouter(
        configuration=configuration,
        registry=registry,
        cloud_budget=budget,
    )
    return router, providers


@pytest.fixture(autouse=True)
def _reset_class_router(monkeypatch: pytest.MonkeyPatch):
    """_get_class_router() memoises into a module global with no reset hook."""

    monkeypatch.setattr(intelligence, "_class_router", None, raising=False)
    monkeypatch.delenv("NOVA_CLASS_ALLOW_LOCAL_FALLBACK", raising=False)
    monkeypatch.delenv("NOVA_CLASS_CLOUD_PROVIDER_ORDER", raising=False)
    yield
    monkeypatch.setattr(intelligence, "_class_router", None, raising=False)


# --- the core rule: a failed call costs nothing -----------------------------


def test_a_failed_cloud_call_does_not_consume_class_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _class_budget(tmp_path, monkeypatch, limit=10)
    router, providers = _router(
        budget, groq=StubProvider("groq", error=ProviderUnavailableError("refused"))
    )

    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route(
                "explain cohesion",
                preferred_provider=ProviderName.GROQ,
                allow_fallback=False,
            )
        )

    assert providers["groq"].calls, "the provider must actually have been attempted"
    assert budget.status()["used_today"] == 0, (
        "an unreachable provider returned nothing and must have been refunded"
    )
    assert budget.status()["providers"].get("groq", 0) == 0, (
        "the per-provider counter must be refunded too, not just the total"
    )


def test_a_successful_cloud_call_keeps_its_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _class_budget(tmp_path, monkeypatch, limit=10)
    router, _ = _router(budget)

    response = asyncio.run(
        router.route(
            "explain cohesion",
            preferred_provider=ProviderName.GROQ,
            allow_fallback=False,
        )
    )

    assert response.text == "cloud answer"
    assert budget.status()["used_today"] == 1, (
        "a request that produced an answer must still be billed"
    )
    assert budget.status()["providers"]["groq"] == 1


def test_an_unexpected_provider_crash_also_refunds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The router has a second except branch for non-ProviderError crashes."""

    budget = _class_budget(tmp_path, monkeypatch, limit=10)
    router, _ = _router(budget, groq=StubProvider("groq", error=RuntimeError("boom")))

    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route(
                "explain cohesion",
                preferred_provider=ProviderName.GROQ,
                allow_fallback=False,
            )
        )

    assert budget.status()["used_today"] == 0


def test_a_local_provider_neither_consumes_nor_refunds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local providers were never metered; a refund must not credit them."""

    budget = _class_budget(tmp_path, monkeypatch, limit=10)
    router, _ = _router(
        budget,
        ollama=StubProvider(
            "ollama", is_local=True, error=ProviderUnavailableError("down")
        ),
    )

    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route(
                "explain cohesion",
                preferred_provider=ProviderName.OLLAMA,
                allow_fallback=False,
            )
        )

    assert budget.status()["used_today"] == 0
    assert budget.status()["providers"].get("ollama", 0) == 0


def test_the_general_budget_is_refunded_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nova_core's own budget takes the same router path and needs the same fix."""

    budget = _general_budget(tmp_path, monkeypatch, limit=10)
    router, _ = _router(
        budget, groq=StubProvider("groq", error=ProviderUnavailableError("refused"))
    )

    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route(
                "explain cohesion",
                preferred_provider=ProviderName.GROQ,
                allow_fallback=False,
            )
        )

    assert budget.status()["used_today"] == 0


# --- the reported scenario: one dead provider must not starve the other -----


def test_a_dead_provider_no_longer_drains_the_shared_class_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 2026-09-01 shape: openai unreachable all lecture, groq healthy.

    The cap is deliberately one global total across providers. That is only
    safe because a failure costs nothing -- otherwise the dead provider spends
    half of every question's budget and takes the healthy one down with it.

    U1 note (2026-09-10): this test originally also asserted that openai was
    attempted all ten times, because the Class refund was the only thing
    standing between a dead provider and the shared cap. Provider Resilience
    P1's circuit breaker now stops attempting a provider that has failed
    NOVA_PROVIDER_FAILURE_THRESHOLD times in a row.

    That expectation is SUPERSEDED, not the invariant. The invariant -- a dead
    provider must not drain the shared class cap -- is unchanged and is
    asserted below. P1 makes it strictly stronger: a skipped provider never
    reserves the budget at all, and the lecture stops paying its timeout
    latency on every question.
    """

    outage = ProviderUnavailableError("connection refused")
    budget = _class_budget(tmp_path, monkeypatch, limit=10)
    router, providers = _router(budget, openai=StubProvider("openai", error=outage))
    monkeypatch.setattr(intelligence, "_get_class_router", lambda: router)

    answers = [
        asyncio.run(intelligence._route(f"question {index}")) for index in range(10)
    ]

    # --- the invariant, unchanged ------------------------------------------
    assert all(answer == "cloud answer" for answer in answers), (
        "a 10-unit cap must fund 10 answered questions, not 5, "
        "when the only failing provider produced nothing"
    )
    assert budget.status()["used_today"] == 10
    assert budget.status()["providers"].get("openai", 0) == 0, (
        "a provider that never answered must not appear in the ledger"
    )
    assert budget.status()["providers"]["groq"] == 10

    # --- what P1 changed: the mechanism, for the better --------------------
    threshold = router.provider_health.failure_threshold
    assert len(providers["openai"].calls) == threshold, (
        "the circuit breaker must stop attempting a provider that keeps "
        f"failing; expected exactly {threshold} attempts before the circuit "
        "opened, then skips"
    )
    assert len(providers["openai"].calls) < len(answers), (
        "P1 must spare the lecture the wasted attempts the refund path "
        "used to pay for on every single question"
    )


def test_the_class_cap_still_stops_at_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refunding must not turn the ceiling into a suggestion."""

    budget = _class_budget(tmp_path, monkeypatch, limit=3)
    router, _ = _router(budget)
    monkeypatch.setattr(intelligence, "_get_class_router", lambda: router)

    answers = [
        asyncio.run(intelligence._route(f"question {index}")) for index in range(6)
    ]

    assert answers[:3] == ["cloud answer"] * 3
    assert answers[3:] == [None] * 3, "past the cap, class intelligence defers"
    assert budget.status()["used_today"] == 3


# --- release() semantics ----------------------------------------------------


def test_class_release_returns_the_counter_to_its_previous_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _class_budget(tmp_path, monkeypatch, limit=5)
    budget.try_consume("groq")
    budget.try_consume("groq")
    assert budget.status()["used_today"] == 2

    budget.release("groq")

    assert budget.status()["used_today"] == 1
    assert budget.status()["providers"]["groq"] == 1


def test_class_release_never_drives_a_counter_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A midnight rollover resets the file; a late refund must not underflow."""

    budget = _class_budget(tmp_path, monkeypatch, limit=5)

    budget.release("groq")
    budget.release("groq")

    assert budget.status()["used_today"] == 0
    assert budget.status()["providers"].get("groq", 0) == 0


def test_class_release_is_a_no_op_when_the_budget_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """try_consume() writes nothing when disabled, so release must not either."""

    usage_path = tmp_path / "class-budget.json"
    monkeypatch.setenv("NOVA_CLASS_CLOUD_USAGE_FILE", str(usage_path))
    monkeypatch.setenv("NOVA_CLASS_CLOUD_BUDGET_ENABLED", "false")
    budget = ClassCloudUsageBudget()

    assert budget.try_consume("groq").allowed
    budget.release("groq")

    assert not usage_path.exists(), "a disabled budget must not write a ledger"


def test_class_release_is_a_no_op_when_the_budget_is_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage_path = tmp_path / "class-budget.json"
    monkeypatch.setenv("NOVA_CLASS_CLOUD_USAGE_FILE", str(usage_path))
    monkeypatch.setenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", "-1")
    budget = ClassCloudUsageBudget()

    assert budget.try_consume("groq").allowed
    budget.release("groq")

    assert not usage_path.exists(), "an unlimited budget must not write a ledger"


def test_general_release_returns_the_counter_to_its_previous_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _general_budget(tmp_path, monkeypatch, limit=5)
    budget.try_consume("openai")
    budget.try_consume("openai")

    budget.release("openai")

    assert budget.status()["used_today"] == 1
    assert budget.status()["providers"]["openai"] == 1


def test_general_release_never_drives_a_counter_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _general_budget(tmp_path, monkeypatch, limit=5)

    budget.release("openai")

    assert budget.status()["used_today"] == 0


def test_releasing_the_class_budget_leaves_the_general_budget_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two budgets stay independent -- separate files, separate counters."""

    general = _general_budget(tmp_path, monkeypatch, limit=5)
    class_budget = _class_budget(tmp_path, monkeypatch, limit=5)

    general.try_consume("openai")
    class_budget.try_consume("openai")
    class_budget.release("openai")

    assert class_budget.status()["used_today"] == 0
    assert general.status()["used_today"] == 1, (
        "a class refund must never credit NOVA's general cloud allowance"
    )
    assert general.path != class_budget.path
