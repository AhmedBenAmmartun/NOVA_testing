"""Safe runtime configuration for NOVA providers and operating profiles."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConfigurationError(ValueError):
    """Raised when NOVA receives invalid configuration."""


class NovaProfile(str, Enum):
    """Supported NOVA operating profiles."""

    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


class ProviderName(str, Enum):
    """AI providers understood by NOVA."""

    GEMINI = "gemini"
    OPENAI = "openai"
    GROQ = "groq"
    OLLAMA = "ollama"


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    """Safe configuration for one AI provider."""

    name: ProviderName
    model: str
    enabled: bool
    api_key_environment_variable: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 60.0
    max_output_tokens: int = 800
    is_local: bool = False

    @property
    def api_key_configured(self) -> bool:
        """
        Return whether the provider's API key appears configured.

        This never exposes or returns the key itself.
        """

        if self.api_key_environment_variable is None:
            return True

        value = os.getenv(
            self.api_key_environment_variable,
            "",
        ).strip()

        if not value:
            return False

        placeholders = {
            "replace_me",
            "your_key_here",
            "your-api-key",
            "your_api_key",
            "api-key-here",
        }

        return value.lower() not in placeholders

    @property
    def configured(self) -> bool:
        """
        Return whether static configuration is present.

        Local providers still need a runtime health check to confirm
        that their local service is actually running.
        """

        return (
            self.enabled
            and bool(self.model.strip())
            and self.api_key_configured
        )

    def safe_summary(self) -> dict[str, Any]:
        """Return provider information without exposing secrets."""

        return {
            "name": self.name.value,
            "model": self.model,
            "enabled": self.enabled,
            "configured": self.configured,
            "is_local": self.is_local,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_output_tokens": self.max_output_tokens,
            "api_key_variable": self.api_key_environment_variable,
            "api_key_configured": self.api_key_configured,
        }


@dataclass(frozen=True, slots=True)
class NovaConfiguration:
    """Complete NOVA runtime configuration."""

    profile: NovaProfile

    conversation_provider: ProviderName
    reasoning_provider: ProviderName
    coding_provider: ProviderName
    private_provider: ProviderName

    fallback_enabled: bool
    fallback_order: tuple[ProviderName, ...]

    providers: dict[
        ProviderName,
        ProviderConfiguration,
    ]

    def provider(
        self,
        name: ProviderName | str,
    ) -> ProviderConfiguration:
        """Return configuration for one provider."""

        provider_name = parse_provider_name(name)

        try:
            return self.providers[provider_name]

        except KeyError as error:
            raise ConfigurationError(
                "No configuration exists for provider "
                f"'{provider_name.value}'."
            ) from error

    def provider_for_role(
        self,
        role: str,
    ) -> ProviderConfiguration:
        """Return the provider selected for a NOVA role."""

        cleaned_role = (
            role
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

        provider_by_role: dict[str, ProviderName] = {
            "conversation": self.conversation_provider,
            "voice": self.conversation_provider,
            "reasoning": self.reasoning_provider,
            "coding": self.coding_provider,
            "private": self.private_provider,
            "local": self.private_provider,
        }

        provider_name = provider_by_role.get(cleaned_role)

        if provider_name is None:
            valid_roles = ", ".join(
                sorted(provider_by_role)
            )

            raise ConfigurationError(
                f"Unknown NOVA provider role '{role}'. "
                f"Valid roles: {valid_roles}."
            )

        return self.provider(provider_name)

    def safe_summary(self) -> dict[str, Any]:
        """Return the full configuration without revealing secrets."""

        return {
            "profile": self.profile.value,
            "roles": {
                "conversation": self.conversation_provider.value,
                "reasoning": self.reasoning_provider.value,
                "coding": self.coding_provider.value,
                "private": self.private_provider.value,
            },
            "fallback": {
                "enabled": self.fallback_enabled,
                "order": [
                    provider.value
                    for provider in self.fallback_order
                ],
            },
            "providers": {
                name.value: provider.safe_summary()
                for name, provider in self.providers.items()
            },
        }


@dataclass(frozen=True, slots=True)
class ProfileDefaults:
    """Default provider roles for one NOVA profile."""

    conversation: ProviderName
    reasoning: ProviderName
    coding: ProviderName
    private: ProviderName
    fallback: tuple[ProviderName, ...]


PROFILE_DEFAULTS: dict[
    NovaProfile,
    ProfileDefaults,
] = {
    NovaProfile.LOCAL: ProfileDefaults(
        conversation=ProviderName.OLLAMA,
        reasoning=ProviderName.OLLAMA,
        coding=ProviderName.OLLAMA,
        private=ProviderName.OLLAMA,
        fallback=(
            ProviderName.OLLAMA,
        ),
    ),
    NovaProfile.CLOUD: ProfileDefaults(
        conversation=ProviderName.GEMINI,
        reasoning=ProviderName.GEMINI,
        coding=ProviderName.GEMINI,
        private=ProviderName.OLLAMA,
        fallback=(
            ProviderName.OLLAMA,
        ),
    ),
    NovaProfile.HYBRID: ProfileDefaults(
        conversation=ProviderName.GEMINI,
        reasoning=ProviderName.OPENAI,
        coding=ProviderName.OPENAI,
        private=ProviderName.OLLAMA,
        fallback=(
            ProviderName.OLLAMA,
        ),
    ),
}


def _environment_value(
    name: str,
    default: str,
) -> str:
    """Read a nonempty environment value."""

    value = os.getenv(
        name,
        "",
    ).strip()

    return value or default


def _environment_bool(
    name: str,
    default: bool,
) -> bool:
    """Read a Boolean environment variable safely."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    cleaned = raw_value.strip().lower()

    true_values = {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }

    false_values = {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }

    if cleaned in true_values:
        return True

    if cleaned in false_values:
        return False

    raise ConfigurationError(
        f"{name} must be true or false, "
        f"not '{raw_value}'."
    )


def _environment_int(
    name: str,
    default: int,
    *,
    minimum: int = 1,
) -> int:
    """Read a positive integer environment variable."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)

    except ValueError as error:
        raise ConfigurationError(
            f"{name} must be an integer."
        ) from error

    if value < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}."
        )

    return value


def _environment_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.1,
) -> float:
    """Read a positive floating-point environment variable."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = float(raw_value)

    except ValueError as error:
        raise ConfigurationError(
            f"{name} must be a number."
        ) from error

    if value < minimum:
        raise ConfigurationError(
            f"{name} must be at least {minimum}."
        )

    return value


def parse_profile(
    value: NovaProfile | str,
) -> NovaProfile:
    """Convert text into a supported NOVA profile."""

    if isinstance(value, NovaProfile):
        return value

    cleaned = value.strip().lower()

    try:
        return NovaProfile(cleaned)

    except ValueError as error:
        valid_profiles = ", ".join(
            profile.value
            for profile in NovaProfile
        )

        raise ConfigurationError(
            f"Unknown NOVA profile '{value}'. "
            f"Valid profiles: {valid_profiles}."
        ) from error


def parse_provider_name(
    value: ProviderName | str,
) -> ProviderName:
    """Convert text into a supported provider name."""

    if isinstance(value, ProviderName):
        return value

    cleaned = (
        value
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases: dict[str, ProviderName] = {
        "google": ProviderName.GEMINI,
        "gemini_live": ProviderName.GEMINI,
        "gpt": ProviderName.OPENAI,
        "gpt56": ProviderName.OPENAI,
        "gpt_5_6": ProviderName.OPENAI,
        "local": ProviderName.OLLAMA,
    }

    if cleaned in aliases:
        return aliases[cleaned]

    try:
        return ProviderName(cleaned)

    except ValueError as error:
        valid_providers = ", ".join(
            provider.value
            for provider in ProviderName
        )

        raise ConfigurationError(
            f"Unknown provider '{value}'. "
            f"Valid providers: {valid_providers}."
        ) from error


def _parse_fallback_order(
    raw_value: str,
) -> tuple[ProviderName, ...]:
    """Parse a comma-separated fallback provider list."""

    cleaned_items = [
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    ]

    if not cleaned_items:
        return ()

    result: list[ProviderName] = []

    for item in cleaned_items:
        provider = parse_provider_name(item)

        if provider not in result:
            result.append(provider)

    return tuple(result)


def load_configuration() -> NovaConfiguration:
    """
    Load NOVA configuration from environment variables.

    Call this after loading .env.local and .env.
    """

    profile = parse_profile(
        _environment_value(
            "NOVA_PROFILE",
            NovaProfile.HYBRID.value,
        )
    )

    defaults = PROFILE_DEFAULTS[profile]

    conversation_provider = parse_provider_name(
        _environment_value(
            "NOVA_CONVERSATION_PROVIDER",
            defaults.conversation.value,
        )
    )

    reasoning_provider = parse_provider_name(
        _environment_value(
            "NOVA_REASONING_PROVIDER",
            defaults.reasoning.value,
        )
    )

    coding_provider = parse_provider_name(
        _environment_value(
            "NOVA_CODING_PROVIDER",
            defaults.coding.value,
        )
    )

    private_provider = parse_provider_name(
        _environment_value(
            "NOVA_PRIVATE_PROVIDER",
            defaults.private.value,
        )
    )

    default_fallback_order = ",".join(
        provider.value
        for provider in defaults.fallback
    )

    fallback_order = _parse_fallback_order(
        _environment_value(
            "NOVA_FALLBACK_ORDER",
            default_fallback_order,
        )
    )

    providers: dict[
        ProviderName,
        ProviderConfiguration,
    ] = {
        ProviderName.GEMINI: ProviderConfiguration(
            name=ProviderName.GEMINI,
            model=_environment_value(
                "NOVA_REALTIME_MODEL",
                (
                    "gemini-2.5-flash-native-audio-"
                    "preview-12-2025"
                ),
            ),
            enabled=_environment_bool(
                "NOVA_ENABLE_GEMINI",
                True,
            ),
            api_key_environment_variable="GOOGLE_API_KEY",
            timeout_seconds=_environment_float(
                "GEMINI_TIMEOUT_SECONDS",
                60.0,
            ),
            max_output_tokens=_environment_int(
                "GEMINI_MAX_OUTPUT_TOKENS",
                800,
            ),
            is_local=False,
        ),
        ProviderName.OPENAI: ProviderConfiguration(
            name=ProviderName.OPENAI,
            model=_environment_value(
                "OPENAI_MODEL",
                "gpt-5.6",
            ),
            enabled=_environment_bool(
                "NOVA_ENABLE_OPENAI",
                True,
            ),
            api_key_environment_variable="OPENAI_API_KEY",
            timeout_seconds=_environment_float(
                "OPENAI_TIMEOUT_SECONDS",
                60.0,
            ),
            max_output_tokens=_environment_int(
                "OPENAI_MAX_OUTPUT_TOKENS",
                800,
            ),
            is_local=False,
        ),
        ProviderName.GROQ: ProviderConfiguration(
            name=ProviderName.GROQ,
            model=_environment_value(
                "GROQ_MODEL",
                "openai/gpt-oss-120b",
            ),
            enabled=_environment_bool(
                "NOVA_ENABLE_GROQ",
                True,
            ),
            api_key_environment_variable="GROQ_API_KEY",
            base_url=_environment_value(
                "GROQ_BASE_URL",
                "https://api.groq.com/openai/v1",
            ),
            timeout_seconds=_environment_float(
                "GROQ_TIMEOUT_SECONDS",
                30.0,
            ),
            max_output_tokens=_environment_int(
                "GROQ_MAX_TOKENS",
                600,
            ),
            is_local=False,
        ),
        ProviderName.OLLAMA: ProviderConfiguration(
            name=ProviderName.OLLAMA,
            model=_environment_value(
                "OLLAMA_MODEL",
                "mistral:latest",
            ),
            enabled=_environment_bool(
                "NOVA_ENABLE_OLLAMA",
                True,
            ),
            api_key_environment_variable=None,
            base_url=_environment_value(
                "OLLAMA_BASE_URL",
                "http://localhost:11434/v1",
            ),
            timeout_seconds=_environment_float(
                "OLLAMA_TIMEOUT_SECONDS",
                120.0,
            ),
            max_output_tokens=_environment_int(
                "OLLAMA_MAX_TOKENS",
                400,
            ),
            is_local=True,
        ),
    }

    return NovaConfiguration(
        profile=profile,
        conversation_provider=conversation_provider,
        reasoning_provider=reasoning_provider,
        coding_provider=coding_provider,
        private_provider=private_provider,
        fallback_enabled=_environment_bool(
            "NOVA_FALLBACK_ENABLED",
            True,
        ),
        fallback_order=fallback_order,
        providers=providers,
    )