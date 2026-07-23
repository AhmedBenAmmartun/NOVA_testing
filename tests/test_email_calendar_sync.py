from __future__ import annotations

import tempfile
import unittest
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from nova_integrations.accounts import AccountRegistry
from nova_integrations.config import IntegrationConfig, NotificationConfig, SyncConfig
from nova_integrations.connectors.base import (
    AdminApprovalRequired,
    CalendarSyncBatch,
    MailSyncBatch,
    WorkspaceConnector,
)
from nova_integrations.events import EventWriter
from nova_integrations.models import (
    AccountCategory,
    AccountHealth,
    ConnectedAccount,
    ContentMode,
    MailSummary,
    Provider,
)
from nova_integrations.notifications import NotificationDispatcher
from nova_integrations.secrets import MemorySecretStore
from nova_integrations.storage import IntegrationDatabase
from nova_integrations.sync import SyncCoordinator


class RecordingNotifier:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, str]] = []

    def send(self, title: str, message: str, *, launch_url: str = "") -> bool:
        self.messages.append((title, message, launch_url))
        return True


class FakeConnector(WorkspaceConnector):
    provider = Provider.MICROSOFT

    def __init__(self, batches=None, error: Exception | None = None) -> None:
        self.batches = deque(batches or [])
        self.error = error

    def connect(self, **kwargs):
        raise NotImplementedError

    def test_account(self, account):
        return "ok"

    def sync_mail(self, account):
        if self.error:
            raise self.error
        return self.batches.popleft() if self.batches else MailSyncBatch()

    def sync_calendar(self, account):
        return CalendarSyncBatch()

    def fetch_message_body(self, account, message_id):
        return "body"


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = IntegrationConfig(
            data_root=root,
            database_path=root / "db.sqlite",
            event_log_path=root / "events.jsonl",
            sync=SyncConfig(interval_seconds=60),
            notifications=NotificationConfig(
                enabled=True,
                hide_content=False,
                quiet_hours_start="00:00",
                quiet_hours_end="00:00",
                suppress_bulk=False,
            ),
        )
        self.db = IntegrationDatabase(self.config.database_path)
        self.secrets = MemorySecretStore()
        self.registry = AccountRegistry(self.db, self.secrets)
        self.account = ConnectedAccount(
            account_id="ms_personal",
            provider=Provider.MICROSOFT,
            label="Personal Outlook",
            category=AccountCategory.PERSONAL,
            principal_hint="ah***@outlook.com",
            enabled_services=("mail",),
            content_mode=ContentMode.CLOUD_ALLOWED,
        )
        self.registry.add(self.account, "fake-cache")
        self.notifier = RecordingNotifier()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _mail(self, message_id: str) -> MailSummary:
        return MailSummary(
            provider=Provider.MICROSOFT,
            account_id=self.account.account_id,
            message_id=message_id,
            sender_name="Test Sender",
            sender_address="sender@example.com",
            subject="Test subject",
            received_at=datetime.now(timezone.utc).isoformat(),
            is_read=False,
            web_link=f"https://outlook.office.com/mail/inbox/id/{message_id}",
        )

    def _coordinator(self, connector: WorkspaceConnector) -> SyncCoordinator:
        return SyncCoordinator(
            self.db,
            self.registry,
            {Provider.MICROSOFT: connector},
            NotificationDispatcher(self.config, self.db, self.notifier),
            EventWriter(self.config.event_log_path),
        )

    def test_initial_sync_suppresses_history_then_one_new_notification(self) -> None:
        old = self._mail("old")
        new = self._mail("new")
        connector = FakeConnector(
            [
                MailSyncBatch(items=[old], baseline=True),
                MailSyncBatch(items=[new], baseline=False),
                MailSyncBatch(items=[new], baseline=False),
            ]
        )
        coordinator = self._coordinator(connector)
        first = coordinator.sync_account(self.account.account_id)[0]
        second = coordinator.sync_account(self.account.account_id)[0]
        third = coordinator.sync_account(self.account.account_id)[0]
        self.assertEqual(first.notifications, 0)
        self.assertEqual(second.notifications, 1)
        self.assertEqual(third.notifications, 0)
        self.assertEqual(len(self.notifier.messages), 1)

        # Reopening the same database simulates a restart; receipt dedup remains.
        reopened = IntegrationDatabase(self.config.database_path)
        notifier_after_restart = RecordingNotifier()
        coordinator_after_restart = SyncCoordinator(
            reopened,
            AccountRegistry(reopened, self.secrets),
            {Provider.MICROSOFT: FakeConnector([MailSyncBatch(items=[new], baseline=False)])},
            NotificationDispatcher(self.config, reopened, notifier_after_restart),
            EventWriter(self.config.event_log_path),
        )
        coordinator_after_restart.sync_account(self.account.account_id)
        self.assertEqual(notifier_after_restart.messages, [])

    def test_cursor_reset_is_reported_without_notification_storm(self) -> None:
        connector = FakeConnector(
            [MailSyncBatch(items=[self._mail("baseline-after-reset")], baseline=True, cursor_reset=True)]
        )
        result = self._coordinator(connector).sync_account(self.account.account_id)[0]
        self.assertTrue(result.cursor_reset)
        self.assertEqual(result.notifications, 0)

    def test_admin_consent_failure_becomes_account_health(self) -> None:
        connector = FakeConnector(error=AdminApprovalRequired("Tenant approval required"))
        results = self._coordinator(connector).sync_account(self.account.account_id)
        self.assertEqual(results, [])
        account = self.db.get_account(self.account.account_id)
        self.assertEqual(account.health, AccountHealth.ADMIN_APPROVAL_REQUIRED)
        self.assertIn("approval", account.health_detail.lower())


if __name__ == "__main__":
    unittest.main()
