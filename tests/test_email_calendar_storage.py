from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nova_integrations.accounts import AccountRegistry
from nova_integrations.models import (
    AccountCategory,
    CalendarEvent,
    ConnectedAccount,
    ContentMode,
    MailSummary,
    Provider,
)
from nova_integrations.secrets import MemorySecretStore, get_cursor, set_cursor
from nova_integrations.services import CalendarService
from nova_integrations.storage import IntegrationDatabase


class StorageIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = IntegrationDatabase(Path(self.temp.name) / "integrations.db")
        self.secrets = MemorySecretStore()
        self.registry = AccountRegistry(self.db, self.secrets)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _account(self, account_id: str, label: str) -> ConnectedAccount:
        account = ConnectedAccount(
            account_id=account_id,
            provider=Provider.MICROSOFT,
            label=label,
            category=AccountCategory.SCHOOL if "School" in label else AccountCategory.WORK,
            principal_hint="ah***@fgcu.edu",
            enabled_services=("mail", "calendar"),
            content_mode=ContentMode.METADATA_ONLY,
        )
        self.registry.add(account, f"oauth-cache-{account_id}")
        return account

    def test_multiple_microsoft_accounts_remain_isolated(self) -> None:
        school = self._account("ms_school", "FGCU School")
        work = self._account("ms_work", "FGCU Work")
        for account, message_id in ((school, "school-message"), (work, "work-message")):
            self.db.upsert_mail(
                MailSummary(
                    provider=Provider.MICROSOFT,
                    account_id=account.account_id,
                    message_id=message_id,
                    sender_name="Sender",
                    sender_address="sender@example.com",
                    subject="Test",
                    received_at=datetime.now(timezone.utc).isoformat(),
                    is_read=False,
                )
            )

        self.assertEqual(len(self.db.list_unread_mail(school.account_id)), 1)
        self.assertEqual(len(self.db.list_unread_mail(work.account_id)), 1)
        self.registry.disconnect(school.account_id)
        self.assertIsNone(self.db.get_account(school.account_id))
        self.assertIsNotNone(self.db.get_account(work.account_id))
        self.assertEqual(len(self.db.list_unread_mail(work.account_id)), 1)

    def test_calendar_sort_conflicts_all_day_and_cancelled(self) -> None:
        school = self._account("ms_school", "FGCU School")
        work = self._account("ms_work", "FGCU Work")
        base = datetime(2026, 7, 22, 13, 0, tzinfo=timezone.utc)
        events = [
            CalendarEvent(
                provider=Provider.MICROSOFT,
                account_id=school.account_id,
                calendar_id="school-cal",
                event_id="class",
                occurrence_id="2026-07-22T13:00:00Z",
                title="Class",
                start_utc=base.isoformat(),
                end_utc=(base + timedelta(hours=1)).isoformat(),
                original_timezone="UTC",
                calendar_name="School",
            ),
            CalendarEvent(
                provider=Provider.MICROSOFT,
                account_id=work.account_id,
                calendar_id="work-cal",
                event_id="shift",
                occurrence_id="2026-07-22T13:30:00Z",
                title="Shift",
                start_utc=(base + timedelta(minutes=30)).isoformat(),
                end_utc=(base + timedelta(hours=2)).isoformat(),
                original_timezone="UTC",
                calendar_name="Work",
            ),
            CalendarEvent(
                provider=Provider.MICROSOFT,
                account_id=school.account_id,
                calendar_id="school-cal",
                event_id="all-day",
                occurrence_id="2026-07-22",
                title="All day",
                start_utc=base.replace(hour=4).isoformat(),
                end_utc=(base.replace(hour=4) + timedelta(days=1)).isoformat(),
                original_timezone="America/New_York",
                all_day=True,
            ),
            CalendarEvent(
                provider=Provider.MICROSOFT,
                account_id=school.account_id,
                calendar_id="school-cal",
                event_id="cancelled",
                occurrence_id="cancelled",
                title="Cancelled",
                start_utc=(base + timedelta(hours=3)).isoformat(),
                end_utc=(base + timedelta(hours=4)).isoformat(),
                original_timezone="UTC",
                cancelled=True,
            ),
        ]
        for event in events:
            self.db.upsert_event(event)

        service = CalendarService(self.db, self.registry, "America/New_York")
        entries = service.date_range(base - timedelta(days=1), base + timedelta(days=2))
        self.assertEqual([event.event_id for _, event in entries], ["all-day", "class", "shift"])
        conflicts = service.conflicts(base - timedelta(hours=1), base + timedelta(hours=4))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].overlap_minutes, 30)

    def test_notification_policy_can_be_changed_per_account(self) -> None:
        school = self._account("ms_school", "FGCU School")
        updated = self.registry.update_notifications(
            school.account_id, enabled=False, important_only=True
        )
        self.assertFalse(updated.notifications_enabled)
        self.assertTrue(updated.important_only)
        persisted = self.registry.resolve(school.account_id)
        self.assertFalse(persisted.notifications_enabled)
        self.assertTrue(persisted.important_only)

    def test_disconnect_removes_all_indexed_sync_cursors(self) -> None:
        school = self._account("ms_school", "FGCU School")
        set_cursor(self.secrets, school.provider.value, school.account_id, "mail", "mail-delta")
        set_cursor(self.secrets, school.provider.value, school.account_id, "calendar:classes", "calendar-delta")

        self.registry.disconnect(school.account_id)

        self.assertIsNone(get_cursor(self.secrets, school.provider.value, school.account_id, "mail"))
        self.assertIsNone(
            get_cursor(self.secrets, school.provider.value, school.account_id, "calendar:classes")
        )

    def test_database_schema_has_no_body_or_token_columns(self) -> None:
        with self.db.connection() as connection:
            mail_columns = {row[1] for row in connection.execute("PRAGMA table_info(mail_messages)")}
            account_columns = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
        self.assertNotIn("body", mail_columns)
        self.assertNotIn("access_token", account_columns)
        self.assertNotIn("refresh_token", account_columns)


if __name__ == "__main__":
    unittest.main()
