"""Central registry for NOVA model providers."""

from __future__ import annotations

import asyncio
from typing import Any

from providers import (
    GroqProvider,
    ModelProvider,
    OllamaProvider,
    OpenAIProvider,
)

from .configuration import (
    NovaConfiguration,
    ProviderName,
    load_configuration,
    parse_provider_name,
)
from .provider_health import (
    ProviderHealthTracker,
    create_provider_health_tracker,
)


class ProviderRegistryError(RuntimeError):
    """Base error raised by NOVA's provider registry."""


class ProviderNotRegisteredError(ProviderRegistryError):
    """Raised when NOVA requests an unregistered provider."""


class ProviderRegistry:
    """
    Store and manage NOVA's configured model providers.

    Gemini Live is currently handled directly by the realtime voice
    session, so this registry initially manages the specialist text
    providers: OpenAI and Ollama.
    """

    def __init__(
        self,
        configuration: NovaConfiguration,
        health_tracker: ProviderHealthTracker | None = None,
    ) -> None:
        self.configuration = configuration

        # One tracker, shared with ModelRouter through the default factory
        # path. Two independent trackers would mean a provider marked
        # unhealthy by a probe still looked healthy to routed traffic.
        self.health_tracker = (
            health_tracker
            if health_tracker is not None
            else create_provider_health_tracker()
        )

        self._providers: dict[
            ProviderName,
            ModelProvider,
        ] = {}

    def register(
        self,
        name: ProviderName | str,
        provider: ModelProvider,
        *,
        replace: bool = False,
    ) -> None:
        """Register one provider adapter."""

        provider_name = parse_provider_name(name)

        if (
            provider_name in self._providers
            and not replace
        ):
            raise ProviderRegistryError(
                f"Provider '{provider_name.value}' "
                "is already registered."
            )

        expected_name = provider_name.value

        if provider.name != expected_name:
            raise ProviderRegistryError(
                "Provider name mismatch: registry key "
                f"'{expected_name}' does not match adapter "
                f"'{provider.name}'."
            )

        self._providers[provider_name] = provider

    def unregister(
        self,
        name: ProviderName | str,
    ) -> bool:
        """Remove a provider from the registry."""

        provider_name = parse_provider_name(name)

        return (
            self._providers.pop(
                provider_name,
                None,
            )
            is not None
        )

    def is_registered(
        self,
        name: ProviderName | str,
    ) -> bool:
        """Return whether a provider adapter is registered."""

        provider_name = parse_provider_name(name)

        return provider_name in self._providers

    def get(
        self,
        name: ProviderName | str,
    ) -> ModelProvider:
        """Return one registered provider."""

        provider_name = parse_provider_name(name)

        try:
            return self._providers[provider_name]

        except KeyError as error:
            raise ProviderNotRegisteredError(
                f"Provider '{provider_name.value}' "
                "is not registered."
            ) from error

    def get_for_role(
        self,
        role: str,
    ) -> ModelProvider:
        """Return the registered provider assigned to a role."""

        provider_configuration = (
            self.configuration.provider_for_role(role)
        )

        return self.get(
            provider_configuration.name
        )

    def registered_names(
        self,
    ) -> tuple[ProviderName, ...]:
        """Return registered provider names."""

        return tuple(self._providers)

    def configured_providers(
        self,
    ) -> tuple[ModelProvider, ...]:
        """Return registered providers with valid static configuration."""

        return tuple(
            provider
            for provider in self._providers.values()
            if provider.configured
        )

    def safe_summary(
        self,
    ) -> dict[str, Any]:
        """Return registry information without exposing secrets."""

        return {
            "registered": [
                name.value
                for name in self.registered_names()
            ],
            "providers": {
                name.value: provider.describe()
                for name, provider
                in self._providers.items()
            },
            "health": self.health_tracker.safe_summary(),
        }

    async def health_check(
        self,
        name: ProviderName | str,
    ) -> bool:
        """Check whether one provider is reachable."""

        provider = self.get(name)

        if not provider.configured:
            self.health_tracker.record_probe_result(
                name,
                reachable=False,
                configured=False,
            )
            return False

        try:
            reachable = await provider.health_check()

        except Exception:
            reachable = False

        self.health_tracker.record_probe_result(
            name,
            reachable=reachable,
            configured=True,
        )

        return reachable

    async def health_check_all(
        self,
    ) -> dict[str, dict[str, Any]]:
        """Check every registered provider concurrently."""

        providers = list(
            self._providers.items()
        )

        async def check_provider(
            name: ProviderName,
            provider: ModelProvider,
        ) -> tuple[str, dict[str, Any]]:
            if not provider.configured:
                self.health_tracker.record_probe_result(
                    name,
                    reachable=False,
                    configured=False,
                )
                return (
                    name.value,
                    {
                        "configured": False,
                        "reachable": False,
                        "model": provider.model,
                        "is_local": provider.is_local,
                    },
                )

            # Delegate so a bulk sweep records health exactly the same way a
            # single probe does, instead of quietly bypassing the tracker.
            reachable = await self.health_check(name)

            return (
                name.value,
                {
                    "configured": True,
                    "reachable": reachable,
                    "model": provider.model,
                    "is_local": provider.is_local,
                },
            )

        results = await asyncio.gather(
            *[
                check_provider(name, provider)
                for name, provider in providers
            ]
        )

        return dict(results)


def create_provider_registry(
    configuration: NovaConfiguration | None = None,
    health_tracker: ProviderHealthTracker | None = None,
) -> ProviderRegistry:
    """
    Create NOVA's default provider registry.

    Missing optional API keys do not prevent provider registration.
    The adapter will simply report configured=False.
    """

    active_configuration = (
        configuration
        if configuration is not None
        else load_configuration()
    )

    registry = ProviderRegistry(
        active_configuration,
        health_tracker=health_tracker,
    )

    openai_configuration = (
        active_configuration.provider(
            ProviderName.OPENAI
        )
    )

    groq_configuration = (
        active_configuration.provider(
            ProviderName.GROQ
        )
    )

    ollama_configuration = (
        active_configuration.provider(
            ProviderName.OLLAMA
        )
    )

    registry.register(
        ProviderName.OPENAI,
        OpenAIProvider(
            openai_configuration
        ),
    )

    registry.register(
        ProviderName.GROQ,
        GroqProvider(
            groq_configuration
        ),
    )

    registry.register(
        ProviderName.OLLAMA,
        OllamaProvider(
            ollama_configuration
        ),
    )

    return registry