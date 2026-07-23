"""SQLite persistence for normalized mail/calendar metadata.

The database intentionally does not persist OAuth tokens, refresh tokens,
complete email bodies, or attachments. OAuth material and opaque sync cursors
are stored in the OS keyring instead.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable, Iterator

from .models import (
    AccountCategory,
    AccountHealth,
    CalendarEvent,
    ConnectedAccount,
    ContentMode,
    MailSummary,
    Provider,
)


SCHEMA_VERSION = 1


class IntegrationDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            current = db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()[0]
            if current < 1:
                self._migration_1(db)
                db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (1, _now()),
                )
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    f"NOVA integration database is newer than this code ({current} > {SCHEMA_VERSION})."
                )

    @staticmethod
    def _migration_1(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE accounts (
                account_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                label TEXT NOT NULL UNIQUE COLLATE NOCASE,
                category TEXT NOT NULL,
                principal_hint TEXT NOT NULL,
                services_json TEXT NOT NULL,
                content_mode TEXT NOT NULL,
                notifications_enabled INTEGER NOT NULL DEFAULT 1,
                important_only INTEGER NOT NULL DEFAULT 0,
                health TEXT NOT NULL,
                health_detail TEXT NOT NULL DEFAULT '',
                last_sync_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE mail_messages (
                provider TEXT NOT NULL,
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender_name TEXT NOT NULL DEFAULT '',
                sender_address TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL,
                is_read INTEGER NOT NULL,
                importance TEXT NOT NULL DEFAULT 'normal',
                web_link TEXT NOT NULL DEFAULT '',
                folder TEXT NOT NULL DEFAULT 'inbox',
                snippet TEXT NOT NULL DEFAULT '',
                notified INTEGER NOT NULL DEFAULT 0,
                deleted INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(provider, account_id, message_id),
                FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
            );
            CREATE INDEX mail_unread_idx ON mail_messages(account_id, is_read, deleted, received_at DESC);

            CREATE TABLE calendar_events (
                provider TEXT NOT NULL,
                account_id TEXT NOT NULL,
                calendar_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                occurrence_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                start_utc TEXT NOT NULL,
                end_utc TEXT NOT NULL,
                original_timezone TEXT NOT NULL DEFAULT 'UTC',
                all_day INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'busy',
                cancelled INTEGER NOT NULL DEFAULT 0,
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                location TEXT NOT NULL DEFAULT '',
                web_link TEXT NOT NULL DEFAULT '',
                meeting_link TEXT NOT NULL DEFAULT '',
                calendar_name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL,
                PRIMARY KEY(provider, account_id, calendar_id, event_id, occurrence_id),
                FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
            );
            CREATE INDEX calendar_range_idx ON calendar_events(start_utc, end_utc, cancelled);

            CREATE TABLE notification_receipts (
                provider TEXT NOT NULL,
                account_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                dispatched_at TEXT NOT NULL,
                PRIMARY KEY(provider, account_id, message_id),
                FOREIGN KEY(account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
            );

            CREATE TABLE settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                account_id TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            """
        )

    def upsert_account(self, account: ConnectedAccount) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO accounts(
                    account_id, provider, label, category, principal_hint,
                    services_json, content_mode, notifications_enabled,
                    important_only, health, health_detail, last_sync_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    provider=excluded.provider,
                    label=excluded.label,
                    category=excluded.category,
                    principal_hint=excluded.principal_hint,
                    services_json=excluded.services_json,
                    content_mode=excluded.content_mode,
                    notifications_enabled=excluded.notifications_enabled,
                    important_only=excluded.important_only,
                    health=excluded.health,
                    health_detail=excluded.health_detail,
                    last_sync_at=excluded.last_sync_at,
                    updated_at=excluded.updated_at
                """,
                (
                    account.account_id,
                    account.provider.value,
                    account.label,
                    account.category.value,
                    account.principal_hint,
                    json.dumps(list(account.enabled_services)),
                    account.content_mode.value,
                    int(account.notifications_enabled),
                    int(account.important_only),
                    account.health.value,
                    account.health_detail,
                    account.last_sync_at,
                    account.created_at,
                    _now(),
                ),
            )

    def list_accounts(self) -> list[ConnectedAccount]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM accounts ORDER BY label COLLATE NOCASE").fetchall()
        return [_row_to_account(row) for row in rows]

    def get_account(self, account_id_or_label: str) -> ConnectedAccount | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM accounts WHERE account_id = ? OR label = ? COLLATE NOCASE LIMIT 1",
                (account_id_or_label, account_id_or_label),
            ).fetchone()
        return _row_to_account(row) if row else None

    def set_account_health(
        self,
        account_id: str,
        health: AccountHealth,
        detail: str = "",
        *,
        synced: bool = False,
    ) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                UPDATE accounts
                SET health=?, health_detail=?, last_sync_at=CASE WHEN ? THEN ? ELSE last_sync_at END,
                    updated_at=?
                WHERE account_id=?
                """,
                (health.value, detail[:500], int(synced), _now(), _now(), account_id),
            )

    def delete_account(self, account_id: str) -> None:
        with self._lock, self.connection() as db:
            db.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))

    def upsert_mail(self, item: MailSummary, *, baseline: bool = False) -> tuple[bool, bool]:
        """Return (created, changed). Baseline messages are marked as already notified."""
        now = _now()
        with self._lock, self.connection() as db:
            existing = db.execute(
                "SELECT * FROM mail_messages WHERE provider=? AND account_id=? AND message_id=?",
                item.stable_key,
            ).fetchone()
            created = existing is None
            changed = created or any(
                [
                    existing["subject"] != item.subject,
                    existing["is_read"] != int(item.is_read),
                    existing["importance"] != item.importance,
                    existing["deleted"] != int(item.deleted),
                ]
            )
            db.execute(
                """
                INSERT INTO mail_messages(
                    provider, account_id, message_id, sender_name, sender_address,
                    subject, received_at, is_read, importance, web_link, folder,
                    snippet, notified, deleted, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, account_id, message_id) DO UPDATE SET
                    sender_name=excluded.sender_name,
                    sender_address=excluded.sender_address,
                    subject=excluded.subject,
                    received_at=excluded.received_at,
                    is_read=excluded.is_read,
                    importance=excluded.importance,
                    web_link=excluded.web_link,
                    folder=excluded.folder,
                    snippet=excluded.snippet,
                    deleted=excluded.deleted,
                    updated_at=excluded.updated_at
                """,
                (
                    item.provider.value,
                    item.account_id,
                    item.message_id,
                    item.sender_name[:300],
                    item.sender_address[:320],
                    item.subject[:1000],
                    item.received_at,
                    int(item.is_read),
                    item.importance[:50],
                    item.web_link[:2000],
                    item.folder[:100],
                    item.snippet[:500],
                    int(baseline),
                    int(item.deleted),
                    now,
                    now,
                ),
            )
        return created, changed

    def mark_mail_deleted(self, provider: Provider, account_id: str, message_id: str) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                "UPDATE mail_messages SET deleted=1, updated_at=? WHERE provider=? AND account_id=? AND message_id=?",
                (_now(), provider.value, account_id, message_id),
            )

    def should_notify(self, item: MailSummary) -> bool:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT notified, deleted FROM mail_messages
                WHERE provider=? AND account_id=? AND message_id=?
                """,
                item.stable_key,
            ).fetchone()
            receipt = db.execute(
                """
                SELECT 1 FROM notification_receipts
                WHERE provider=? AND account_id=? AND message_id=?
                """,
                item.stable_key,
            ).fetchone()
        return bool(row and not row["notified"] and not row["deleted"] and not receipt)

    def mark_notified(self, item: MailSummary) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                "UPDATE mail_messages SET notified=1, updated_at=? WHERE provider=? AND account_id=? AND message_id=?",
                (_now(), *item.stable_key),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO notification_receipts(provider, account_id, message_id, dispatched_at)
                VALUES (?, ?, ?, ?)
                """,
                (*item.stable_key, _now()),
            )

    def list_unread_mail(
        self,
        account_id: str | None = None,
        *,
        important_only: bool = False,
        limit: int = 10,
    ) -> list[MailSummary]:
        clauses = ["m.deleted=0", "m.is_read=0"]
        params: list[object] = []
        if account_id:
            clauses.append("m.account_id=?")
            params.append(account_id)
        if important_only:
            clauses.append("LOWER(m.importance) IN ('high', 'important')")
        params.append(max(1, min(int(limit), 100)))
        query = f"""
            SELECT m.* FROM mail_messages m
            WHERE {' AND '.join(clauses)}
            ORDER BY m.received_at DESC
            LIMIT ?
        """
        with self.connection() as db:
            rows = db.execute(query, params).fetchall()
        return [_row_to_mail(row) for row in rows]

    def get_mail(self, account_id: str, message_id: str) -> MailSummary | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT * FROM mail_messages WHERE account_id=? AND message_id=? AND deleted=0",
                (account_id, message_id),
            ).fetchone()
        return _row_to_mail(row) if row else None

    def unread_counts(self) -> dict[str, int]:
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT account_id, COUNT(*) AS count
                FROM mail_messages WHERE is_read=0 AND deleted=0
                GROUP BY account_id
                """
            ).fetchall()
        return {row["account_id"]: int(row["count"]) for row in rows}

    def upsert_event(self, item: CalendarEvent) -> tuple[bool, bool]:
        now = _now()
        with self._lock, self.connection() as db:
            existing = db.execute(
                """
                SELECT * FROM calendar_events
                WHERE provider=? AND account_id=? AND calendar_id=? AND event_id=? AND occurrence_id=?
                """,
                item.stable_key,
            ).fetchone()
            created = existing is None
            changed = created or any(
                [
                    existing["title"] != item.title,
                    existing["start_utc"] != item.start_utc,
                    existing["end_utc"] != item.end_utc,
                    existing["cancelled"] != int(item.cancelled),
                    existing["status"] != item.status,
                ]
            )
            db.execute(
                """
                INSERT INTO calendar_events(
                    provider, account_id, calendar_id, event_id, occurrence_id,
                    title, start_utc, end_utc, original_timezone, all_day, status,
                    cancelled, sensitivity, location, web_link, meeting_link,
                    calendar_name, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, account_id, calendar_id, event_id, occurrence_id) DO UPDATE SET
                    title=excluded.title,
                    start_utc=excluded.start_utc,
                    end_utc=excluded.end_utc,
                    original_timezone=excluded.original_timezone,
                    all_day=excluded.all_day,
                    status=excluded.status,
                    cancelled=excluded.cancelled,
                    sensitivity=excluded.sensitivity,
                    location=excluded.location,
                    web_link=excluded.web_link,
                    meeting_link=excluded.meeting_link,
                    calendar_name=excluded.calendar_name,
                    updated_at=excluded.updated_at
                """,
                (
                    item.provider.value,
                    item.account_id,
                    item.calendar_id,
                    item.event_id,
                    item.occurrence_id,
                    item.title[:1000],
                    item.start_utc,
                    item.end_utc,
                    item.original_timezone[:100],
                    int(item.all_day),
                    item.status[:50],
                    int(item.cancelled),
                    item.sensitivity[:50],
                    item.location[:1000],
                    item.web_link[:2000],
                    item.meeting_link[:2000],
                    item.calendar_name[:300],
                    now,
                ),
            )
        return created, changed

    def delete_events_by_remote_id(
        self,
        provider: Provider,
        account_id: str,
        calendar_id: str,
        event_id: str,
    ) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                DELETE FROM calendar_events
                WHERE provider=? AND account_id=? AND calendar_id=? AND event_id=?
                """,
                (provider.value, account_id, calendar_id, event_id),
            )

    def delete_event_key(
        self,
        provider: Provider,
        account_id: str,
        calendar_id: str,
        event_id: str,
        occurrence_id: str,
    ) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                DELETE FROM calendar_events
                WHERE provider=? AND account_id=? AND calendar_id=? AND event_id=? AND occurrence_id=?
                """,
                (provider.value, account_id, calendar_id, event_id, occurrence_id),
            )

    def list_events(
        self,
        start_utc: str,
        end_utc: str,
        account_ids: Iterable[str] | None = None,
        *,
        include_cancelled: bool = False,
    ) -> list[CalendarEvent]:
        clauses = ["end_utc > ?", "start_utc < ?"]
        params: list[object] = [start_utc, end_utc]
        account_ids = tuple(account_ids or ())
        if account_ids:
            placeholders = ",".join("?" for _ in account_ids)
            clauses.append(f"account_id IN ({placeholders})")
            params.extend(account_ids)
        if not include_cancelled:
            clauses.append("cancelled=0")
        query = f"SELECT * FROM calendar_events WHERE {' AND '.join(clauses)} ORDER BY start_utc, end_utc"
        with self.connection() as db:
            rows = db.execute(query, params).fetchall()
        return [_row_to_event(row) for row in rows]

    def set_setting(self, key: str, value: object) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value), _now()),
            )

    def get_setting(self, key: str, default: object = None) -> object:
        with self.connection() as db:
            row = db.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def audit(
        self,
        event_type: str,
        *,
        account_id: str = "",
        provider: str = "",
        status: str = "ok",
        detail: str = "",
    ) -> None:
        # Never pass bodies, tokens, or raw exception traces into detail.
        safe_detail = " ".join(detail.replace("\n", " ").split())[:500]
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO audit_events(event_type, account_id, provider, status, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (event_type, account_id, provider, status, safe_detail, _now()),
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_account(row: sqlite3.Row) -> ConnectedAccount:
    return ConnectedAccount(
        account_id=row["account_id"],
        provider=Provider(row["provider"]),
        label=row["label"],
        category=AccountCategory(row["category"]),
        principal_hint=row["principal_hint"],
        enabled_services=tuple(json.loads(row["services_json"])),
        content_mode=ContentMode(row["content_mode"]),
        notifications_enabled=bool(row["notifications_enabled"]),
        important_only=bool(row["important_only"]),
        health=AccountHealth(row["health"]),
        health_detail=row["health_detail"],
        last_sync_at=row["last_sync_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_mail(row: sqlite3.Row) -> MailSummary:
    return MailSummary(
        provider=Provider(row["provider"]),
        account_id=row["account_id"],
        message_id=row["message_id"],
        sender_name=row["sender_name"],
        sender_address=row["sender_address"],
        subject=row["subject"],
        received_at=row["received_at"],
        is_read=bool(row["is_read"]),
        importance=row["importance"],
        web_link=row["web_link"],
        folder=row["folder"],
        snippet=row["snippet"],
        deleted=bool(row["deleted"]),
    )


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        provider=Provider(row["provider"]),
        account_id=row["account_id"],
        calendar_id=row["calendar_id"],
        event_id=row["event_id"],
        occurrence_id=row["occurrence_id"],
        title=row["title"],
        start_utc=row["start_utc"],
        end_utc=row["end_utc"],
        original_timezone=row["original_timezone"],
        all_day=bool(row["all_day"]),
        status=row["status"],
        cancelled=bool(row["cancelled"]),
        sensitivity=row["sensitivity"],
        location=row["location"],
        web_link=row["web_link"],
        meeting_link=row["meeting_link"],
        calendar_name=row["calendar_name"],
    )
