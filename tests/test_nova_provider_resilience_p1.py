"""Provider Resilience P1 contract tests.

NOVA has no pytest-asyncio plugin installed, so async scenarios run through
`asyncio.run(...)` inside ordinary sync tests -- the same convention the rest
of the NOVA suite uses.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from livekit.agents import llm as livekit_llm
from openai import APIStatusError

from nova_runtime import HealthState

from nova_core.configuration import (
    NovaConfiguration,
    NovaProfile,
    ProviderConfiguration,
    ProviderName,
)
from nova_core.provider_health import (
    ProviderCircuitState,
    ProviderFailureKind,
    ProviderHealthTracker,
    classify_provider_error,
)
from nova_core.provider_registry import ProviderRegistry
from nova_core.realtime import (
    RealtimeFailureKind,
    classify_realtime_error,
)
from nova_core.router import ModelRouter, NoProviderAvailableError
from providers.groq_provider import GroqProvider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.base import (
    ModelProvider,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponse,
    ProviderUnavailableError,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    """Deterministic monotonic clock so cooldown tests never sleep."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProvider(ModelProvider):
    is_local = False

    def __init__(self, *, name: str, outcomes: list[object]) -> None:
        super().__init__(model=f"{name}-test-model")
        self.name = name
        self.outcomes = list(outcomes)
        self.generate_calls = 0
        self.health_reachable = True

    @property
    def configured(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return self.health_reachable

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        _ = prompt, system_prompt, timeout_seconds
        self.generate_calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"

        if isinstance(outcome, BaseException):
            raise outcome

        return ProviderResponse(
            text=str(outcome),
            provider=self.name,
            model=self.model,
        )


@dataclass
class FakeBudgetDecision:
    allowed: bool = True
    used: int = 0
    limit: int = 100
    reason: str | None = None


class FakeBudget:
    """Cloud budget stub that always allows, so P1 tests isolate health.

    `release()` exists because U1 merged Class Intelligence's refund path into
    the router: a failed provider now hands its reservation back. Without it
    the router's `_release_cloud_budget` would raise AttributeError into a
    defensive `except Exception` and these tests would pass while quietly
    logging tracebacks.
    """

    def __init__(self) -> None:
        self.released: list[str] = []

    def try_consume(self, provider: str) -> FakeBudgetDecision:
        _ = provider
        return FakeBudgetDecision()

    def release(self, provider: str) -> None:
        self.released.append(provider)

    def status(self) -> dict[str, object]:
        return {"enabled": True, "used": 0, "limit": 100}


class DenyingBudget(FakeBudget):
    """Cloud budget stub that always refuses cloud providers."""

    def try_consume(self, provider: str) -> FakeBudgetDecision:
        _ = provider
        return FakeBudgetDecision(
            allowed=False,
            reason="daily_cloud_limit_reached",
        )


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


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_transient_failures_open_after_threshold_and_recover_half_open() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=2,
        transient_cooldown_seconds=10,
        clock=clock,
    )

    tracker.record_failure_kind(
        ProviderName.OPENAI,
        ProviderFailureKind.UNAVAILABLE,
        error_type="Timeout",
    )
    assert (
        tracker.safe_summary()["providers"]["openai"]["state"]
        == ProviderCircuitState.CLOSED.value
    )

    tracker.record_failure_kind(
        ProviderName.OPENAI,
        ProviderFailureKind.UNAVAILABLE,
        error_type="Timeout",
    )

    denied = tracker.acquire(ProviderName.OPENAI)
    assert denied.allowed is False
    assert denied.reason == "circuit_open:unavailable"

    clock.advance(10)

    probe = tracker.acquire(ProviderName.OPENAI)
    assert probe.allowed is True
    assert probe.state is ProviderCircuitState.HALF_OPEN

    second_probe = tracker.acquire(ProviderName.OPENAI)
    assert second_probe.allowed is False
    assert second_probe.reason == "half_open_probe_in_flight"

    tracker.record_success(ProviderName.OPENAI)

    healthy = tracker.acquire(ProviderName.OPENAI)
    assert healthy.allowed is True
    assert healthy.state is ProviderCircuitState.CLOSED


def test_failed_half_open_probe_reopens_the_circuit() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=2,
        transient_cooldown_seconds=10,
        clock=clock,
    )

    for _ in range(2):
        tracker.record_failure(
            ProviderName.OPENAI,
            ProviderUnavailableError("down"),
        )

    clock.advance(10)
    probe = tracker.acquire(ProviderName.OPENAI)
    assert probe.state is ProviderCircuitState.HALF_OPEN

    # One failed probe is enough; the threshold does not restart.
    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderUnavailableError("still down"),
    )

    reopened = tracker.acquire(ProviderName.OPENAI)
    assert reopened.allowed is False
    assert reopened.state is ProviderCircuitState.OPEN
    assert reopened.cooldown_remaining_seconds == 10


def test_rate_limit_opens_immediately_with_longer_cooldown() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=5,
        transient_cooldown_seconds=5,
        rate_limit_cooldown_seconds=60,
        clock=clock,
    )

    tracker.record_failure(
        ProviderName.GROQ,
        ProviderRateLimitError("do not expose this raw message"),
    )

    denied = tracker.acquire(ProviderName.GROQ)
    assert denied.allowed is False
    assert denied.reason == "circuit_open:rate_limit"
    assert denied.cooldown_remaining_seconds == 60


def test_request_error_does_not_poison_provider_health() -> None:
    tracker = ProviderHealthTracker(failure_threshold=1)

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderRequestError("bad request"),
    )

    decision = tracker.acquire(ProviderName.OPENAI)
    assert decision.allowed is True

    summary = tracker.safe_summary()["providers"]["openai"]
    assert summary["state"] == "closed"
    assert summary["consecutive_failures"] == 0
    assert summary["last_failure_kind"] == "request"


def test_provider_error_classification_covers_every_kind() -> None:
    assert classify_provider_error(
        ProviderNotConfiguredError("x")
    ) is ProviderFailureKind.NOT_CONFIGURED

    # ProviderRateLimitError subclasses ProviderUnavailableError, so the
    # narrower class must win.
    assert classify_provider_error(
        ProviderRateLimitError("x")
    ) is ProviderFailureKind.RATE_LIMIT

    assert classify_provider_error(
        ProviderUnavailableError("x")
    ) is ProviderFailureKind.UNAVAILABLE

    assert classify_provider_error(
        ProviderRequestError("x")
    ) is ProviderFailureKind.REQUEST

    assert classify_provider_error(
        RuntimeError("x")
    ) is ProviderFailureKind.UNEXPECTED


def test_disabled_circuit_breaker_never_blocks_a_provider() -> None:
    tracker = ProviderHealthTracker(
        enabled=False,
        failure_threshold=1,
    )

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderUnavailableError("down"),
    )

    decision = tracker.acquire(ProviderName.OPENAI)
    assert decision.allowed is True
    assert decision.reason == "circuit_breaker_disabled"


def test_safe_summary_never_contains_raw_error_message() -> None:
    tracker = ProviderHealthTracker(failure_threshold=1)
    secret_like_text = "sensitive-marker-must-never-enter-health"

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderUnavailableError(secret_like_text),
    )

    serialized = repr(tracker.safe_summary())
    assert secret_like_text not in serialized
    assert "ProviderUnavailableError" in serialized


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------


def test_router_skips_open_primary_without_calling_it_again() -> None:
    tracker = ProviderHealthTracker(
        failure_threshold=2,
        transient_cooldown_seconds=120,
    )
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    primary = FakeProvider(
        name="openai",
        outcomes=[
            ProviderUnavailableError("timeout one"),
            ProviderUnavailableError("timeout two"),
        ],
    )
    fallback = FakeProvider(
        name="groq",
        outcomes=["fallback-1", "fallback-2", "fallback-3"],
    )

    registry.register(ProviderName.OPENAI, primary)
    registry.register(ProviderName.GROQ, fallback)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
        health_tracker=tracker,
    )

    async def scenario() -> tuple[
        ProviderResponse,
        ProviderResponse,
        ProviderResponse,
    ]:
        first = await router.route("one", role="reasoning")
        second = await router.route("two", role="reasoning")
        third = await router.route("three", role="reasoning")
        return first, second, third

    first, second, third = asyncio.run(scenario())

    assert first.provider == "groq"
    assert second.provider == "groq"
    assert third.provider == "groq"
    assert first.used_fallback is True

    # The third request must not spend another doomed call on the primary.
    assert primary.generate_calls == 2
    assert fallback.generate_calls == 3

    assert third.metadata["attempts"][0]["reason"] == (
        "circuit_open:unavailable"
    )
    assert (
        third.metadata["provider_health"]["providers"]["openai"]["state"]
        == "open"
    )


def test_router_recovers_primary_after_cooldown_probe_succeeds() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=30,
        clock=clock,
    )
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    primary = FakeProvider(
        name="openai",
        outcomes=[
            ProviderUnavailableError("timeout"),
            "primary-recovered",
        ],
    )
    fallback = FakeProvider(name="groq", outcomes=["fallback-1"])

    registry.register(ProviderName.OPENAI, primary)
    registry.register(ProviderName.GROQ, fallback)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
        health_tracker=tracker,
    )

    first = asyncio.run(router.route("one", role="reasoning"))
    assert first.provider == "groq"
    assert tracker.acquire(ProviderName.OPENAI).allowed is False

    clock.advance(30)

    second = asyncio.run(router.route("two", role="reasoning"))
    assert second.provider == "openai"
    assert second.used_fallback is False
    assert (
        second.metadata["provider_health"]["providers"]["openai"]["state"]
        == "closed"
    )


def test_router_request_error_keeps_primary_available() -> None:
    tracker = ProviderHealthTracker(failure_threshold=1)
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    primary = FakeProvider(
        name="openai",
        outcomes=[
            ProviderRequestError("this prompt was rejected"),
            "primary-ok",
        ],
    )
    fallback = FakeProvider(name="groq", outcomes=["fallback-1"])

    registry.register(ProviderName.OPENAI, primary)
    registry.register(ProviderName.GROQ, fallback)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
        health_tracker=tracker,
    )

    first = asyncio.run(router.route("one", role="reasoning"))
    assert first.provider == "groq"

    # A request-specific rejection must not take a reachable provider offline.
    second = asyncio.run(router.route("two", role="reasoning"))
    assert second.provider == "openai"
    assert primary.generate_calls == 2


def test_router_rate_limit_opens_circuit_and_falls_back() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=5,
        transient_cooldown_seconds=5,
        rate_limit_cooldown_seconds=120,
        clock=clock,
    )
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    primary = FakeProvider(
        name="openai",
        outcomes=[ProviderRateLimitError("quota exhausted")],
    )
    fallback = FakeProvider(
        name="groq",
        outcomes=["fallback-1", "fallback-2"],
    )

    registry.register(ProviderName.OPENAI, primary)
    registry.register(ProviderName.GROQ, fallback)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
        health_tracker=tracker,
    )

    first = asyncio.run(router.route("one", role="reasoning"))
    assert first.provider == "groq"

    # One 429 is enough, even though the transient threshold is five.
    second = asyncio.run(router.route("two", role="reasoning"))
    assert second.provider == "groq"
    assert primary.generate_calls == 1
    assert second.metadata["attempts"][0]["reason"] == (
        "circuit_open:rate_limit"
    )

    # The rate-limit cooldown outlives the transient one.
    clock.advance(6)
    assert tracker.acquire(ProviderName.OPENAI).allowed is False


def test_budget_refusal_releases_the_half_open_probe_slot() -> None:
    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=10,
        clock=clock,
    )
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    provider = FakeProvider(name="openai", outcomes=["ok"])
    registry.register(ProviderName.OPENAI, provider)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=DenyingBudget(),
        health_tracker=tracker,
    )

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderUnavailableError("down"),
    )
    clock.advance(10)

    with pytest.raises(NoProviderAvailableError):
        asyncio.run(
            router.route(
                "one",
                role="reasoning",
                allow_fallback=False,
            )
        )

    # The probe never reached the provider, so the slot must be free again.
    assert provider.generate_calls == 0
    probe = tracker.acquire(ProviderName.OPENAI)
    assert probe.allowed is True
    assert probe.state is ProviderCircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# Shared tracker invariant
# ---------------------------------------------------------------------------


def test_registry_probe_and_router_share_health_tracker() -> None:
    tracker = ProviderHealthTracker(failure_threshold=1)
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    provider = FakeProvider(name="openai", outcomes=["ok"])
    provider.health_reachable = False
    registry.register(ProviderName.OPENAI, provider)

    assert asyncio.run(registry.health_check(ProviderName.OPENAI)) is False

    decision = tracker.acquire(ProviderName.OPENAI)
    assert decision.allowed is False
    assert decision.reason == "circuit_open:unavailable"


def test_router_defaults_to_the_registry_tracker_instance() -> None:
    tracker = ProviderHealthTracker()
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
    )

    assert router.provider_health is tracker
    assert router.registry.health_tracker is tracker


def test_default_factory_path_shares_exactly_one_tracker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nova_core import router as router_module

    monkeypatch.setattr(
        router_module,
        "load_configuration",
        _configuration,
    )

    built = router_module.create_model_router()

    assert built.provider_health is built.registry.health_tracker


def test_registry_summary_exposes_health_without_secrets() -> None:
    tracker = ProviderHealthTracker(failure_threshold=1)
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)
    registry.register(
        ProviderName.OPENAI,
        FakeProvider(name="openai", outcomes=["ok"]),
    )

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderUnavailableError("another-sensitive-marker"),
    )

    serialized = repr(registry.safe_summary())
    assert "another-sensitive-marker" not in serialized
    assert "health" in registry.safe_summary()


# ---------------------------------------------------------------------------
# Native realtime lane
# ---------------------------------------------------------------------------


class FakeRealtimeError(Exception):
    def __init__(
        self,
        *,
        status_code: int | None = None,
        message: str = "",
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.recoverable = recoverable


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            FakeRealtimeError(status_code=429),
            RealtimeFailureKind.RATE_LIMIT,
        ),
        (
            FakeRealtimeError(status_code=503),
            RealtimeFailureKind.UNAVAILABLE,
        ),
        (
            FakeRealtimeError(status_code=401),
            RealtimeFailureKind.AUTHENTICATION,
        ),
        (
            FakeRealtimeError(status_code=400),
            RealtimeFailureKind.REQUEST,
        ),
        (
            FakeRealtimeError(message="deadline exceeded timeout"),
            RealtimeFailureKind.UNAVAILABLE,
        ),
        (
            FakeRealtimeError(message="resource_exhausted quota"),
            RealtimeFailureKind.RATE_LIMIT,
        ),
        (
            FakeRealtimeError(message="something nobody predicted"),
            RealtimeFailureKind.UNKNOWN,
        ),
    ],
)
def test_realtime_error_classification(
    error: BaseException,
    expected: RealtimeFailureKind,
) -> None:
    assert classify_realtime_error(error) is expected


def test_realtime_classification_never_returns_the_raw_message() -> None:
    kind = classify_realtime_error(
        FakeRealtimeError(message="api key sk-should-never-leak")
    )

    assert kind is RealtimeFailureKind.AUTHENTICATION
    assert "sk-should-never-leak" not in kind.value


def test_agent_reports_realtime_health_without_overriding_recovery() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    assert "_install_realtime_provider_health(" in agent
    assert 'topic="nova.provider-status"' in agent
    assert "classify_realtime_error(provider_error)" in agent
    assert "HealthState.DEGRADED" in agent
    assert "HealthState.FAILED" in agent

    # LiveKit's own recovery semantics stay authoritative.
    assert "event.error.recoverable = True" not in agent
    assert "error.recoverable = True" not in agent


def test_agent_realtime_health_uses_the_existing_runtime_registry() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    assert "from nova_runtime import HealthState, NovaRuntime" in agent
    assert "runtime.health.set(" in agent

    # P1 must not introduce a second global runtime health system.
    assert "class HealthRegistry" not in agent
    assert "HealthRegistry()" not in agent


def test_agent_installs_health_after_runtime_and_keeps_task_recovery() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    runtime_index = agent.index("runtime = NovaRuntime()")
    install_index = agent.index("_install_realtime_provider_health(\n        ctx,")
    recovery_index = agent.index("TaskStore().recover()")

    assert runtime_index < install_index < recovery_index

    # The durable-task recovery comment the v1.0.2 installer mis-anchored on
    # is still the full multiline version, untouched.
    assert (
        "# Recover durable task state before anything new is dispatched. This is"
        in agent
    )
    assert "durable task recovery failed; starting with none" in agent


def test_p1_keeps_p0_native_realtime_boundary_and_video_contracts() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    realtime = (
        ROOT / "nova_core" / "realtime.py"
    ).read_text(encoding="utf-8-sig")

    assert "build_realtime_model()" in agent
    assert "llm=realtime_model" in agent
    assert "video_input=True" in agent
    assert "google.realtime.RealtimeModel(" not in agent
    assert (
        "types.TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO"
        in realtime
    )
    assert "START_OF_ACTIVITY_INTERRUPTS" in realtime


def test_p1_does_not_pretend_text_providers_are_native_realtime() -> None:
    realtime = (
        ROOT / "nova_core" / "realtime.py"
    ).read_text(encoding="utf-8-sig")

    from nova_core import realtime as realtime_module

    assert "RealtimeProviderUnsupportedError" in realtime
    assert hasattr(realtime_module, "classify_realtime_error")

    # Gemini remains the only native audio/video realtime lane.
    for text_provider in ("groq", "openai", "ollama"):
        assert f'route="{text_provider}_realtime"' not in realtime


# ---------------------------------------------------------------------------
# Rate-limit circuits are only cleared by a real generation
# ---------------------------------------------------------------------------


def test_successful_generic_probe_cannot_clear_a_rate_limit_circuit() -> None:
    """A cheap liveness call is not proof the generation quota recovered.

    `health_check()` lists models; a rate-limited provider answers that call
    happily while still refusing completions. Letting it close the circuit
    would send the whole backlog straight back into the rate limit.
    """

    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=5,
        rate_limit_cooldown_seconds=120,
        clock=clock,
    )

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderRateLimitError("429"),
    )

    applied = tracker.record_probe_result(
        ProviderName.OPENAI,
        reachable=True,
    )

    assert applied is False

    decision = tracker.acquire(ProviderName.OPENAI)
    assert decision.allowed is False
    assert decision.reason == "circuit_open:rate_limit"
    assert decision.cooldown_remaining_seconds == 120

    summary = tracker.safe_summary()["providers"]["openai"]
    assert summary["state"] == "open"
    assert summary["last_failure_kind"] == "rate_limit"


def test_failed_generic_probe_cannot_shorten_a_rate_limit_cooldown() -> None:
    """A failed probe must not downgrade rate_limit to the shorter transient."""

    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=5,
        rate_limit_cooldown_seconds=120,
        clock=clock,
    )

    tracker.record_failure(
        ProviderName.GROQ,
        ProviderRateLimitError("429"),
    )

    applied = tracker.record_probe_result(
        ProviderName.GROQ,
        reachable=False,
    )

    assert applied is False

    summary = tracker.safe_summary()["providers"]["groq"]
    assert summary["last_failure_kind"] == "rate_limit"
    assert summary["cooldown_remaining_seconds"] == 120
    assert summary["consecutive_failures"] == 1

    # Well past the transient cooldown, still inside the rate-limit one.
    clock.advance(5)
    assert tracker.acquire(ProviderName.GROQ).allowed is False


def test_rate_limit_recovery_is_proven_by_the_routed_generation() -> None:
    """After the cooldown, the HALF_OPEN generation attempt decides."""

    clock = FakeClock()
    tracker = ProviderHealthTracker(
        failure_threshold=1,
        transient_cooldown_seconds=5,
        rate_limit_cooldown_seconds=120,
        clock=clock,
    )
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    primary = FakeProvider(
        name="openai",
        outcomes=[
            ProviderRateLimitError("429"),
            "primary-recovered",
        ],
    )
    fallback = FakeProvider(name="groq", outcomes=["fallback-1"])

    registry.register(ProviderName.OPENAI, primary)
    registry.register(ProviderName.GROQ, fallback)

    router = ModelRouter(
        configuration=config,
        registry=registry,
        cloud_budget=FakeBudget(),
        health_tracker=tracker,
    )

    first = asyncio.run(router.route("one", role="reasoning"))
    assert first.provider == "groq"

    # Probes during the cooldown change nothing, in either direction.
    assert asyncio.run(registry.health_check(ProviderName.OPENAI)) is True
    assert tracker.acquire(ProviderName.OPENAI).allowed is False

    clock.advance(120)

    second = asyncio.run(router.route("two", role="reasoning"))
    assert second.provider == "openai"
    assert primary.generate_calls == 2

    summary = tracker.safe_summary()["providers"]["openai"]
    assert summary["state"] == "closed"
    assert summary["last_failure_kind"] is None


def test_registry_probe_still_governs_non_rate_limit_circuits() -> None:
    """The guard is scoped to rate limits and must not disable probing."""

    tracker = ProviderHealthTracker(failure_threshold=1)
    config = _configuration()
    registry = ProviderRegistry(config, health_tracker=tracker)

    provider = FakeProvider(name="openai", outcomes=["ok"])
    provider.health_reachable = False
    registry.register(ProviderName.OPENAI, provider)

    assert asyncio.run(registry.health_check(ProviderName.OPENAI)) is False
    assert tracker.acquire(ProviderName.OPENAI).allowed is False

    provider.health_reachable = True
    assert asyncio.run(registry.health_check(ProviderName.OPENAI)) is True
    assert tracker.acquire(ProviderName.OPENAI).allowed is True


def test_unconfigured_probe_is_recorded_even_during_a_rate_limit() -> None:
    """A missing key is a configuration fact, not a quota question."""

    tracker = ProviderHealthTracker(failure_threshold=1)

    tracker.record_failure(
        ProviderName.OPENAI,
        ProviderRateLimitError("429"),
    )

    applied = tracker.record_probe_result(
        ProviderName.OPENAI,
        reachable=False,
        configured=False,
    )

    assert applied is True
    summary = tracker.safe_summary()["providers"]["openai"]
    assert summary["last_failure_kind"] == "not_configured"


# ---------------------------------------------------------------------------
# Real LiveKit RealtimeModelError wrapper shape
# ---------------------------------------------------------------------------

RAW_MESSAGE_MARKER = "sensitive-realtime-marker-must-not-leak"


class WrappedProviderError(Exception):
    """Stand-in for the provider exception LiveKit puts inside its wrapper."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _realtime_model_error(
    *,
    status_code: int | None,
    recoverable: bool,
    message: str = RAW_MESSAGE_MARKER,
) -> livekit_llm.RealtimeModelError:
    """Build the REAL LiveKit wrapper, not a hand-rolled look-alike."""

    return livekit_llm.RealtimeModelError(
        timestamp=1234.0,
        label="google.realtime",
        error=WrappedProviderError(message, status_code=status_code),
        recoverable=recoverable,
    )


class _FakeLocalParticipant:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def send_text(self, text: str, *, topic: str) -> None:
        self.published.append((topic, json.loads(text)))


class _FakeRoom:
    def __init__(self) -> None:
        self.local_participant = _FakeLocalParticipant()


class _FakeJobContext:
    def __init__(self) -> None:
        self.room = _FakeRoom()


class _FakeSession:
    """Minimal stand-in for AgentSession's event registration."""

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, name: str):
        def decorate(function):
            self.handlers.setdefault(name, []).append(function)
            return function

        return decorate

    def emit(self, name: str, event: object) -> None:
        for function in self.handlers.get(name, ()):
            function(event)


def _drive_realtime_error(error: object) -> tuple[object, list, str]:
    """Run agent.py's real observer against a real-shaped error event."""

    import agent as agent_module
    from nova_runtime import NovaRuntime

    ctx = _FakeJobContext()
    session = _FakeSession()
    runtime = NovaRuntime()
    realtime_model = object()
    selection = SimpleNamespace(
        provider=SimpleNamespace(value="gemini"),
    )

    async def scenario():
        (
            tasks,
            component,
        ) = agent_module._install_realtime_provider_health(
            ctx,
            session,
            runtime,
            selection,
            realtime_model,
        )

        session.emit(
            "error",
            SimpleNamespace(error=error, source=realtime_model),
        )

        pending = list(tasks)
        if pending:
            await asyncio.gather(*pending)

        health = runtime.health.get(component)
        await runtime.shutdown()
        return health, ctx.room.local_participant.published, component

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_code", "expected_kind"),
    [
        (429, "rate_limit"),
        (503, "unavailable"),
        (401, "authentication"),
        (403, "authentication"),
        (400, "request"),
    ],
)
def test_wrapper_is_unwrapped_before_classification(
    status_code: int,
    expected_kind: str,
) -> None:
    """The status code lives on the inner exception, not on the wrapper.

    Classifying the wrapper reports `unknown` for every one of these, because
    `RealtimeModelError` carries no status_code.
    """

    wrapper = _realtime_model_error(
        status_code=status_code,
        recoverable=True,
    )

    health, published, _ = _drive_realtime_error(wrapper)

    assert health.detail == f"{expected_kind}:WrappedProviderError"

    topic, payload = published[0]
    assert topic == "nova.provider-status"
    assert payload["failure_kind"] == expected_kind
    assert payload["detail"] == "WrappedProviderError"
    assert payload["provider"] == "gemini"
    assert payload["lane"] == "realtime"


def test_wrapper_recoverable_flag_drives_health_state() -> None:
    """`recoverable` is LiveKit's judgment and lives only on the wrapper."""

    recoverable_health, recoverable_published, _ = _drive_realtime_error(
        _realtime_model_error(status_code=503, recoverable=True)
    )
    assert recoverable_health.state is HealthState.DEGRADED
    assert recoverable_published[0][1]["recoverable"] is True

    fatal_health, fatal_published, _ = _drive_realtime_error(
        _realtime_model_error(status_code=401, recoverable=False)
    )
    assert fatal_health.state is HealthState.FAILED
    assert fatal_published[0][1]["recoverable"] is False


def test_realtime_health_never_publishes_the_raw_provider_message() -> None:
    """`str(RealtimeModelError)` embeds the inner message. Never store it."""

    wrapper = _realtime_model_error(status_code=429, recoverable=True)

    # Guard the premise: the wrapper really does expose the raw text.
    assert RAW_MESSAGE_MARKER in str(wrapper)

    health, published, _ = _drive_realtime_error(wrapper)

    assert RAW_MESSAGE_MARKER not in health.detail
    assert RAW_MESSAGE_MARKER not in repr(published)
    assert "RealtimeModelError" not in health.detail


def test_realtime_health_component_is_scoped_to_the_provider() -> None:
    health, _, component = _drive_realtime_error(
        _realtime_model_error(status_code=503, recoverable=True)
    )

    assert component == "provider:gemini:realtime"
    assert health.name == component


def test_non_realtime_error_sources_are_ignored() -> None:
    """A tool or STT error is somebody else's health story."""

    import agent as agent_module
    from nova_runtime import NovaRuntime

    ctx = _FakeJobContext()
    session = _FakeSession()
    runtime = NovaRuntime()
    realtime_model = object()
    selection = SimpleNamespace(provider=SimpleNamespace(value="gemini"))

    async def scenario():
        _, component = agent_module._install_realtime_provider_health(
            ctx,
            session,
            runtime,
            selection,
            realtime_model,
        )

        session.emit(
            "error",
            SimpleNamespace(
                error=_realtime_model_error(
                    status_code=503,
                    recoverable=False,
                ),
                source=SimpleNamespace(),
            ),
        )

        health = runtime.health.get(component)
        await runtime.shutdown()
        return health, ctx.room.local_participant.published

    health, published = asyncio.run(scenario())

    assert health.state is HealthState.HEALTHY
    assert published == []


def test_unwrap_helper_handles_a_bare_exception_and_a_missing_inner() -> None:
    import agent as agent_module

    bare = WrappedProviderError("boom", status_code=503)
    provider_error, recoverable = agent_module._unwrap_realtime_error(bare)
    assert provider_error is bare
    assert recoverable is False

    empty = SimpleNamespace(error=None, recoverable=True)
    provider_error, recoverable = agent_module._unwrap_realtime_error(empty)
    assert provider_error is None
    assert recoverable is True

    assert classify_realtime_error(None) is RealtimeFailureKind.UNKNOWN


# ---------------------------------------------------------------------------
# Adapter classification consistency
# ---------------------------------------------------------------------------


def _api_status_error(status_code: int) -> APIStatusError:
    """Build a real openai.APIStatusError, the type the adapters catch."""

    request = httpx.Request("POST", "http://localhost/v1/chat/completions")
    response = httpx.Response(status_code, request=request)

    return APIStatusError(
        "upstream rejected the request",
        response=response,
        body=None,
    )


class _RaisingCompletions:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def create(self, **kwargs: object):
        _ = kwargs
        raise self._error


class _RaisingClient:
    """Stands in for AsyncOpenAI far enough to reach the except blocks.

    Both surfaces are stubbed on purpose: the OpenAI adapter calls
    `responses.create`, while Groq and Ollama use `chat.completions.create`.
    Stubbing only one lets an AttributeError fall into the generic
    `except Exception` and masquerade as a request-error result.
    """

    def __init__(self, error: BaseException) -> None:
        self.chat = SimpleNamespace(
            completions=_RaisingCompletions(error)
        )
        self.responses = _RaisingCompletions(error)

    def with_options(self, **kwargs: object) -> "_RaisingClient":
        _ = kwargs
        return self


def _adapter_for(name: ProviderName):
    configuration = _configuration().provider(name)

    if name is ProviderName.OPENAI:
        return OpenAIProvider(configuration)
    if name is ProviderName.GROQ:
        return GroqProvider(configuration)
    return OllamaProvider(configuration)


@pytest.mark.parametrize(
    "provider_name",
    [ProviderName.OPENAI, ProviderName.GROQ, ProviderName.OLLAMA],
)
@pytest.mark.parametrize(
    ("status_code", "expected_error", "expected_kind"),
    [
        (429, ProviderRateLimitError, ProviderFailureKind.RATE_LIMIT),
        (503, ProviderUnavailableError, ProviderFailureKind.UNAVAILABLE),
        (408, ProviderUnavailableError, ProviderFailureKind.UNAVAILABLE),
        (400, ProviderRequestError, ProviderFailureKind.REQUEST),
    ],
)
def test_every_adapter_maps_status_codes_the_same_way(
    provider_name: ProviderName,
    status_code: int,
    expected_error: type[BaseException],
    expected_kind: ProviderFailureKind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three adapters must agree, or the circuit breaker misbehaves.

    Ollama shipped without the 429 branch, so a rate-limited
    Ollama-compatible endpoint was reported as a request error and never
    opened a circuit.
    """

    provider = _adapter_for(provider_name)

    monkeypatch.setattr(
        provider,
        "_get_client",
        lambda: _RaisingClient(_api_status_error(status_code)),
    )

    with pytest.raises(expected_error) as captured:
        asyncio.run(provider.generate("hello"))

    assert classify_provider_error(captured.value) is expected_kind

    # The raw upstream message must not be re-raised verbatim.
    assert "upstream rejected the request" not in str(captured.value)


def test_ollama_rate_limit_error_is_classified_as_a_rate_limit() -> None:
    assert classify_provider_error(
        ProviderRateLimitError("Ollama is currently rate-limited.")
    ) is ProviderFailureKind.RATE_LIMIT

    # And it is still an unavailable-error subtype for existing callers.
    assert isinstance(
        ProviderRateLimitError("x"),
        ProviderUnavailableError,
    )
