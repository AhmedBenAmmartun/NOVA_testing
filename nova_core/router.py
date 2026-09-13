"""Central model routing and fallback logic for NOVA."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from providers import (
    ModelProvider,
    ProviderError,
    ProviderResponse,
)

from .cloud_budget import (
    CloudUsageBudget,
    get_cloud_usage_budget,
)
from .configuration import (
    NovaConfiguration,
    ProviderName,
    load_configuration,
    parse_provider_name,
)
from .provider_health import (
    ProviderFailureKind,
    ProviderHealthTracker,
    create_provider_health_tracker,
)
from .provider_registry import (
    ProviderRegistry,
    create_provider_registry,
)


logger = logging.getLogger(__name__)


class RouterError(RuntimeError):
    """Base error raised by NOVA's model router."""


class NoProviderAvailableError(RouterError):
    """Raised when no provider can complete a request."""


@dataclass(frozen=True, slots=True)
class RoutingAttempt:
    """Safe information about one provider attempt."""

    provider: ProviderName
    succeeded: bool
    reason: str | None = None

    def safe_summary(self) -> dict[str, Any]:
        """Return attempt information without private data."""

        return {
            "provider": self.provider.value,
            "succeeded": self.succeeded,
            "reason": self.reason,
        }


class ModelRouter:
    """
    Route specialist requests to configured model providers.

    NOVA tries the selected primary provider first. If the provider
    fails, is unavailable, or exceeds the local cloud budget, NOVA
    attempts the configured fallback providers.
    """

    def __init__(
        self,
        configuration: NovaConfiguration,
        registry: ProviderRegistry,
        cloud_budget: CloudUsageBudget | None = None,
        health_tracker: ProviderHealthTracker | None = None,
    ) -> None:
        self.configuration = configuration
        self.registry = registry

        # Default to the registry's tracker rather than building a second one:
        # the router and the registry must agree about which providers are
        # currently unhealthy.
        self.provider_health = (
            health_tracker
            if health_tracker is not None
            else registry.health_tracker
        )
        self.cloud_budget = (
            cloud_budget
            if cloud_budget is not None
            else get_cloud_usage_budget()
        )

    def _primary_provider_for_role(
        self,
        role: str,
        preferred_provider: ProviderName | str | None,
        *,
        local_only: bool,
    ) -> ProviderName:
        """Determine the primary provider for one request."""

        if local_only:
            return self.configuration.private_provider

        if preferred_provider is not None:
            return parse_provider_name(
                preferred_provider
            )

        return self.configuration.provider_for_role(
            role
        ).name

    def _candidate_providers(
        self,
        role: str,
        preferred_provider: ProviderName | str | None,
        *,
        allow_fallback: bool,
        local_only: bool,
    ) -> tuple[
        ProviderName,
        tuple[ProviderName, ...],
    ]:
        """Build the ordered provider candidate list."""

        primary_provider = self._primary_provider_for_role(
            role,
            preferred_provider,
            local_only=local_only,
        )

        candidates: list[ProviderName] = [
            primary_provider
        ]

        fallback_allowed = (
            allow_fallback
            and self.configuration.fallback_enabled
        )

        if fallback_allowed:
            candidates.extend(
                self.configuration.fallback_order
            )

        unique_candidates: list[ProviderName] = []

        for provider_name in candidates:
            if provider_name in unique_candidates:
                continue

            if local_only:
                provider_configuration = (
                    self.configuration.provider(
                        provider_name
                    )
                )

                if not provider_configuration.is_local:
                    continue

            unique_candidates.append(
                provider_name
            )

        return (
            primary_provider,
            tuple(unique_candidates),
        )

    def _release_cloud_budget(
        self,
        provider: ModelProvider,
        provider_name: ProviderName,
    ) -> None:
        """
        Give back an allowance reserved for a call that never answered.

        The allowance is reserved before generate() runs so the daily
        cap stays a real ceiling when requests overlap. The price of
        reserving first is that a failed call must hand its
        reservation back. Class Intelligence pays that price twice
        over: it walks its cloud tier one provider at a time, so a
        single question during an outage used to burn one unit per
        provider and still return nothing.
        """

        if provider.is_local:
            # Local providers never consumed the allowance, so there is
            # nothing to give back.
            return

        try:
            self.cloud_budget.release(
                provider_name.value,
            )

        except Exception:
            # A refund is best-effort bookkeeping. It must never turn a
            # handled provider failure into an unhandled routing crash.
            logger.exception(
                "Could not release cloud budget: provider=%s",
                provider_name.value,
            )

    async def route(
        self,
        prompt: str,
        *,
        role: str = "reasoning",
        preferred_provider: ProviderName | str | None = None,
        allow_fallback: bool = True,
        local_only: bool = False,
        system_prompt: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ProviderResponse:
        """
        Route one prompt through the best available provider.

        Setting local_only=True guarantees that the prompt will not
        be sent to a cloud provider.
        """

        cleaned_prompt = prompt.strip()

        if not cleaned_prompt:
            raise RouterError(
                "NOVA cannot route an empty prompt."
            )

        (
            primary_provider,
            candidates,
        ) = self._candidate_providers(
            role,
            preferred_provider,
            allow_fallback=allow_fallback,
            local_only=local_only,
        )

        attempts: list[RoutingAttempt] = []

        for provider_name in candidates:
            if not self.registry.is_registered(
                provider_name
            ):
                attempts.append(
                    RoutingAttempt(
                        provider=provider_name,
                        succeeded=False,
                        reason="not_registered",
                    )
                )
                continue

            provider = self.registry.get(
                provider_name
            )

            if not provider.configured:
                self.provider_health.record_failure_kind(
                    provider_name,
                    ProviderFailureKind.NOT_CONFIGURED,
                    error_type="NotConfigured",
                )
                attempts.append(
                    RoutingAttempt(
                        provider=provider_name,
                        succeeded=False,
                        reason="not_configured",
                    )
                )
                continue

            # Skip a provider NOVA already knows is failing instead of paying
            # its full timeout and cloud-budget allowance again.
            circuit = self.provider_health.acquire(
                provider_name
            )

            if not circuit.allowed:
                attempts.append(
                    RoutingAttempt(
                        provider=provider_name,
                        succeeded=False,
                        reason=circuit.reason,
                    )
                )
                continue

            # Only cloud providers consume the daily cloud allowance.
            if not provider.is_local:
                budget_decision = (
                    self.cloud_budget.try_consume(
                        provider_name.value
                    )
                )

                if not budget_decision.allowed:
                    logger.info(
                        "Cloud provider skipped because of budget: "
                        "provider=%s used=%s limit=%s reason=%s",
                        provider_name.value,
                        budget_decision.used,
                        budget_decision.limit,
                        budget_decision.reason,
                    )

                    # The circuit admitted this attempt but the budget
                    # refused it. Give the probe slot back or a half-open
                    # provider could never recover.
                    self.provider_health.release_attempt(
                        provider_name
                    )

                    attempts.append(
                        RoutingAttempt(
                            provider=provider_name,
                            succeeded=False,
                            reason=budget_decision.reason,
                        )
                    )
                    continue

            provider_configuration = (
                self.configuration.provider(
                    provider_name
                )
            )

            effective_timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else provider_configuration.timeout_seconds
            )

            try:
                response = await provider.generate(
                    cleaned_prompt,
                    system_prompt=system_prompt,
                    timeout_seconds=effective_timeout,
                )

            except ProviderError as error:
                failure_kind = self.provider_health.record_failure(
                    provider_name,
                    error,
                )

                logger.warning(
                    "NOVA provider failed: provider=%s error=%s kind=%s",
                    provider_name.value,
                    type(error).__name__,
                    failure_kind.value,
                )

                self._release_cloud_budget(
                    provider,
                    provider_name,
                )

                attempts.append(
                    RoutingAttempt(
                        provider=provider_name,
                        succeeded=False,
                        reason=type(error).__name__,
                    )
                )
                continue

            except Exception as error:
                self.provider_health.record_failure_kind(
                    provider_name,
                    ProviderFailureKind.UNEXPECTED,
                    error_type=type(error).__name__,
                )

                logger.exception(
                    "Unexpected provider failure: provider=%s",
                    provider_name.value,
                )

                self._release_cloud_budget(
                    provider,
                    provider_name,
                )

                attempts.append(
                    RoutingAttempt(
                        provider=provider_name,
                        succeeded=False,
                        reason=type(error).__name__,
                    )
                )
                continue

            self.provider_health.record_success(
                provider_name
            )

            attempts.append(
                RoutingAttempt(
                    provider=provider_name,
                    succeeded=True,
                )
            )

            metadata = dict(
                response.metadata
            )

            metadata.update(
                {
                    "requested_role": role,
                    "primary_provider": (
                        primary_provider.value
                    ),
                    "selected_provider": (
                        provider_name.value
                    ),
                    "attempts": [
                        attempt.safe_summary()
                        for attempt in attempts
                    ],
                    "cloud_budget": (
                        self.cloud_budget.status()
                    ),
                    "provider_health": (
                        self.provider_health.safe_summary()
                    ),
                }
            )

            return ProviderResponse(
                text=response.text,
                provider=response.provider,
                model=response.model,
                used_fallback=(
                    provider_name
                    != primary_provider
                ),
                metadata=metadata,
            )

        attempt_summary = ", ".join(
            (
                f"{attempt.provider.value}: "
                f"{attempt.reason or 'failed'}"
            )
            for attempt in attempts
        )

        if not attempt_summary:
            attempt_summary = (
                "no provider candidates were available"
            )

        raise NoProviderAvailableError(
            "NOVA could not find an available model provider. "
            f"Attempts: {attempt_summary}."
        )

    async def route_private(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        """Route a request only through a local provider."""

        return await self.route(
            prompt,
            role="private",
            local_only=True,
            allow_fallback=True,
            system_prompt=system_prompt,
        )

    def safe_summary(self) -> dict[str, Any]:
        """Return router status without exposing secrets."""

        return {
            "profile": self.configuration.profile.value,
            "roles": {
                "conversation": (
                    self.configuration
                    .conversation_provider
                    .value
                ),
                "reasoning": (
                    self.configuration
                    .reasoning_provider
                    .value
                ),
                "coding": (
                    self.configuration
                    .coding_provider
                    .value
                ),
                "private": (
                    self.configuration
                    .private_provider
                    .value
                ),
            },
            "fallback_enabled": (
                self.configuration.fallback_enabled
            ),
            "fallback_order": [
                provider.value
                for provider
                in self.configuration.fallback_order
            ],
            "cloud_budget": (
                self.cloud_budget.status()
            ),
            "provider_health": (
                self.provider_health.safe_summary()
            ),
            "registry": (
                self.registry.safe_summary()
            ),
        }


def create_model_router(
    configuration: NovaConfiguration | None = None,
    registry: ProviderRegistry | None = None,
    cloud_budget: CloudUsageBudget | None = None,
    health_tracker: ProviderHealthTracker | None = None,
) -> ModelRouter:
    """Create NOVA's default specialist model router."""

    active_configuration = (
        configuration
        if configuration is not None
        else load_configuration()
    )

    # ProviderHealthTracker
    #   |
    #   +---- ProviderRegistry
    #   |
    #   +---- ModelRouter
    #
    # Resolve the tracker once, before the registry is built, so the default
    # factory path can never end up with two independent trackers.
    active_health_tracker = (
        health_tracker
        if health_tracker is not None
        else (
            registry.health_tracker
            if registry is not None
            else create_provider_health_tracker()
        )
    )

    active_registry = (
        registry
        if registry is not None
        else create_provider_registry(
            active_configuration,
            health_tracker=active_health_tracker,
        )
    )

    return ModelRouter(
        configuration=active_configuration,
        registry=active_registry,
        cloud_budget=cloud_budget,
        health_tracker=active_health_tracker,
    )