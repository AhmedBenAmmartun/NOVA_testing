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
    RealtimeProviderError,
    RealtimeProviderNotConfiguredError,
    RealtimeProviderUnsupportedError,
    RealtimeSelection,
    build_realtime_model,
    load_realtime_selection,
)


__all__ = [
    "ConfigurationError",
    "NovaConfiguration",
    "NovaProfile",
    "ProviderConfiguration",
    "ProviderName",
    "ProviderRegistry",
    "ProviderRegistryError",
    "ProviderNotRegisteredError",
    "ModelRouter",
    "RouterError",
    "NoProviderAvailableError",
    "RoutingAttempt",
    "RealtimeProviderError",
    "RealtimeProviderNotConfiguredError",
    "RealtimeProviderUnsupportedError",
    "RealtimeSelection",
    "load_configuration",
    "parse_profile",
    "parse_provider_name",
    "create_provider_registry",
    "create_model_router",
    "build_realtime_model",
    "load_realtime_selection",
]