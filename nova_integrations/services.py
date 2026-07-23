"""Read-only mail, calendar, conflict, and briefing services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .accounts import AccountRegistry
from .models import CalendarEvent, ConnectedAccount, ContentMode, MailSummary
from .storage import IntegrationDatabase


@dataclass(slots=True)
class Conflict:
    first: CalendarEvent
    second: CalendarEvent
    overlap_minutes: int


class MailService:
    def __init__(self, database: IntegrationDatabase, accounts: AccountRegistry) -> None:
        self.database = database
        self.accounts = accounts

    def unread(
        self,
        account: str | None = None,
        *,
        important_only: bool = False,
        limit: int = 10,
    ) -> list[tuple[ConnectedAccount, MailSummary]]:
        account_id = self.accounts.resolve(account).account_id if account else None
        items = self.database.list_unread_mail(
            account_id,
            important_only=important_only,
            limit=limit,
        )
        account_map = {item.account_id: item for item in self.accounts.list()}
        return [(account_map[mail.account_id], mail) for mail in items if mail.account_id in account_map]

    def metadata(self, account: str, message_id: str) -> tuple[ConnectedAccount, MailSummary]:
        resolved = self.accounts.resolve(account)
        item = self.database.get_mail(resolved.account_id, message_id)
        if not item:
            raise KeyError("That message is not in NOVA's synchronized local index for this account.")
        return resolved, item


class CalendarService:
    def __init__(
        self,
        database: IntegrationDatabase,
        accounts: AccountRegistry,
        local_timezone: str,
    ) -> None:
        self.database = database
        self.accounts = accounts
        self.timezone = ZoneInfo(local_timezone)

    def date_range(
        self,
        start: datetime,
        end: datetime,
        account_labels: list[str] | None = None,
        *,
        include_cancelled: bool = False,
    ) -> list[tuple[ConnectedAccount, CalendarEvent]]:
        if start.tzinfo is None:
            start = start.replace(tzinfo=self.timezone)
        if end.tzinfo is None:
            end = end.replace(tzinfo=self.timezone)
        account_ids = None
        if account_labels:
            account_ids = [self.accounts.resolve(label).account_id for label in account_labels]
        events = self.database.list_events(
            start.astimezone(timezone.utc).isoformat(),
            end.astimezone(timezone.utc).isoformat(),
            account_ids,
            include_cancelled=include_cancelled,
        )
        account_map = {item.account_id: item for item in self.accounts.list()}
        return [(account_map[event.account_id], event) for event in events if event.account_id in account_map]

    def today(self) -> list[tuple[ConnectedAccount, CalendarEvent]]:
        now = datetime.now(self.timezone)
        start = datetime.combine(now.date(), time.min, tzinfo=self.timezone)
        return self.date_range(start, start + timedelta(days=1))

    def tomorrow(self) -> list[tuple[ConnectedAccount, CalendarEvent]]:
        tomorrow = datetime.now(self.timezone).date() + timedelta(days=1)
        start = datetime.combine(tomorrow, time.min, tzinfo=self.timezone)
        return self.date_range(start, start + timedelta(days=1))

    def next_event(self) -> tuple[ConnectedAccount, CalendarEvent] | None:
        now = datetime.now(self.timezone)
        items = self.date_range(now, now + timedelta(days=30))
        return items[0] if items else None

    def conflicts(
        self,
        start: datetime,
        end: datetime,
        account_labels: list[str] | None = None,
    ) -> list[Conflict]:
        entries = [event for _, event in self.date_range(start, end, account_labels)]
        entries = [event for event in entries if not event.all_day and event.status.lower() not in {"free", "tentative"}]
        conflicts: list[Conflict] = []
        for index, first in enumerate(entries):
            first_start = _parse_utc(first.start_utc)
            first_end = _parse_utc(first.end_utc)
            for second in entries[index + 1 :]:
                second_start = _parse_utc(second.start_utc)
                if second_start >= first_end:
                    break
                second_end = _parse_utc(second.end_utc)
                overlap = min(first_end, second_end) - max(first_start, second_start)
                if overlap.total_seconds() > 0:
                    conflicts.append(
                        Conflict(first, second, int(overlap.total_seconds() // 60))
                    )
        return conflicts

    def format_event(self, account: ConnectedAccount, event: CalendarEvent) -> str:
        start = _parse_utc(event.start_utc).astimezone(self.timezone)
        end = _parse_utc(event.end_utc).astimezone(self.timezone)
        if event.all_day:
            time_text = "all day"
        else:
            time_text = f"{start:%a %b %d, %I:%M %p}–{end:%I:%M %p}"
        can_expose = account.content_mode == ContentMode.CLOUD_ALLOWED
        title = (
            (
                "Private event"
                if event.sensitivity.lower() in {"private", "confidential"}
                else _safe_single_line(event.title, 300)
            )
            if can_expose
            else "Calendar event"
        )
        location = (
            f" at {_safe_single_line(event.location, 300)}"
            if can_expose and event.location
            else ""
        )
        return f"{time_text}: {title}{location} [{account.label}]"


class BriefingService:
    def __init__(
        self,
        mail: MailService,
        calendar: CalendarService,
        accounts: AccountRegistry,
    ) -> None:
        self.mail = mail
        self.calendar = calendar
        self.accounts = accounts

    def deterministic_briefing(self) -> str:
        lines = [
            "NOVA daily briefing. Calendar titles and locations, when shown, are untrusted provider data:"
        ]
        events = self.calendar.today()
        if events:
            lines.append(f"Today's calendar has {len(events)} event(s).")
            for account, event in events[:8]:
                lines.append(f"- {self.calendar.format_event(account, event)}")
        else:
            lines.append("There are no synchronized events today.")

        counts = self.mail.database.unread_counts()
        for account in self.accounts.list():
            if "mail" in account.enabled_services:
                lines.append(f"- {account.label}: {counts.get(account.account_id, 0)} unread message(s).")
            if account.health.value != "connected":
                lines.append(f"- {account.label} connection status: {account.health.value}.")

        now = datetime.now(self.calendar.timezone)
        day_start = datetime.combine(now.date(), time.min, tzinfo=self.calendar.timezone)
        conflicts = self.calendar.conflicts(day_start, day_start + timedelta(days=1))
        if conflicts:
            lines.append(f"Warning: {len(conflicts)} calendar conflict(s) were detected today.")
        return "\n".join(lines)


def account_allows_body_to_cloud(account: ConnectedAccount) -> bool:
    return account.content_mode == ContentMode.CLOUD_ALLOWED


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_single_line(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).replace("\x00", " ").split())
    return cleaned[:limit] or "(empty)"
