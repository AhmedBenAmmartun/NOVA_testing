"""Lazy construction of integration services and connectors."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .accounts import AccountRegistry
from .config import IntegrationConfig, load_config
from .connectors import GoogleWorkspaceConnector, MicrosoftGraphConnector
from .events import EventWriter
from .models import Provider
from .notifications import NotificationDispatcher, Notifier
from .secrets import KeyringSecretStore, SecretStore
from .services import BriefingService, CalendarService, MailService
from .storage import IntegrationDatabase
from .supervisor import IntegrationSupervisor
from .sync import SyncCoordinator


@dataclass(slots=True)
class IntegrationRuntime:
    config: IntegrationConfig
    database: IntegrationDatabase
    secrets: SecretStore
    accounts: AccountRegistry
    connectors: dict
    notifications: NotificationDispatcher
    events: EventWriter
    sync: SyncCoordinator
    mail: MailService
    calendar: CalendarService
    briefing: BriefingService
    supervisor: IntegrationSupervisor


_runtime: IntegrationRuntime | None = None
_runtime_lock = RLock()


def build_runtime(
    config: IntegrationConfig | None = None,
    *,
    secrets: SecretStore | None = None,
    notifier: Notifier | None = None,
) -> IntegrationRuntime:
    config = config or load_config()
    database = IntegrationDatabase(config.database_path)
    secrets = secrets or KeyringSecretStore()
    accounts = AccountRegistry(database, secrets)
    events = EventWriter(config.event_log_path)
    notifications = NotificationDispatcher(config, database, notifier=notifier)
    google = GoogleWorkspaceConnector(config, accounts, secrets)
    microsoft = MicrosoftGraphConnector(config, accounts, secrets)
    connectors = {
        Provider.GOOGLE: google,
        Provider.MICROSOFT: microsoft,
    }
    sync = SyncCoordinator(database, accounts, connectors, notifications, events)
    mail = MailService(database, accounts)
    calendar = CalendarService(database, accounts, config.local_timezone)
    briefing = BriefingService(mail, calendar, accounts)
    supervisor = IntegrationSupervisor(
        sync,
        interval_seconds=config.sync.interval_seconds,
        max_backoff_seconds=config.sync.max_backoff_seconds,
    )
    return IntegrationRuntime(
        config=config,
        database=database,
        secrets=secrets,
        accounts=accounts,
        connectors=connectors,
        notifications=notifications,
        events=events,
        sync=sync,
        mail=mail,
        calendar=calendar,
        briefing=briefing,
        supervisor=supervisor,
    )


def get_runtime() -> IntegrationRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = build_runtime()
        return _runtime


def start_integration_supervisor() -> IntegrationSupervisor:
    supervisor = get_runtime().supervisor
    supervisor.start()
    return supervisor


def stop_integration_supervisor() -> None:
    with _runtime_lock:
        if _runtime is not None:
            _runtime.supervisor.stop()
