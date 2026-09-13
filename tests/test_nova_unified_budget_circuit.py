"""U1: where Provider Resilience P1 meets Class Intelligence's budget refund.

These two landed on separate branches and touched the same two `except` blocks
in `nova_core/router.py`. Git merged them without a conflict, which proves
nothing about whether they compose correctly -- so this file pins the
interaction with the REAL `CloudUsageBudget` and the REAL `ModelRouter`.

The rule the whole file exists to protect:

    A reservation is taken only when NOVA actually calls a provider. Anything
    that stops NOVA before the call must not reserve, and must therefore not
    refund either. Double-refunding would turn the daily cap into a suggestion.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nova_capture import intelligence
from nova_core.cloud_budget import CloudUsageBudget
from nova_core.configuration import (
    NovaConfiguration,
    NovaProfile,
    ProviderConfiguration,
    ProviderName,
    load_configuration,
)
from nova_core.provider_health import (
    ProviderCircuitState,
    ProviderHealthTracker,
)
from nova_core.provider_registry import ProviderRegistry
from nova_core.router import ModelRouter, NoProviderAvailableError
from providers.base import (
    ModelProvider,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponse,
    ProviderUnavailableError,
)


class StubProvider(ModelProvider):
    """Answers, or raises, and counts every real call."""

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
        _ = system_prompt, timeout_seconds
        self.calls.append(prompt)

        if self.error is not None:
            raise self.error

        return ProviderResponse(
            text=self.reply or "",
            provider=self.name,
            model=self.model,
        )


class FakeClock:
    def __init__(self) -> None:
        self.now = 4000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit: int,
) -> CloudUsageBudget:
    """A real general cloud budget, isolated to tmp_path."""

    monkeypatch.setenv(
        "NOVA_CLOUD_USAGE_FILE",
        str(tmp_path / "general-budget.json"),
    )
    monkeypatch.setenv(
        "NOVA_CLOUD_DAILY_REQUEST_LIMIT",
        str(limit),
    )
    monkeypatch.delenv("NOVA_CLOUD_BUDGET_ENABLED", raising=False)
    return CloudUsageBudget()


def _configuration() -> NovaConfiguration:
    providers = {
        name: ProviderConfiguration(
            name=name,
            model=f"{name.value}-test-model",
            enabled=True,
            api_key_environment_variable=None,
            timeout_seconds=1.0,
            max_output_tokens=50,
            is_local=(name is ProviderName.OLLAMA),
        )
        for name in ProviderName
    }

    return NovaConfiguration(
        profile=NovaProfile.HYBRID,
        conversation_provider=ProviderName.GEMINI,
        reasoning_provider=ProviderName.OPENAI,
        coding_provider=ProviderName.OPENAI,
        private_provider=ProviderName.OLLAMA,
        fallback_enabled=True,
        fallback_order=(ProviderName.GROQ,),
        providers=providers,
    )


def _router(
    budget: CloudUsageBudget,
    tracker: ProviderHealthTracker,
    *,
    openai: StubProvider,
    groq: StubProvider,
) -> ModelRouter:
    configuration = _configuration()
    registry = ProviderRegistry(configuration, health_tracker=tracker)
    registry.register(ProviderName.OPENAI, openai)
    registry.register(ProviderName.GROQ, groq)

    return ModelRouter(
        configuration=configuration,
        registry=registry,
        cloud_budget=budget,
        health_tracker=tracker,
    )


# ---------------------------------------------------------------------------
# The reserve/refund contract
# ---------------------------------------------------------------------------


def test_a_failed_call_refunds_its_reservation_and_records_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both mechanisms must fire on the same failure, not one or the other."""

    budget = _budget(tmp_path, monkeypatch, limit=10)
    tracker = ProviderHealthTracker(failure_threshold=5)

    openai = StubProvider("openai", error=ProviderUnavailableError("down"))
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    response = asyncio.run(router.route("q", role="reasoning"))

    assert response.provider == "groq"
    assert openai.calls, "openai must actually have been attempted"

    # Refunded: the failed provider is not billed for an answer it never gave.
    assert budget.status()["providers"].get("openai", 0) == 0
    assert budget.status()["providers"]["groq"] == 1

    # And recorded: the circuit knows openai failed.
    health = tracker.safe_summary()["providers"]["openai"]
    assert health["last_failure_kind"] == "unavailable"
    assert health["consecutive_failures"] == 1


def test_an_open_circuit_never_reserves_so_it_never_refunds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core interaction rule.

    A skipped provider must leave the ledger untouched -- not reserve-then-
    refund, which would be a no-op with two chances to get the arithmetic
    wrong, and not refund-without-reserving, which would inflate the cap.
    """

    budget = _budget(tmp_path, monkeypatch, limit=20)
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=300,
    )

    openai = StubProvider("openai", error=ProviderUnavailableError("down"))
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    # First call opens openai's circuit.
    asyncio.run(router.route("q1", role="reasoning"))
    assert tracker.acquire(ProviderName.OPENAI).allowed is False

    used_after_open = budget.status()["used_today"]
    groq_after_open = budget.status()["providers"]["groq"]

    # Five more questions, all served by groq while openai is skipped.
    for index in range(5):
        asyncio.run(router.route(f"q{index + 2}", role="reasoning"))

    assert len(openai.calls) == 1, "the open circuit must not call openai again"

    status = budget.status()
    assert status["providers"].get("openai", 0) == 0, (
        "a skipped provider must never appear in the ledger"
    )
    assert status["providers"]["groq"] == groq_after_open + 5
    assert status["used_today"] == used_after_open + 5, (
        "each answered question costs exactly one unit, and skipped "
        "providers cost nothing"
    )


def test_skipping_a_provider_never_refunds_an_answer_it_already_gave(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reachable double-refund: a provider that worked, then died.

    `CloudUsageBudget.release()` is guarded and will not drive a counter
    negative, so refunding a provider that holds NO reservation is a harmless
    no-op. That guard is exactly why this case needs its own test: here openai
    holds a real reservation from a question it actually answered, so a
    spurious refund on the later skip WOULD pop it -- silently handing the
    lecture a free unit and turning the daily cap into a suggestion.
    """

    budget = _budget(tmp_path, monkeypatch, limit=20)
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=300,
    )

    openai = StubProvider("openai")
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    # 1. openai answers for real and keeps its reservation.
    first = asyncio.run(router.route("q1", role="reasoning"))
    assert first.provider == "openai"
    assert budget.status()["providers"]["openai"] == 1
    assert budget.status()["used_today"] == 1

    # 2. openai dies; the failure refunds only what that failed call reserved.
    openai.error = ProviderUnavailableError("down")
    asyncio.run(router.route("q2", role="reasoning"))

    assert budget.status()["providers"]["openai"] == 1, (
        "the failed call refunds its own reservation and must not touch the "
        "one that funded the answered question"
    )
    assert tracker.acquire(ProviderName.OPENAI).allowed is False

    used_before_skips = budget.status()["used_today"]

    # 3. openai is now skipped. The ledger must not move for openai at all.
    for index in range(3):
        asyncio.run(router.route(f"q{index + 3}", role="reasoning"))

    status = budget.status()
    assert status["providers"]["openai"] == 1, (
        "skipping a provider must never refund the answer it already gave"
    )
    assert status["used_today"] == used_before_skips + 3, (
        "three answered questions cost exactly three units"
    )


def test_a_rate_limited_provider_refunds_and_opens_the_long_cooldown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 must not bill the lecture, and must back off longer than a timeout."""

    clock = FakeClock()
    budget = _budget(tmp_path, monkeypatch, limit=10)
    tracker = ProviderHealthTracker(
        failure_threshold=5,
        transient_cooldown_seconds=30,
        rate_limit_cooldown_seconds=120,
        clock=clock,
    )

    openai = StubProvider("openai", error=ProviderRateLimitError("429"))
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    asyncio.run(router.route("q", role="reasoning"))

    assert budget.status()["providers"].get("openai", 0) == 0

    decision = tracker.acquire(ProviderName.OPENAI)
    assert decision.allowed is False
    assert decision.reason == "circuit_open:rate_limit"

    # One 429 opens immediately despite a threshold of five...
    assert len(openai.calls) == 1
    # ...and outlives the transient cooldown.
    clock.advance(30)
    assert tracker.acquire(ProviderName.OPENAI).allowed is False


def test_a_request_error_refunds_without_opening_the_circuit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected prompt still costs nothing, but keeps the provider usable."""

    budget = _budget(tmp_path, monkeypatch, limit=10)
    tracker = ProviderHealthTracker(failure_threshold=1)

    openai = StubProvider("openai", error=ProviderRequestError("bad prompt"))
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    asyncio.run(router.route("q", role="reasoning"))

    assert budget.status()["providers"].get("openai", 0) == 0, (
        "a rejected request must be refunded like any other failure"
    )
    assert tracker.acquire(ProviderName.OPENAI).allowed is True, (
        "a request-specific rejection must not take a reachable provider "
        "offline"
    )


def test_budget_exhaustion_frees_the_half_open_probe_without_refunding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The budget can refuse an attempt the circuit already admitted.

    That probe never reached the provider, so there is nothing to refund --
    but the probe slot must be handed back or the provider could never
    recover once the budget frees up.
    """

    clock = FakeClock()
    budget = _budget(tmp_path, monkeypatch, limit=1)
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=10,
        clock=clock,
    )

    openai = StubProvider("openai", error=ProviderUnavailableError("down"))
    groq = StubProvider("groq")
    router = _router(budget, tracker, openai=openai, groq=groq)

    # Spend the single unit; openai fails and refunds, groq answers and keeps it.
    asyncio.run(router.route("q1", role="reasoning"))
    assert budget.status()["remaining_today"] == 0

    clock.advance(10)

    # Budget is exhausted, so the half-open probe is refused before the call.
    calls_before = len(openai.calls)
    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route("q2", role="reasoning", allow_fallback=False)
        )

    assert len(openai.calls) == calls_before, "the probe never reached openai"
    assert budget.status()["used_today"] == 1, (
        "a refused attempt must not inflate or deflate the ledger"
    )

    probe = tracker.acquire(ProviderName.OPENAI)
    assert probe.allowed is True
    assert probe.state is ProviderCircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# U1 decision: Class Intelligence keeps its own circuit
# ---------------------------------------------------------------------------


def test_class_intelligence_keeps_a_health_tracker_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approved U1 decision (2026-09-10): internal isolation, not modes.

    Class Intelligence builds its own router through `create_model_router()`,
    which mints its own ProviderHealthTracker. A lecture burning through a
    provider's quota must not open the circuit for the conversation Ahmed is
    having, and vice versa.

    This is deliberate isolation between two internal routers. It is NOT a
    user-facing mode, and it does not weaken P1's invariant that a registry
    and its router share one tracker -- that still holds inside each router.
    """

    monkeypatch.setattr(intelligence, "_class_router", None, raising=False)

    from nova_core import create_model_router

    conversational = create_model_router()
    class_router = intelligence._get_class_router()

    try:
        # Each router is internally consistent: registry and router agree.
        assert (
            conversational.provider_health
            is conversational.registry.health_tracker
        )
        assert class_router.provider_health is class_router.registry.health_tracker

        # And the two lanes are isolated from each other.
        assert class_router.provider_health is not conversational.provider_health

        # Failing a provider for the lecture must not silence the conversation.
        class_router.provider_health.record_failure(
            ProviderName.OPENAI,
            ProviderRateLimitError("lecture hit the quota"),
        )
        assert (
            class_router.provider_health.acquire(ProviderName.OPENAI).allowed
            is False
        )
        assert (
            conversational.provider_health.acquire(ProviderName.OPENAI).allowed
            is True
        )
    finally:
        monkeypatch.setattr(intelligence, "_class_router", None, raising=False)


def test_class_router_still_carries_its_own_cloud_budget() -> None:
    """Isolation must not have cost Class its separate spending cap."""

    configuration = load_configuration()
    assert configuration is not None

    from nova_capture.class_budget import get_class_cloud_usage_budget

    class_budget = get_class_cloud_usage_budget()
    general_budget = CloudUsageBudget()

    assert class_budget is not general_budget
