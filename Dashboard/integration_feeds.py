"""Read-only email/calendar data for the local NOVA dashboard.

This module reads the integration SQLite database and safe JSONL event stream.
It never reads OAuth tokens, email bodies, attachments, or provider passwords.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo

try:
    from nova_integrations.config import load_config
    from nova_integrations.models import ContentMode
    from nova_integrations.storage import IntegrationDatabase
except ImportError:  # Package has not been installed yet.
    load_config = None  # type: ignore[assignment]
    ContentMode = None  # type: ignore[assignment]
    IntegrationDatabase = None  # type: ignore[assignment]


_PROVIDER_COLORS = {
    "google": "#2ee6d6",
    "microsoft": "#7c86f8",
}
_CATEGORY_COLORS = {
    "school": "#f5a97b",
    "work": "#aab1ff",
    "personal": "#2ee6d6",
}


def _safe_text(value: object, limit: int = 500) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())[:limit]


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_time_cross_platform(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def _format_day_cross_platform(value: datetime) -> str:
    return value.strftime("%a %b %d").replace(" 0", " ")


def _when(start: datetime, end: datetime, all_day: bool, now: datetime) -> str:
    if all_day:
        if start.date() == now.date():
            return "Today · All day"
        if start.date() == now.date() + timedelta(days=1):
            return "Tomorrow · All day"
        return f"{_format_day_cross_platform(start)} · All day"
    if start.date() == now.date():
        prefix = "Today"
    elif start.date() == now.date() + timedelta(days=1):
        prefix = "Tomorrow"
    else:
        prefix = _format_day_cross_platform(start)
    return f"{prefix} · {_format_time_cross_platform(start)}"


def _load_database():
    if load_config is None or IntegrationDatabase is None:
        return None, None
    try:
        cache_clear = getattr(load_config, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
        config = load_config()
        return config, IntegrationDatabase(config.database_path)
    except Exception:
        return None, None


def status_message() -> dict:
    config, database = _load_database()
    if not config or not database:
        return {
            "type": "integrations",
            "available": False,
            "status": "not_installed",
            "accounts": [],
            "connectedCount": 0,
            "totalUnread": 0,
        }
    try:
        accounts = database.list_accounts()
        counts = database.unread_counts()
        rows = []
        for account in accounts:
            rows.append(
                {
                    "id": account.account_id,
                    "label": account.label,
                    "provider": account.provider.value,
                    "category": account.category.value,
                    "services": list(account.enabled_services),
                    "contentMode": account.content_mode.value,
                    "health": account.health.value,
                    "healthDetail": _safe_text(account.health_detail, 240),
                    "lastSync": account.last_sync_at,
                    "principal": account.principal_hint,
                    "unread": counts.get(account.account_id, 0),
                }
            )
        connected = sum(1 for account in accounts if account.health.value == "connected")
        status = "connected" if connected else ("needs_attention" if accounts else "not_configured")
        return {
            "type": "integrations",
            "available": True,
            "status": status,
            "accounts": rows,
            "connectedCount": connected,
            "totalUnread": sum(counts.values()),
        }
    except Exception as exc:
        return {
            "type": "integrations",
            "available": True,
            "status": "error",
            "accounts": [],
            "connectedCount": 0,
            "totalUnread": 0,
            "detail": _safe_text(exc, 240),
        }


def mail_message(limit: int = 12) -> dict:
    config, database = _load_database()
    if not config or not database:
        return {"type": "mail", "available": False, "totalUnread": 0, "items": []}
    try:
        accounts = {item.account_id: item for item in database.list_accounts()}
        counts = database.unread_counts()
        rows = []
        for item in database.list_unread_mail(limit=limit):
            account = accounts.get(item.account_id)
            if not account:
                continue
            # This dashboard is local-only. Header metadata may be shown locally,
            # while complete message bodies remain excluded from the database.
            rows.append(
                {
                    "id": f"{item.provider.value}:{item.account_id}:{item.message_id}",
                    "messageId": item.message_id,
                    "accountId": item.account_id,
                    "account": account.label,
                    "provider": item.provider.value,
                    "category": account.category.value,
                    "sender": _safe_text(item.sender_name or item.sender_address, 160) or "Unknown sender",
                    "subject": _safe_text(item.subject, 300) or "(No subject)",
                    "receivedAt": item.received_at,
                    "importance": item.importance,
                    "webLink": item.web_link,
                }
            )
        return {
            "type": "mail",
            "available": True,
            "totalUnread": sum(counts.values()),
            "counts": counts,
            "items": rows,
        }
    except Exception as exc:
        return {
            "type": "mail",
            "available": True,
            "totalUnread": 0,
            "items": [],
            "error": _safe_text(exc, 240),
        }


def calendar_message(*, now: datetime | None = None) -> dict:
    config, database = _load_database()
    if not config or not database:
        return {
            "type": "calendar",
            "available": False,
            "status": "not_installed",
            "monthTitle": "Calendar",
            "todayLabel": "Not connected",
            "events": [],
            "upcoming": [],
        }
    try:
        local_zone = ZoneInfo(config.local_timezone)
        now = now.astimezone(local_zone) if now else datetime.now(local_zone)
        month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=local_zone)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        range_end = max(next_month, now + timedelta(days=60))
        accounts = {item.account_id: item for item in database.list_accounts()}
        events = database.list_events(
            month_start.astimezone(timezone.utc).isoformat(),
            range_end.astimezone(timezone.utc).isoformat(),
        )
        event_rows = []
        upcoming = []
        for event in events:
            account = accounts.get(event.account_id)
            if not account:
                continue
            start = _parse_datetime(event.start_utc).astimezone(local_zone)
            end = _parse_datetime(event.end_utc).astimezone(local_zone)
            sensitive = str(event.sensitivity or "").lower() in {"private", "confidential"}
            title = "Private event" if sensitive else (_safe_text(event.title, 300) or "Calendar event")
            color = _CATEGORY_COLORS.get(account.category.value, _PROVIDER_COLORS.get(account.provider.value, "#7c86f8"))
            row = {
                "id": f"{event.provider.value}:{event.account_id}:{event.calendar_id}:{event.event_id}:{event.occurrence_id}",
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "day": start.day,
                "month": start.month,
                "year": start.year,
                "allDay": event.all_day,
                "account": account.label,
                "provider": account.provider.value,
                "category": account.category.value,
                "calendar": _safe_text(event.calendar_name, 160),
                "location": "" if sensitive else _safe_text(event.location, 220),
                "webLink": event.web_link,
                "meetingLink": event.meeting_link,
                "color": color,
            }
            event_rows.append(row)
            if end >= now and len(upcoming) < 12:
                upcoming.append({**row, "when": _when(start, end, event.all_day, now)})
        connected = sum(1 for account in accounts.values() if account.health.value == "connected")
        return {
            "type": "calendar",
            "available": True,
            "status": "connected" if connected else ("needs_attention" if accounts else "not_configured"),
            "monthTitle": now.strftime("%B %Y"),
            "todayLabel": "Today · " + now.strftime("%A, %B %d").replace(" 0", " "),
            "month": now.month,
            "year": now.year,
            "firstWeekday": (month_start.weekday() + 1) % 7,
            "daysInMonth": (next_month.date() - month_start.date()).days,
            "events": [row for row in event_rows if row["month"] == now.month and row["year"] == now.year],
            "upcoming": upcoming,
            "accountCount": len(accounts),
            "connectedCount": connected,
        }
    except Exception as exc:
        return {
            "type": "calendar",
            "available": True,
            "status": "error",
            "monthTitle": "Calendar",
            "todayLabel": "Integration error",
            "events": [],
            "upcoming": [],
            "error": _safe_text(exc, 240),
        }


def briefing_message() -> dict:
    status = status_message()
    calendar = calendar_message()
    mail = mail_message(limit=1)
    if not status.get("accounts"):
        text = "Connect Gmail or Outlook to show your live agenda and unread mail here."
    else:
        event_count = len(calendar.get("upcoming", []))
        unread = int(mail.get("totalUnread", 0))
        connected = int(status.get("connectedCount", 0))
        text = f"{connected} account(s) connected · {unread} unread email(s) · {event_count} upcoming event(s)."
    return {"type": "briefing", "text": text}


def snapshot_messages() -> list[dict]:
    return [status_message(), mail_message(), calendar_message(), briefing_message()]


@dataclass
class IntegrationEventTail:
    path: Path | None = None
    from_start: bool = False

    def __post_init__(self) -> None:
        if self.path is None and load_config is not None:
            try:
                self.path = load_config().event_log_path
            except Exception:
                self.path = None
        self._position = 0
        self._lock = RLock()
        self._initialized = False

    def read_new(self) -> list[dict]:
        path = self.path
        if not path or not path.is_file():
            return []
        with self._lock:
            try:
                size = path.stat().st_size
                if not self._initialized:
                    self._position = 0 if self.from_start else size
                    self._initialized = True
                    return []
                if size < self._position:
                    self._position = 0
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    handle.seek(self._position)
                    lines = handle.readlines()
                    self._position = handle.tell()
            except OSError:
                return []
        events = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events


def event_to_dashboard(event: dict) -> dict | None:
    title = _safe_text(event.get("title"), 160)
    message = _safe_text(event.get("message"), 500)
    if not title and not message:
        return None
    severity = str(event.get("severity", "info")).lower()
    icon = "⚠" if severity in {"warning", "error"} else "✉"
    return {"type": "notify", "icon": icon, "title": title or "Email & Calendar", "text": message}
