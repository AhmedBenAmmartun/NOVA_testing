"""Provider-neutral email notification policy and Windows toast adapter."""

from __future__ import annotations

import ctypes
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time
from typing import Protocol
from urllib.parse import urlparse

from .config import IntegrationConfig
from .models import ConnectedAccount, MailSummary, Provider
from .storage import IntegrationDatabase


logger = logging.getLogger("nova.integrations.notifications")


class Notifier(Protocol):
    def send(self, title: str, message: str, *, launch_url: str = "") -> bool: ...


class ConsoleNotifier:
    def send(self, title: str, message: str, *, launch_url: str = "") -> bool:
        print(f"[NOVA notification] {title}: {message}")
        return True


class WindowsToastNotifier:
    """Uses winotify when available; falls back without crashing sync."""

    def __init__(self, app_id: str = "NOVA") -> None:
        self.app_id = app_id

    def send(self, title: str, message: str, *, launch_url: str = "") -> bool:
        try:
            from winotify import Notification

            toast = Notification(
                app_id=self.app_id,
                title=title,
                msg=message,
                launch=launch_url or "",
            )
            toast.show()
            return True
        except Exception:
            logger.exception("Windows toast dispatch failed")
            return False


@dataclass(slots=True)
class NotificationPolicy:
    quiet_start: str
    quiet_end: str
    hide_content: bool
    suppress_bulk: bool

    def quiet_now(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        current = now.time().replace(second=0, microsecond=0)
        start = _parse_clock(self.quiet_start)
        end = _parse_clock(self.quiet_end)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end


class NotificationDispatcher:
    def __init__(
        self,
        config: IntegrationConfig,
        database: IntegrationDatabase,
        notifier: Notifier | None = None,
    ) -> None:
        self.config = config
        self.database = database
        self.policy = NotificationPolicy(
            quiet_start=config.notifications.quiet_hours_start,
            quiet_end=config.notifications.quiet_hours_end,
            hide_content=config.notifications.hide_content,
            suppress_bulk=config.notifications.suppress_bulk,
        )
        if notifier is not None:
            self.notifier = notifier
        elif os.name == "nt":
            self.notifier = WindowsToastNotifier()
        else:
            self.notifier = ConsoleNotifier()

    def dispatch(self, account: ConnectedAccount, item: MailSummary) -> bool:
        if not self.config.notifications.enabled or not account.notifications_enabled:
            return False
        if self.policy.quiet_now():
            return False
        if account.important_only and item.importance.lower() not in {"high", "important"}:
            return False
        if self.policy.suppress_bulk and _looks_bulk(item):
            return False
        if not self.database.should_notify(item):
            return False

        private = self.policy.hide_content or is_windows_session_locked()
        title = f"New email — {account.label}"
        if private:
            message = "A new message arrived. Open NOVA to review it."
        else:
            sender = item.sender_name or item.sender_address or "Unknown sender"
            message = f"{sender}: {item.subject or '(No subject)'}"
        launch_url = item.web_link if _approved_link(item.provider, item.web_link) else ""
        try:
            sent = bool(self.notifier.send(title, message, launch_url=launch_url))
        except Exception:
            logger.exception("Notification adapter raised unexpectedly")
            sent = False
        if sent:
            self.database.mark_notified(item)
            self.database.audit(
                "notification_dispatched",
                account_id=account.account_id,
                provider=account.provider.value,
                detail="new inbox message metadata notification",
            )
        return sent


def is_windows_session_locked() -> bool:
    if os.name != "nt":
        return False
    DESKTOP_SWITCHDESKTOP = 0x0100
    try:
        user32 = ctypes.windll.user32
        desktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not desktop:
            return True
        try:
            return not bool(user32.SwitchDesktop(desktop))
        finally:
            user32.CloseDesktop(desktop)
    except Exception:
        return False


def _parse_clock(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _approved_link(provider: Provider, value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    allowed = {
        Provider.GOOGLE: {"mail.google.com"},
        Provider.MICROSOFT: {
            "outlook.office.com",
            "outlook.office365.com",
            "outlook.live.com",
        },
    }
    return host in allowed[provider]


def _looks_bulk(item: MailSummary) -> bool:
    sender = item.sender_address.lower()
    subject = item.subject.lower()
    return any(
        marker in sender or marker in subject
        for marker in (
            "no-reply",
            "noreply",
            "newsletter",
            "unsubscribe",
            "promotion",
            "marketing",
        )
    ) and item.importance.lower() not in {"high", "important"}
