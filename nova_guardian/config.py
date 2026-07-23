"""Safe configuration for NOVA Guardian and ambient vision."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any


class GuardianConfigurationError(ValueError):
    """Raised when Guardian receives invalid configuration."""


class VisionMode(str, Enum):
    """Supported Guardian vision modes."""

    OFF = "off"
    ON_DEMAND = "on_demand"
    AMBIENT = "ambient"
    TEMPORARY_SESSION = "temporary_session"


@dataclass(frozen=True, slots=True)
class GuardianConfiguration:
    """Complete NOVA Guardian configuration."""

    enabled: bool
    security_monitor_enabled: bool
    active_window_monitor_enabled: bool

    vision_mode: VisionMode
    local_vision_only: bool
    pause_on_sensitive_windows: bool

    capture_interval_seconds: float
    maximum_vision_session_minutes: int

    store_screenshots: bool
    screenshot_retention_seconds: int

    security_scan_interval_seconds: float
    automatic_response_enabled: bool

    excluded_processes: tuple[str, ...]
    sensitive_title_keywords: tuple[str, ...]

    def process_is_excluded(
        self,
        process_name: str,
    ) -> bool:
        """Return whether this process must not be captured."""

        cleaned = process_name.strip().lower()

        if cleaned.endswith(".exe"):
            cleaned = cleaned[:-4]

        return cleaned in self.excluded_processes

    def title_is_sensitive(
        self,
        window_title: str,
    ) -> bool:
        """Return whether a window title appears sensitive."""

        if not self.pause_on_sensitive_windows:
            return False

        cleaned_title = window_title.strip().lower()

        if not cleaned_title:
            return False

        return any(
            keyword in cleaned_title
            for keyword in self.sensitive_title_keywords
        )

    def safe_summary(self) -> dict[str, Any]:
        """Return Guardian configuration without private data."""

        return {
            "enabled": self.enabled,
            "security_monitor_enabled": (
                self.security_monitor_enabled
            ),
            "active_window_monitor_enabled": (
                self.active_window_monitor_enabled
            ),
            "vision_mode": self.vision_mode.value,
            "local_vision_only": self.local_vision_only,
            "pause_on_sensitive_windows": (
                self.pause_on_sensitive_windows
            ),
            "capture_interval_seconds": (
                self.capture_interval_seconds
            ),
            "maximum_vision_session_minutes": (
                self.maximum_vision_session_minutes
            ),
            "store_screenshots": self.store_screenshots,
            "screenshot_retention_seconds": (
                self.screenshot_retention_seconds
            ),
            "security_scan_interval_seconds": (
                self.security_scan_interval_seconds
            ),
            "automatic_response_enabled": (
                self.automatic_response_enabled
            ),
            "excluded_processes": list(
                self.excluded_processes
            ),
            "sensitive_title_keywords": list(
                self.sensitive_title_keywords
            ),
        }


def _environment_bool(
    name: str,
    default: bool,
) -> bool:
    """Read a Boolean environment variable."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    cleaned = raw_value.strip().lower()

    if cleaned in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }:
        return True

    if cleaned in {
        "0",
        "false",
        "no",
        "off",
        "disabled",
    }:
        return False

    raise GuardianConfigurationError(
        f"{name} must be true or false, "
        f"not '{raw_value}'."
    )


def _environment_int(
    name: str,
    default: int,
    *,
    minimum: int = 0,
) -> int:
    """Read an integer environment variable."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)

    except ValueError as error:
        raise GuardianConfigurationError(
            f"{name} must be an integer."
        ) from error

    if value < minimum:
        raise GuardianConfigurationError(
            f"{name} must be at least {minimum}."
        )

    return value


def _environment_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.1,
) -> float:
    """Read a floating-point environment variable."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = float(raw_value)

    except ValueError as error:
        raise GuardianConfigurationError(
            f"{name} must be a number."
        ) from error

    if value < minimum:
        raise GuardianConfigurationError(
            f"{name} must be at least {minimum}."
        )

    return value


def _environment_list(
    name: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    """Read a comma-separated environment list."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    items: list[str] = []

    for raw_item in raw_value.split(","):
        cleaned = raw_item.strip().lower()

        if cleaned.endswith(".exe"):
            cleaned = cleaned[:-4]

        if cleaned and cleaned not in items:
            items.append(cleaned)

    return tuple(items)


def _environment_vision_mode(
    name: str,
    default: VisionMode,
) -> VisionMode:
    """Read and validate the vision mode."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    cleaned = (
        raw_value
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "none": VisionMode.OFF,
        "disabled": VisionMode.OFF,
        "ask": VisionMode.ON_DEMAND,
        "ask_every_time": VisionMode.ON_DEMAND,
        "local": VisionMode.AMBIENT,
        "watch": VisionMode.TEMPORARY_SESSION,
        "session": VisionMode.TEMPORARY_SESSION,
    }

    if cleaned in aliases:
        return aliases[cleaned]

    try:
        return VisionMode(cleaned)

    except ValueError as error:
        valid_modes = ", ".join(
            mode.value
            for mode in VisionMode
        )

        raise GuardianConfigurationError(
            f"Unknown vision mode '{raw_value}'. "
            f"Valid modes: {valid_modes}."
        ) from error


DEFAULT_EXCLUDED_PROCESSES = (
    "1password",
    "bitwarden",
    "keepass",
    "keepassxc",
    "lastpass",
    "nordpass",
    "protonpass",
    "credentialui",
    "logonui",
)

DEFAULT_SENSITIVE_TITLE_KEYWORDS = (
    "password",
    "passcode",
    "sign in",
    "login",
    "authentication",
    "verification code",
    "security code",
    "one-time code",
    "payment",
    "checkout",
    "banking",
    "credit card",
    "private browsing",
    "incognito",
    "api key",
    "secret key",
    "access token",
    "credentials",
)


def load_guardian_configuration() -> GuardianConfiguration:
    """Load Guardian configuration from environment variables."""

    return GuardianConfiguration(
        enabled=_environment_bool(
            "NOVA_GUARDIAN_ENABLED",
            False,
        ),
        security_monitor_enabled=_environment_bool(
            "NOVA_SECURITY_MONITOR_ENABLED",
            True,
        ),
        active_window_monitor_enabled=_environment_bool(
            "NOVA_WINDOW_MONITOR_ENABLED",
            True,
        ),
        vision_mode=_environment_vision_mode(
            "NOVA_VISION_MODE",
            VisionMode.OFF,
        ),
        local_vision_only=_environment_bool(
            "NOVA_LOCAL_VISION_ONLY",
            True,
        ),
        pause_on_sensitive_windows=_environment_bool(
            "NOVA_PAUSE_ON_SENSITIVE_WINDOWS",
            True,
        ),
        capture_interval_seconds=_environment_float(
            "NOVA_VISION_CAPTURE_INTERVAL_SECONDS",
            4.0,
            minimum=1.0,
        ),
        maximum_vision_session_minutes=_environment_int(
            "NOVA_MAX_VISION_SESSION_MINUTES",
            5,
            minimum=1,
        ),
        store_screenshots=_environment_bool(
            "NOVA_STORE_VISION_SCREENSHOTS",
            False,
        ),
        screenshot_retention_seconds=_environment_int(
            "NOVA_SCREENSHOT_RETENTION_SECONDS",
            0,
            minimum=0,
        ),
        security_scan_interval_seconds=_environment_float(
            "NOVA_SECURITY_SCAN_INTERVAL_SECONDS",
            15.0,
            minimum=5.0,
        ),
        automatic_response_enabled=_environment_bool(
            "NOVA_GUARDIAN_AUTO_RESPONSE",
            False,
        ),
        excluded_processes=_environment_list(
            "NOVA_VISION_EXCLUDED_PROCESSES",
            DEFAULT_EXCLUDED_PROCESSES,
        ),
        sensitive_title_keywords=_environment_list(
            "NOVA_SENSITIVE_WINDOW_KEYWORDS",
            DEFAULT_SENSITIVE_TITLE_KEYWORDS,
        ),
    )