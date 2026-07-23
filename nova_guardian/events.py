"""Event types used by NOVA Guardian."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class GuardianEventCategory(str, Enum):
    """High-level Guardian event categories."""

    SYSTEM = "system"
    WINDOW = "window"
    VISION = "vision"
    PROCESS = "process"
    NETWORK = "network"
    SECURITY = "security"
    IDENTITY = "identity"


class GuardianEventSeverity(str, Enum):
    """Severity assigned to a Guardian event."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GuardianEventType(str, Enum):
    """Specific events Guardian may produce."""

    GUARDIAN_STARTED = "guardian_started"
    GUARDIAN_STOPPED = "guardian_stopped"

    ACTIVE_WINDOW_CHANGED = "active_window_changed"
    SENSITIVE_WINDOW_DETECTED = "sensitive_window_detected"

    VISION_STARTED = "vision_started"
    VISION_STOPPED = "vision_stopped"
    VISION_PAUSED = "vision_paused"
    VISION_RESUMED = "vision_resumed"
    VISION_SESSION_EXPIRED = "vision_session_expired"

    PROCESS_STARTED = "process_started"
    PROCESS_STOPPED = "process_stopped"
    SUSPICIOUS_PROCESS_DETECTED = (
        "suspicious_process_detected"
    )

    NETWORK_LISTENER_DETECTED = (
        "network_listener_detected"
    )

    SECURITY_PROTECTION_DISABLED = (
        "security_protection_disabled"
    )
    SECURITY_PROTECTION_RESTORED = (
        "security_protection_restored"
    )

    UNKNOWN_USER_DETECTED = "unknown_user_detected"
    USER_IDENTITY_CONFIRMED = "user_identity_confirmed"


@dataclass(frozen=True, slots=True)
class GuardianEvent:
    """One safe Guardian observation or alert."""

    event_type: GuardianEventType
    category: GuardianEventCategory
    severity: GuardianEventSeverity
    title: str
    message: str

    source: str = "nova_guardian"

    event_id: str = field(
        default_factory=lambda: uuid4().hex
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    requires_attention: bool = False
    acknowledged: bool = False

    def safe_summary(self) -> dict[str, Any]:
        """
        Return event information without image contents,
        credentials, tokens, or other private data.
        """

        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
            "requires_attention": (
                self.requires_attention
            ),
            "acknowledged": self.acknowledged,
        }


def create_guardian_event(
    *,
    event_type: GuardianEventType,
    category: GuardianEventCategory,
    severity: GuardianEventSeverity,
    title: str,
    message: str,
    source: str = "nova_guardian",
    metadata: dict[str, Any] | None = None,
    requires_attention: bool | None = None,
) -> GuardianEvent:
    """Create a normalized Guardian event."""

    cleaned_title = title.strip()
    cleaned_message = message.strip()
    cleaned_source = source.strip() or "nova_guardian"

    if not cleaned_title:
        cleaned_title = event_type.value.replace(
            "_",
            " ",
        ).title()

    if not cleaned_message:
        cleaned_message = cleaned_title

    if requires_attention is None:
        requires_attention = severity in {
            GuardianEventSeverity.HIGH,
            GuardianEventSeverity.CRITICAL,
        }

    return GuardianEvent(
        event_type=event_type,
        category=category,
        severity=severity,
        title=cleaned_title,
        message=cleaned_message,
        source=cleaned_source,
        metadata=dict(metadata or {}),
        requires_attention=requires_attention,
    )