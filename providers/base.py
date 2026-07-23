"""Shared interfaces and errors for NOVA model providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(RuntimeError):
    """Base error raised by a NOVA model provider."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when a provider is missing required configuration."""


class ProviderUnavailableError(ProviderError):
    """Raised when a configured provider cannot currently be reached."""


class ProviderRequestError(ProviderError):
    """Raised when a provider rejects or fails a generation request."""


@dataclass(slots=True)
class ProviderResponse:
    """Standard response returned by every NOVA model provider."""

    text: str
    provider: str
    model: str
    used_fallback: bool = False
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class ModelProvider(ABC):
    """
    Base interface implemented by every NOVA model provider.

    The router should interact with providers through this interface
    instead of depending directly on OpenAI, Groq, or Ollama code.
    """

    name: str
    model: str
    is_local: bool = False

    def __init__(
        self,
        *,
        model: str,
    ) -> None:
        self.model = model

    @property
    @abstractmethod
    def configured(self) -> bool:
        """
        Return True when this provider has enough configuration to run.

        Cloud providers usually require an API key.
        Local providers may require a running local service instead.
        """

        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Check whether the provider is currently reachable.

        This should return False instead of crashing during normal
        availability checks.
        """

        raise NotImplementedError

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        """
        Generate one text response.

        Every provider adapter must convert its native result into
        ProviderResponse so the NOVA router receives one common format.
        """

        raise NotImplementedError

    def require_configured(self) -> None:
        """Raise a clear error when the provider is not configured."""

        if not self.configured:
            raise ProviderNotConfiguredError(
                f"The {self.name} provider is not configured."
            )

    def describe(self) -> dict[str, object]:
        """Return safe provider metadata for status displays and logs."""

        return {
            "name": self.name,
            "model": self.model,
            "configured": self.configured,
            "is_local": self.is_local,
        }