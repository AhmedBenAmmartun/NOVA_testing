"""Observable local NOVA status for the desktop skin."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - optional runtime dependency
    psutil = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = PROJECT_ROOT / "nova_tools.log"
CONVERSATION_DIR = PROJECT_ROOT / "conversation_logs"
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(slots=True)
class LocalSnapshot:
    now: str
    date: str
    cpu: str
    ram: str
    battery: str
    network: str
    voice_status: str
    voice_detail: str
    vault_status: str
    latest_conversation: str
    latest_tool_events: tuple[str, ...]
    current_focus: str
    profile: str
    command_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_env_value(name: str) -> str | None:
    """Read one non-secret configuration path without printing its value."""
    if not ENV_PATH.exists():
        return None
    try:
        for line in ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _safe_log_line(line: str) -> str:
    clean = " ".join(line.strip().split())
    lowered = clean.lower()
    blocked = (".env", "api key", "apikey", "bearer ", "password", "secret", "token")
    if any(marker in lowered for marker in blocked):
        return "Protected event hidden"
    return clean[:180]


def _latest_tool_events(path: Path, limit: int = 3, max_bytes: int = 24_000) -> tuple[str, ...]:
    if not path.exists():
        return ("No tool activity yet",)
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ("Tool log unavailable",)

    events: list[str] = []
    for raw in reversed(text.splitlines()):
        clean = _safe_log_line(raw)
        if clean:
            events.append(clean)
        if len(events) >= limit:
            break
    return tuple(events) or ("No tool activity yet",)


def _latest_conversation(root: Path) -> str:
    if not root.exists():
        return "No saved conversation yet"
    try:
        latest = max(root.rglob("*.md"), key=lambda item: item.stat().st_mtime)
        relative = latest.relative_to(root)
        return str(relative).replace("\\", "/")[:92]
    except (OSError, ValueError):
        return "Conversation history unavailable"


def _voice_process() -> tuple[str, str]:
    if psutil is None:
        return "unknown", "Process status unavailable"
    try:
        for process in psutil.process_iter(["name", "cmdline"]):
            command = " ".join(process.info.get("cmdline") or []).lower()
            if "agent.py console" in command or "agent.py dev" in command:
                return "running", "NOVA voice process detected"
    except Exception:
        return "unknown", "Process status unavailable"
    return "offline", "Voice session is not running"


def _system_values() -> tuple[str, str, str, str]:
    if psutil is None:
        return "n/a", "n/a", "n/a", "unknown"
    try:
        cpu = f"{psutil.cpu_percent(interval=None):.0f}%"
        ram = f"{psutil.virtual_memory().percent:.0f}%"
        battery_info = psutil.sensors_battery()
        if battery_info is None:
            battery = "n/a"
        else:
            suffix = " charging" if battery_info.power_plugged else ""
            battery = f"{battery_info.percent:.0f}%{suffix}"
        interfaces = psutil.net_if_stats()
        network = "connected" if any(item.isup for item in interfaces.values()) else "offline"
        return cpu, ram, battery, network
    except Exception:
        return "n/a", "n/a", "n/a", "unknown"


class LocalStatusService:
    """Poll local state and expose only safe, observable dashboard data."""

    def snapshot(
        self,
        *,
        current_focus: str = "",
        profile: str = "focus",
        command_status: str = "Ready for safe commands",
    ) -> LocalSnapshot:
        cpu, ram, battery, network = _system_values()
        voice_status, voice_detail = _voice_process()
        vault_value = _read_env_value("OBSIDIAN_VAULT_PATH")
        if not vault_value:
            vault_status = "Vault not configured"
        elif Path(vault_value).is_dir():
            vault_status = "Vault connected"
        else:
            vault_status = "Vault path missing"

        now = datetime.now()
        return LocalSnapshot(
            now=now.strftime("%I:%M").lstrip("0"),
            date=now.strftime("%a, %b %d"),
            cpu=cpu,
            ram=ram,
            battery=battery,
            network=network,
            voice_status=voice_status,
            voice_detail=voice_detail,
            vault_status=vault_status,
            latest_conversation=_latest_conversation(CONVERSATION_DIR),
            latest_tool_events=_latest_tool_events(LOG_PATH),
            current_focus=current_focus.strip() or "No active focus",
            profile=profile,
            command_status=command_status,
        )
