"""Provider-neutral models for NOVA mail and calendar integrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Provider(str, Enum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class AccountCategory(str, Enum):
    PERSONAL = "personal"
    SCHOOL = "school"
    WORK = "work"


class AccountHealth(str, Enum):
    CONNECTED = "connected"
    NEEDS_RECONNECT = "needs_reconnect"
    ADMIN_APPROVAL_REQUIRED = "admin_approval_required"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ContentMode(str, Enum):
    METADATA_ONLY = "metadata_only"
    LOCAL_PRIVATE = "local_private"
    CLOUD_ALLOWED = "cloud_allowed"


@dataclass(slots=True)
class ConnectedAccount:
    account_id: str
    provider: Provider
    label: str
    category: AccountCategory
    principal_hint: str
    enabled_services: tuple[str, ...]
    content_mode: ContentMode = ContentMode.METADATA_ONLY
    notifications_enabled: bool = True
    important_only: bool = False
    health: AccountHealth = AccountHealth.CONNECTED
    health_detail: str = ""
    last_sync_at: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def safe_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["provider"] = self.provider.value
        data["category"] = self.category.value
        data["content_mode"] = self.content_mode.value
        data["health"] = self.health.value
        return data


@dataclass(slots=True)
class MailSummary:
    provider: Provider
    account_id: str
    message_id: str
    sender_name: str
    sender_address: str
    subject: str
    received_at: str
    is_read: bool
    importance: str = "normal"
    web_link: str = ""
    folder: str = "inbox"
    snippet: str = ""
    deleted: bool = False

    @property
    def stable_key(self) -> tuple[str, str, str]:
        return (self.provider.value, self.account_id, self.message_id)


@dataclass(slots=True)
class CalendarEvent:
    provider: Provider
    account_id: str
    calendar_id: str
    event_id: str
    occurrence_id: str
    title: str
    start_utc: str
    end_utc: str
    original_timezone: str
    all_day: bool = False
    status: str = "busy"
    cancelled: bool = False
    sensitivity: str = "normal"
    location: str = ""
    web_link: str = ""
    meeting_link: str = ""
    calendar_name: str = ""

    @property
    def stable_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.provider.value,
            self.account_id,
            self.calendar_id,
            self.event_id,
            self.occurrence_id,
        )


@dataclass(slots=True)
class SyncResult:
    provider: Provider
    account_id: str
    resource: str
    added: int = 0
    updated: int = 0
    deleted: int = 0
    notifications: int = 0
    cursor_reset: bool = False
    error: str = ""


@dataclass(slots=True)
class IntegrationEvent:
    event_type: str
    account_id: str
    provider: str
    title: str
    message: str
    severity: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def safe_dict(self) -> dict[str, Any]:
        return asdict(self)
