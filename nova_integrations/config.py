"""Configuration loader. No OAuth tokens or mailbox content belong here."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def local_data_root() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if base:
        return Path(base) / "NOVA" / "integrations"
    return Path.home() / ".local" / "share" / "NOVA" / "integrations"


@dataclass(slots=True)
class GoogleConfig:
    client_config_path: str = ""


@dataclass(slots=True)
class MicrosoftConfig:
    client_id: str = ""
    authority: str = "https://login.microsoftonline.com/common"


@dataclass(slots=True)
class SyncConfig:
    interval_seconds: int = 180
    initial_mail_limit: int = 50
    calendar_past_days: int = 30
    calendar_future_days: int = 365
    max_backoff_seconds: int = 900


@dataclass(slots=True)
class NotificationConfig:
    enabled: bool = True
    hide_content: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    suppress_bulk: bool = True


@dataclass(slots=True)
class IntegrationConfig:
    data_root: Path = field(default_factory=local_data_root)
    database_path: Path = field(default_factory=lambda: local_data_root() / "nova_integrations.db")
    event_log_path: Path = field(default_factory=lambda: local_data_root() / "events.jsonl")
    google: GoogleConfig = field(default_factory=GoogleConfig)
    microsoft: MicrosoftConfig = field(default_factory=MicrosoftConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    local_timezone: str = "America/New_York"

    def ensure_directories(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)


def _deep_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def load_config(path: str | Path | None = None) -> IntegrationConfig:
    default_path = local_data_root() / "config.json"
    selected = Path(path or os.getenv("NOVA_INTEGRATIONS_CONFIG", "") or default_path)
    data: dict[str, Any] = {}
    if selected.exists():
        data = json.loads(selected.read_text(encoding="utf-8"))

    root = Path(data.get("data_root") or local_data_root()).expanduser()
    config = IntegrationConfig(
        data_root=root,
        database_path=Path(data.get("database_path") or root / "nova_integrations.db").expanduser(),
        event_log_path=Path(data.get("event_log_path") or root / "events.jsonl").expanduser(),
        google=GoogleConfig(
            client_config_path=str(_deep_get(data, "google", "client_config_path", default="")),
        ),
        microsoft=MicrosoftConfig(
            client_id=str(_deep_get(data, "microsoft", "client_id", default="")),
            authority=str(
                _deep_get(
                    data,
                    "microsoft",
                    "authority",
                    default="https://login.microsoftonline.com/common",
                )
            ),
        ),
        sync=SyncConfig(
            interval_seconds=int(_deep_get(data, "sync", "interval_seconds", default=180)),
            initial_mail_limit=int(_deep_get(data, "sync", "initial_mail_limit", default=50)),
            calendar_past_days=int(_deep_get(data, "sync", "calendar_past_days", default=30)),
            calendar_future_days=int(_deep_get(data, "sync", "calendar_future_days", default=365)),
            max_backoff_seconds=int(_deep_get(data, "sync", "max_backoff_seconds", default=900)),
        ),
        notifications=NotificationConfig(
            enabled=bool(_deep_get(data, "notifications", "enabled", default=True)),
            hide_content=bool(_deep_get(data, "notifications", "hide_content", default=False)),
            quiet_hours_start=str(_deep_get(data, "notifications", "quiet_hours_start", default="22:00")),
            quiet_hours_end=str(_deep_get(data, "notifications", "quiet_hours_end", default="07:00")),
            suppress_bulk=bool(_deep_get(data, "notifications", "suppress_bulk", default=True)),
        ),
        local_timezone=str(data.get("local_timezone") or "America/New_York"),
    )
    config.ensure_directories()
    return config
