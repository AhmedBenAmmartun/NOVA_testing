"""Native realtime-provider selection for NOVA.

Provider Resilience P0 deliberately keeps the existing LiveKit transport and
Gemini native audio/video behavior. Text specialist fallback remains owned by
nova_core.router. A later milestone may add an STT -> text router -> TTS
fallback lane; P0 does not pretend text providers are native realtime models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from google.genai import types
from livekit.plugins import google

from .configuration import (
    ConfigurationError,
    NovaConfiguration,
    ProviderName,
    load_configuration,
    parse_provider_name,
)


class RealtimeProviderError(RuntimeError):
    """Base error for NOVA native realtime-provider selection."""


class RealtimeProviderUnsupportedError(RealtimeProviderError):
    """Raised when a provider cannot serve NOVA's native realtime lane."""


class RealtimeProviderNotConfiguredError(RealtimeProviderError):
    """Raised when the selected native realtime provider is not configured."""


class RealtimeFailureKind(StrEnum):
    """Safe classification of native realtime provider failures."""

    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    REQUEST = "request"
    UNKNOWN = "unknown"


def classify_realtime_error(
    error: BaseException | None,
) -> RealtimeFailureKind:
    """Classify a realtime failure without returning its raw message.

    The realtime lane does not raise NOVA's own provider errors -- failures
    arrive from LiveKit/Gemini as whatever the transport produced. Only the
    resulting category and the exception class name are safe to keep.

    Callers must pass the *provider* exception, not LiveKit's
    `RealtimeModelError` wrapper: the wrapper has no status code and a single
    fixed class name, so classifying it would report every failure as
    `unknown`. See `agent._unwrap_realtime_error`.
    """

    if error is None:
        return RealtimeFailureKind.UNKNOWN

    status_code = getattr(error, "status_code", None)

    if status_code in {401, 403}:
        return RealtimeFailureKind.AUTHENTICATION

    if status_code == 429:
        return RealtimeFailureKind.RATE_LIMIT

    if status_code == 408 or (
        isinstance(status_code, int) and status_code >= 500
    ):
        return RealtimeFailureKind.UNAVAILABLE

    if isinstance(status_code, int) and 400 <= status_code < 500:
        return RealtimeFailureKind.REQUEST

    name = type(error).__name__.lower()
    message = str(error).lower()

    def _matches(*tokens: str) -> bool:
        return any(
            token in name or token in message
            for token in tokens
        )

    if _matches(
        "ratelimit",
        "rate limit",
        "quota",
        "resource_exhausted",
    ):
        return RealtimeFailureKind.RATE_LIMIT

    if _matches(
        "authentication",
        "permission",
        "api key",
        "unauthorized",
        "forbidden",
    ):
        return RealtimeFailureKind.AUTHENTICATION

    if _matches(
        "timeout",
        "deadline",
        "connection",
        "unavailable",
        "gateway",
    ):
        return RealtimeFailureKind.UNAVAILABLE

    return RealtimeFailureKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class RealtimeSelection:
    """Safe metadata describing the selected native realtime provider."""

    provider: ProviderName
    model: str
    voice: str
    temperature: float
    route: str

    def safe_summary(self) -> dict[str, Any]:
        """Return selection metadata without credentials or private values."""

        return {
            "provider": self.provider.value,
            "model": self.model,
            "voice": self.voice,
            "temperature": self.temperature,
            "route": self.route,
        }


def _environment_value(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _realtime_temperature() -> float:
    raw = _environment_value("NOVA_TEMPERATURE", "0.5")

    try:
        value = float(raw)
    except ValueError as error:
        raise RealtimeProviderError(
            "NOVA_TEMPERATURE must be a number."
        ) from error

    if not 0.0 <= value <= 2.0:
        raise RealtimeProviderError(
            "NOVA_TEMPERATURE must be between 0.0 and 2.0."
        )

    return value


def load_realtime_selection(
    configuration: NovaConfiguration | None = None,
) -> RealtimeSelection:
    """Resolve the native realtime lane without constructing a network client."""

    active_configuration = (
        configuration
        if configuration is not None
        else load_configuration()
    )

    raw_provider = _environment_value(
        "NOVA_REALTIME_PROVIDER",
        ProviderName.GEMINI.value,
    )

    try:
        provider = parse_provider_name(raw_provider)
    except ConfigurationError as error:
        raise RealtimeProviderUnsupportedError(
            f"Unsupported native realtime provider '{raw_provider}'. "
            "Provider Resilience P0 supports Gemini for native "
            "audio/video realtime."
        ) from error

    if provider is not ProviderName.GEMINI:
        raise RealtimeProviderUnsupportedError(
            f"Provider '{provider.value}' is not a native audio/video "
            "realtime provider in Provider Resilience P0. Gemini remains "
            "the native realtime lane; Groq/OpenAI/Ollama continue through "
            "NOVA's existing text ModelRouter."
        )

    provider_configuration = active_configuration.provider(
        ProviderName.GEMINI
    )

    return RealtimeSelection(
        provider=ProviderName.GEMINI,
        model=provider_configuration.model,
        voice=_environment_value("NOVA_VOICE", "Puck"),
        temperature=_realtime_temperature(),
        route="gemini_realtime",
    )


def build_realtime_model(
    configuration: NovaConfiguration | None = None,
) -> tuple[object, RealtimeSelection]:
    """Build NOVA's selected native realtime LiveKit model.

    P0 preserves the exact Gemini audio/video turn handling that was already
    verified in A1 while moving construction behind one provider-neutral
    boundary.
    """

    active_configuration = (
        configuration
        if configuration is not None
        else load_configuration()
    )
    selection = load_realtime_selection(active_configuration)

    provider_configuration = active_configuration.provider(
        selection.provider
    )

    if not provider_configuration.enabled:
        raise RealtimeProviderNotConfiguredError(
            "The Gemini native realtime provider is disabled. "
            "Set NOVA_ENABLE_GEMINI=true to use the P0 realtime lane."
        )

    if not provider_configuration.api_key_configured:
        raise RealtimeProviderNotConfiguredError(
            "The Gemini native realtime provider is not configured. "
            "Configure GOOGLE_API_KEY in NOVA's trusted local environment."
        )

    realtime_model = google.realtime.RealtimeModel(
        model=selection.model,
        voice=selection.voice,
        temperature=selection.temperature,

        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),

        thinking_config=types.ThinkingConfig(
            thinking_budget=0,
            include_thoughts=False,
        ),

        realtime_input_config=types.RealtimeInputConfig(
            turn_coverage=(
                types.TurnCoverage.TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO
            ),
            activity_handling=(
                types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
            ),
            automatic_activity_detection=(
                types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=(
                        types.StartSensitivity.
                        START_SENSITIVITY_HIGH
                    ),
                    end_of_speech_sensitivity=(
                        types.EndSensitivity.
                        END_SENSITIVITY_LOW
                    ),
                    prefix_padding_ms=120,
                    silence_duration_ms=400,
                )
            ),
        ),
    )

    return realtime_model, selection
