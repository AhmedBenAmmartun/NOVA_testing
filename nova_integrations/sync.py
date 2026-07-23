"""Incremental synchronization coordinator with notification deduplication."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .accounts import AccountRegistry
from .connectors import (
    AdminApprovalRequired,
    ConnectorError,
    RateLimited,
    ReconnectRequired,
    WorkspaceConnector,
)
from .events import EventWriter
from .models import AccountHealth, IntegrationEvent, Provider, SyncResult
from .notifications import NotificationDispatcher
from .storage import IntegrationDatabase


logger = logging.getLogger("nova.integrations.sync")


class SyncCoordinator:
    def __init__(
        self,
        database: IntegrationDatabase,
        accounts: AccountRegistry,
        connectors: Mapping[Provider, WorkspaceConnector],
        notifications: NotificationDispatcher,
        events: EventWriter,
    ) -> None:
        self.database = database
        self.accounts = accounts
        self.connectors = dict(connectors)
        self.notifications = notifications
        self.events = events

    def sync_all(self) -> list[SyncResult]:
        results: list[SyncResult] = []
        for account in self.accounts.list():
            results.extend(self.sync_account(account.account_id))
        return results

    def sync_account(self, account_id_or_label: str) -> list[SyncResult]:
        account = self.accounts.resolve(account_id_or_label)
        connector = self.connectors[account.provider]
        results: list[SyncResult] = []
        try:
            if "mail" in account.enabled_services:
                batch = connector.sync_mail(account)
                result = SyncResult(
                    provider=account.provider,
                    account_id=account.account_id,
                    resource="mail",
                    cursor_reset=batch.cursor_reset,
                )
                for message_id in batch.removed_ids:
                    self.database.mark_mail_deleted(account.provider, account.account_id, message_id)
                    result.deleted += 1
                for item in batch.items:
                    created, changed = self.database.upsert_mail(item, baseline=batch.baseline)
                    result.added += int(created)
                    result.updated += int(changed and not created)
                    if created and not batch.baseline and self.notifications.dispatch(account, item):
                        result.notifications += 1
                results.append(result)

            if "calendar" in account.enabled_services:
                batch = connector.sync_calendar(account)
                result = SyncResult(
                    provider=account.provider,
                    account_id=account.account_id,
                    resource="calendar",
                    cursor_reset=batch.cursor_reset,
                )
                for calendar_id, event_id, occurrence_id in batch.removed_keys:
                    if occurrence_id:
                        self.database.delete_event_key(
                            account.provider,
                            account.account_id,
                            calendar_id,
                            event_id,
                            occurrence_id,
                        )
                    else:
                        self.database.delete_events_by_remote_id(
                            account.provider,
                            account.account_id,
                            calendar_id,
                            event_id,
                        )
                    result.deleted += 1
                for item in batch.items:
                    created, changed = self.database.upsert_event(item)
                    result.added += int(created)
                    result.updated += int(changed and not created)
                results.append(result)

            self.database.set_account_health(
                account.account_id,
                AccountHealth.CONNECTED,
                "",
                synced=True,
            )
            self.database.audit(
                "sync_completed",
                account_id=account.account_id,
                provider=account.provider.value,
                detail="; ".join(
                    f"{item.resource}: +{item.added} ~{item.updated} -{item.deleted} notify={item.notifications}"
                    for item in results
                ),
            )
            self.events.emit(
                IntegrationEvent(
                    event_type="integration_sync_completed",
                    account_id=account.account_id,
                    provider=account.provider.value,
                    title=f"{account.label} synchronized",
                    message="Mail and calendar metadata are current.",
                )
            )
            return results
        except AdminApprovalRequired as exc:
            self._failure(account, AccountHealth.ADMIN_APPROVAL_REQUIRED, str(exc))
        except ReconnectRequired as exc:
            self._failure(account, AccountHealth.NEEDS_RECONNECT, str(exc))
        except RateLimited:
            # Preserve connected status; the supervisor applies bounded backoff.
            raise
        except ConnectorError as exc:
            self._failure(account, AccountHealth.ERROR, str(exc))
        except Exception:
            logger.exception("Unexpected integration synchronization failure for %s", account.account_id)
            self._failure(account, AccountHealth.ERROR, "Unexpected synchronization error; private response content was not logged.")
        return results

    def _failure(self, account, health: AccountHealth, detail: str) -> None:
        self.database.set_account_health(account.account_id, health, detail)
        self.database.audit(
            "sync_failed",
            account_id=account.account_id,
            provider=account.provider.value,
            status=health.value,
            detail=detail,
        )
        self.events.emit(
            IntegrationEvent(
                event_type="integration_sync_failed",
                account_id=account.account_id,
                provider=account.provider.value,
                title=f"{account.label} needs attention",
                message=detail,
                severity="warning",
            )
        )
