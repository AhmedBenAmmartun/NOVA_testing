"""Connector contracts and provider-safe exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import AccountCategory, CalendarEvent, ConnectedAccount, ContentMode, MailSummary, Provider


class ConnectorError(RuntimeError):
    pass


class ReconnectRequired(ConnectorError):
    pass


class AdminApprovalRequired(ConnectorError):
    pass


class RateLimited(ConnectorError):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(slots=True)
class MailSyncBatch:
    items: list[MailSummary] = field(default_factory=list)
    removed_ids: list[str] = field(default_factory=list)
    baseline: bool = False
    cursor_reset: bool = False


@dataclass(slots=True)
class CalendarSyncBatch:
    items: list[CalendarEvent] = field(default_factory=list)
    removed_keys: list[tuple[str, str, str]] = field(default_factory=list)
    baseline: bool = False
    cursor_reset: bool = False


class WorkspaceConnector(ABC):
    provider: Provider

    @abstractmethod
    def connect(
        self,
        *,
        label: str,
        category: AccountCategory,
        services: tuple[str, ...],
        content_mode: ContentMode,
    ) -> ConnectedAccount: ...

    @abstractmethod
    def test_account(self, account: ConnectedAccount) -> str: ...

    @abstractmethod
    def sync_mail(self, account: ConnectedAccount) -> MailSyncBatch: ...

    @abstractmethod
    def sync_calendar(self, account: ConnectedAccount) -> CalendarSyncBatch: ...

    @abstractmethod
    def fetch_message_body(self, account: ConnectedAccount, message_id: str) -> str: ...
