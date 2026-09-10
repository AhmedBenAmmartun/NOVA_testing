"""Core configuration and provider routing for NOVA."""

from .configuration import (
    ConfigurationError,
    NovaConfiguration,
    NovaProfile,
    ProviderConfiguration,
    ProviderName,
    load_configuration,
    parse_profile,
    parse_provider_name,
)
from .provider_health import (
    ProviderAttemptDecision,
    ProviderCircuitState,
    ProviderFailureKind,
    ProviderHealthTracker,
    classify_provider_error,
    create_provider_health_tracker,
)
from .provider_registry import (
    ProviderNotRegisteredError,
    ProviderRegistry,
    ProviderRegistryError,
    create_provider_registry,
)
from .router import (
    ModelRouter,
    NoProviderAvailableError,
    RouterError,
    RoutingAttempt,
    create_model_router,
)
from .realtime import (
    RealtimeFailureKind,
    RealtimeProviderError,
    RealtimeProviderNotConfiguredError,
    RealtimeProviderUnsupportedError,
    RealtimeSelection,
    build_realtime_model,
    classify_realtime_error,
    load_realtime_selection,
)


__all__ = [
    "ConfigurationError",
    "NovaConfiguration",
    "NovaProfile",
    "ProviderConfiguration",
    "ProviderName",
    "ProviderAttemptDecision",
    "ProviderCircuitState",
    "ProviderFailureKind",
    "ProviderHealthTracker",
    "ProviderRegistry",
    "ProviderRegistryError",
    "ProviderNotRegisteredError",
    "ModelRouter",
    "RouterError",
    "NoProviderAvailableError",
    "RoutingAttempt",
    "RealtimeFailureKind",
    "RealtimeProviderError",
    "RealtimeProviderNotConfiguredError",
    "RealtimeProviderUnsupportedError",
    "RealtimeSelection",
    "load_configuration",
    "parse_profile",
    "parse_provider_name",
    "classify_provider_error",
    "classify_realtime_error",
    "create_provider_health_tracker",
    "create_provider_registry",
    "create_model_router",
    "build_realtime_model",
    "load_realtime_selection",
]