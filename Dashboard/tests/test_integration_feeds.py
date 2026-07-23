from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nova_integrations.models import (
    AccountCategory,
    AccountHealth,
    CalendarEvent,
    ConnectedAccount,
    ContentMode,
    MailSummary,
    Provider,
)
from nova_integrations.storage import IntegrationDatabase

from Dashboard import integration_feeds


class IntegrationFeedsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "config.json"
        self.db_path = self.root / "nova_integrations.db"
        self.events_path = self.root / "events.jsonl"
        self.config_path.write_text(
            json.dumps(
                {
                    "local_timezone": "America/New_York",
                    "database_path": str(self.db_path),
                    "event_log_path": str(self.events_path),
                }
            ),
            encoding="utf-8",
        )
        self.env = patch.dict(os.environ, {"NOVA_INTEGRATIONS_CONFIG": str(self.config_path)})
        self.env.start()
        self.db = IntegrationDatabase(self.db_path)
        self.account = ConnectedAccount(
            account_id="go_demo",
            provider=Provider.GOOGLE,
            label="Personal Gmail",
            category=AccountCategory.PERSONAL,
            principal_hint="ah***@gmail.com",
            enabled_services=("calendar", "mail"),
            content_mode=ContentMode.METADATA_ONLY,
            health=AccountHealth.CONNECTED,
        )
        self.db.upsert_account(self.account)

    def tearDown(self) -> None:
        self.env.stop()
        self.temp.cleanup()

    def test_status_and_mail_are_local_metadata_only(self) -> None:
        now = datetime.now(timezone.utc)
        self.db.upsert_mail(
            MailSummary(
                provider=Provider.GOOGLE,
                account_id=self.account.account_id,
                message_id="msg-1",
                sender_name="FGCU Advising",
                sender_address="advisor@example.edu",
                subject="Graduation review",
                received_at=now.isoformat(),
                is_read=False,
            )
        )
        status = integration_feeds.status_message()
        mail = integration_feeds.mail_message()
        self.assertEqual(status["status"], "connected")
        self.assertEqual(status["totalUnread"], 1)
        self.assertEqual(mail["totalUnread"], 1)
        self.assertEqual(mail["items"][0]["subject"], "Graduation review")
        self.assertNotIn("body", mail["items"][0])

    def test_calendar_payload_builds_month_and_upcoming(self) -> None:
        local_now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
        start = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
        self.db.upsert_event(
            CalendarEvent(
                provider=Provider.GOOGLE,
                account_id=self.account.account_id,
                calendar_id="primary",
                event_id="event-1",
                occurrence_id="event-1",
                title="Hackathon demo recording",
                start_utc=start.isoformat(),
                end_utc=(start + timedelta(hours=1)).isoformat(),
                original_timezone="America/New_York",
                calendar_name="Personal",
            )
        )
        payload = integration_feeds.calendar_message(now=local_now)
        self.assertEqual(payload["status"], "connected", msg=f"Calendar payload: {payload!r}")
        self.assertEqual(payload["monthTitle"], "July 2026")
        self.assertEqual(payload["events"][0]["title"], "Hackathon demo recording")
        self.assertEqual(payload["upcoming"][0]["account"], "Personal Gmail")

    def test_event_tail_forwards_only_safe_event_fields(self) -> None:
        self.events_path.write_text("", encoding="utf-8")
        tail = integration_feeds.IntegrationEventTail(self.events_path, from_start=True)
        tail.read_new()
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "event_type": "integration_sync_completed",
                "title": "Personal Gmail synchronized",
                "message": "Mail and calendar metadata are current.",
                "secret": "must-not-be-forwarded",
            }) + "\n")
        event = tail.read_new()[0]
        message = integration_feeds.event_to_dashboard(event)
        self.assertEqual(message["type"], "notify")
        self.assertNotIn("secret", message)


if __name__ == "__main__":
    unittest.main()
