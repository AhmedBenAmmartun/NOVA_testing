"""Provider circuit-breaker and health state for NOVA text providers.

Provider Resilience P1 gives NOVA a memory of provider failures that survives
one request. Without it, every routed prompt re-attacked a provider that had
just failed, paying full latency and cloud-budget allowance for a request that
was already known to be doomed.

This tracker covers the text lane owned by nova_core.router. The Gemini native
realtime lane is classified separately in nova_core.realtime and reported
through the existing NovaRuntime health registry -- a realtime provider failure
is one component being degraded, not NOVA being dead.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from providers.base import (
    ProviderError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderUnavailableError,
)

from .configuration import ProviderName, parse_provider_name


class ProviderCircuitState(StrEnum):
    """Circuit state for one provider."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderFailureKind(StrEnum):
    """Safe failure categories used for routing decisions."""

    NOT_CONFIGURED = "not_configured"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    REQUEST = "request"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class ProviderAttemptDecision:
    """Whether a request may attempt one provider."""

    allowed: bool
    state: ProviderCircuitState
    reason: str
    cooldown_remaining_seconds: float = 0.0

    def safe_summary(self) -> dict[str, object]:
        """Return the decision without private data."""

        return {
            "allowed": self.allowed,
            "state": self.state.value,
            "reason": self.reason,
            "cooldown_remaining_seconds": round(
                max(0.0, self.cooldown_remaining_seconds),
                3,
            ),
        }


@dataclass(slots=True)
class _ProviderHealthRecord:
    """Process-local health state for one provider.

    Only operational metadata lives here. Prompts, responses, credentials, and
    raw provider error messages must never be stored.
    """

    state: ProviderCircuitState = ProviderCircuitState.CLOSED
    consecutive_failures: int = 0
    last_failure_kind: ProviderFailureKind | None = None
    last_error_type: str | None = None
    cooldown_until: float | None = None
    half_open_probe_in_flight: bool = False
    last_success_at: float | None = None
    last_failure_at: float | None = None


def classify_provider_error(error: BaseException) -> ProviderFailureKind:
    """Classify a standardized provider error without exposing its message.

    Order matters: ProviderRateLimitError is a ProviderUnavailableError, and
    ProviderNotConfiguredError/ProviderRequestError are both ProviderError.
    """

    if isinstance(error, ProviderNotConfiguredError):
        return ProviderFailureKind.NOT_CONFIGURED

    if isinstance(error, ProviderRateLimitError):
        return ProviderFailureKind.RATE_LIMIT

    if isinstance(error, ProviderUnavailableError):
        return ProviderFailureKind.UNAVAILABLE

    if isinstance(error, ProviderRequestError):
        return ProviderFailureKind.REQUEST

    if isinstance(error, ProviderError):
        return ProviderFailureKind.UNEXPECTED

    return ProviderFailureKind.UNEXPECTED


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    cleaned = raw.strip().lower()

    if cleaned in {"1", "true", "yes", "on", "enabled"}:
        return True

    if cleaned in {"0", "false", "no", "off", "disabled"}:
        return False

    return default


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        value = int(raw)
    except ValueError:
        return default

    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        value = float(raw)
    except ValueError:
        return default

    return max(minimum, value)


class ProviderHealthTracker:
    """Remember provider failures and prevent retry storms.

    The tracker is intentionally in-memory and process-local. It never stores
    prompts, responses, credentials, or raw provider error messages -- only a
    failure category and the exception class name.

    ProviderRegistry and ModelRouter share exactly one instance through the
    default factory path so an explicit health probe and a routed request see
    the same circuit state.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        failure_threshold: int = 2,
        transient_cooldown_seconds: float = 30.0,
        rate_limit_cooldown_seconds: float = 120.0,
        not_configured_cooldown_seconds: float = 300.0,
        unexpected_cooldown_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(
                "failure_threshold must be at least 1"
            )

        self.enabled = enabled
        self.failure_threshold = failure_threshold
        self.transient_cooldown_seconds = max(
            0.0,
            transient_cooldown_seconds,
        )
        self.rate_limit_cooldown_seconds = max(
            0.0,
            rate_limit_cooldown_seconds,
        )
        self.not_configured_cooldown_seconds = max(
            0.0,
            not_configured_cooldown_seconds,
        )
        self.unexpected_cooldown_seconds = max(
            0.0,
            unexpected_cooldown_seconds,
        )

        # Monotonic by default: a wall-clock jump must not silently extend or
        # cancel a cooldown. Tests inject a fake clock instead of sleeping.
        self._clock = (
            clock
            if clock is not None
            else time.monotonic
        )
        self._records: dict[
            ProviderName,
            _ProviderHealthRecord,
        ] = {}
        self._lock = threading.RLock()

    def _name(
        self,
        provider: ProviderName | str,
    ) -> ProviderName:
        return parse_provider_name(provider)

    def _record(
        self,
        provider: ProviderName,
    ) -> _ProviderHealthRecord:
        return self._records.setdefault(
            provider,
            _ProviderHealthRecord(),
        )

    def acquire(
        self,
        provider: ProviderName | str,
    ) -> ProviderAttemptDecision:
        """Reserve permission to attempt one provider.

        CLOSED circuits allow normal concurrency. Once an OPEN cooldown
        expires, exactly one HALF_OPEN probe is admitted until it succeeds or
        fails -- a recovering provider gets one careful request, not the whole
        backlog at once.
        """

        name = self._name(provider)

        if not self.enabled:
            return ProviderAttemptDecision(
                allowed=True,
                state=ProviderCircuitState.CLOSED,
                reason="circuit_breaker_disabled",
            )

        with self._lock:
            now = self._clock()
            record = self._record(name)

            if record.state is ProviderCircuitState.CLOSED:
                return ProviderAttemptDecision(
                    allowed=True,
                    state=record.state,
                    reason="closed",
                )

            if record.state is ProviderCircuitState.OPEN:
                cooldown_until = (
                    record.cooldown_until
                    if record.cooldown_until is not None
                    else now
                )
                remaining = max(0.0, cooldown_until - now)

                if remaining > 0:
                    failure = (
                        record.last_failure_kind.value
                        if record.last_failure_kind is not None
                        else ProviderFailureKind.UNEXPECTED.value
                    )

                    return ProviderAttemptDecision(
                        allowed=False,
                        state=record.state,
                        reason=f"circuit_open:{failure}",
                        cooldown_remaining_seconds=remaining,
                    )

                record.state = ProviderCircuitState.HALF_OPEN
                record.half_open_probe_in_flight = True

                return ProviderAttemptDecision(
                    allowed=True,
                    state=record.state,
                    reason="half_open_probe",
                )

            if record.half_open_probe_in_flight:
                return ProviderAttemptDecision(
                    allowed=False,
                    state=record.state,
                    reason="half_open_probe_in_flight",
                )

            record.half_open_probe_in_flight = True

            return ProviderAttemptDecision(
                allowed=True,
                state=record.state,
                reason="half_open_probe",
            )

    def release_attempt(
        self,
        provider: ProviderName | str,
    ) -> None:
        """Release a HALF_OPEN attempt that never reached the provider.

        The cloud budget can refuse a request after the circuit admitted it.
        Without this, a single probe slot would stay reserved forever and the
        provider could never recover.
        """

        name = self._name(provider)

        with self._lock:
            record = self._records.get(name)

            if (
                record is not None
                and record.state is ProviderCircuitState.HALF_OPEN
            ):
                record.half_open_probe_in_flight = False

    def record_success(
        self,
        provider: ProviderName | str,
    ) -> None:
        """Close the circuit after a successful response or probe."""

        name = self._name(provider)

        with self._lock:
            now = self._clock()
            record = self._record(name)

            record.state = ProviderCircuitState.CLOSED
            record.consecutive_failures = 0
            record.last_failure_kind = None
            record.last_error_type = None
            record.cooldown_until = None
            record.half_open_probe_in_flight = False
            record.last_success_at = now

    def record_failure(
        self,
        provider: ProviderName | str,
        error: BaseException,
    ) -> ProviderFailureKind:
        """Classify and record one provider failure."""

        failure_kind = classify_provider_error(error)

        self.record_failure_kind(
            provider,
            failure_kind,
            error_type=type(error).__name__,
        )

        return failure_kind

    def record_failure_kind(
        self,
        provider: ProviderName | str,
        failure_kind: ProviderFailureKind,
        *,
        error_type: str | None = None,
    ) -> None:
        """Record one already-classified provider failure."""

        name = self._name(provider)

        if not self.enabled:
            return

        with self._lock:
            now = self._clock()
            record = self._record(name)
            was_half_open = (
                record.state is ProviderCircuitState.HALF_OPEN
            )

            record.last_failure_kind = failure_kind
            record.last_error_type = (
                error_type[:120]
                if isinstance(error_type, str) and error_type
                else None
            )
            record.last_failure_at = now
            record.half_open_probe_in_flight = False

            # A request-specific rejection proves the provider is reachable.
            # Poisoning its health here would take a healthy provider offline
            # because one prompt was malformed or too long.
            if failure_kind is ProviderFailureKind.REQUEST:
                record.state = ProviderCircuitState.CLOSED
                record.consecutive_failures = 0
                record.cooldown_until = None
                return

            if failure_kind is ProviderFailureKind.NOT_CONFIGURED:
                record.consecutive_failures += 1
                self._open(
                    record,
                    now,
                    self.not_configured_cooldown_seconds,
                )
                return

            # Rate limiting is not "try again immediately"; it is the provider
            # telling NOVA to back off, so it opens at once and stays open
            # longer than an ordinary transient failure.
            if failure_kind is ProviderFailureKind.RATE_LIMIT:
                record.consecutive_failures += 1
                self._open(
                    record,
                    now,
                    self.rate_limit_cooldown_seconds,
                )
                return

            record.consecutive_failures += 1

            if (
                was_half_open
                or record.consecutive_failures >= self.failure_threshold
            ):
                cooldown = (
                    self.transient_cooldown_seconds
                    if failure_kind is ProviderFailureKind.UNAVAILABLE
                    else self.unexpected_cooldown_seconds
                )
                self._open(record, now, cooldown)
                return

            record.state = ProviderCircuitState.CLOSED
            record.cooldown_until = None

    def _open(
        self,
        record: _ProviderHealthRecord,
        now: float,
        cooldown_seconds: float,
    ) -> None:
        record.state = ProviderCircuitState.OPEN
        record.cooldown_until = now + max(0.0, cooldown_seconds)
        record.half_open_probe_in_flight = False

    def rate_limit_circuit_is_authoritative(
        self,
        provider: ProviderName | str,
    ) -> bool:
        """Return whether only a real generation may clear this circuit.

        A rate limit is a statement about the provider's *generation* quota.
        A generic reachability probe (listing models, pinging a base URL) is a
        different, far cheaper call that a rate-limited provider will happily
        answer -- so it proves nothing either way and must not be allowed to
        clear or shorten the cooldown.
        """

        name = self._name(provider)

        with self._lock:
            record = self._records.get(name)

            if record is None:
                return False

            return (
                record.last_failure_kind is ProviderFailureKind.RATE_LIMIT
                and record.state
                in (
                    ProviderCircuitState.OPEN,
                    ProviderCircuitState.HALF_OPEN,
                )
            )

    def record_probe_result(
        self,
        provider: ProviderName | str,
        *,
        reachable: bool,
        configured: bool = True,
    ) -> bool:
        """Feed an explicit registry health probe into the same circuit.

        Returns whether the probe was actually applied. A generic probe is
        deliberately ignored while a rate-limit circuit is still standing:
        recovery from a rate limit is proven by the routed HALF_OPEN
        generation attempt after the cooldown, not by a cheap liveness check.
        """

        # A missing/placeholder key is not a generation-quota question, so a
        # configuration failure is still allowed to speak.
        if not configured:
            self.record_failure_kind(
                provider,
                ProviderFailureKind.NOT_CONFIGURED,
                error_type="NotConfigured",
            )
            return True

        if self.rate_limit_circuit_is_authoritative(provider):
            return False

        if reachable:
            self.record_success(provider)
            return True

        self.record_failure_kind(
            provider,
            ProviderFailureKind.UNAVAILABLE,
            error_type="HealthCheckFailed",
        )
        return True

    def safe_summary(self) -> dict[str, object]:
        """Return provider health without prompts, responses, or raw errors."""

        with self._lock:
            now = self._clock()
            providers: dict[str, object] = {}

            for provider, record in sorted(
                self._records.items(),
                key=lambda item: item[0].value,
            ):
                remaining = 0.0

                if record.cooldown_until is not None:
                    remaining = max(
                        0.0,
                        record.cooldown_until - now,
                    )

                providers[provider.value] = {
                    "state": record.state.value,
                    "consecutive_failures": (
                        record.consecutive_failures
                    ),
                    "last_failure_kind": (
                        record.last_failure_kind.value
                        if record.last_failure_kind is not None
                        else None
                    ),
                    "last_error_type": record.last_error_type,
                    "cooldown_remaining_seconds": round(
                        remaining,
                        3,
                    ),
                    "half_open_probe_in_flight": (
                        record.half_open_probe_in_flight
                    ),
                    "has_success": (
                        record.last_success_at is not None
                    ),
                    "has_failure": (
                        record.last_failure_at is not None
                    ),
                }

            return {
                "enabled": self.enabled,
                "failure_threshold": self.failure_threshold,
                "providers": providers,
            }


def create_provider_health_tracker() -> ProviderHealthTracker:
    """Create the configured P1 provider-health tracker.

    Every value here is operational tuning. None of it is a secret, so the
    defaults are safe to publish in .env.example.
    """

    return ProviderHealthTracker(
        enabled=_env_bool(
            "NOVA_PROVIDER_CIRCUIT_BREAKER_ENABLED",
            True,
        ),
        failure_threshold=_env_int(
            "NOVA_PROVIDER_FAILURE_THRESHOLD",
            2,
        ),
        transient_cooldown_seconds=_env_float(
            "NOVA_PROVIDER_TRANSIENT_COOLDOWN_SECONDS",
            30.0,
        ),
        rate_limit_cooldown_seconds=_env_float(
            "NOVA_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS",
            120.0,
        ),
        not_configured_cooldown_seconds=_env_float(
            "NOVA_PROVIDER_CONFIGURATION_COOLDOWN_SECONDS",
            300.0,
        ),
        unexpected_cooldown_seconds=_env_float(
            "NOVA_PROVIDER_UNEXPECTED_COOLDOWN_SECONDS",
            30.0,
        ),
    )
