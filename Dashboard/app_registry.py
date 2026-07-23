"""Trusted Windows application registry for the NOVA dashboard.

The browser receives opaque IDs and display metadata only.  Executable paths,
AUMIDs, shortcuts, and process details stay inside this Python process.
"""
from __future__ import annotations

import time

import ctypes
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import psutil

try:
    from app_icons import icon_data_uri, save_cache as save_icon_cache
except Exception:  # pragma: no cover - optional on non-Windows hosts
    def icon_data_uri(*_args, **_kwargs):
        return None

    def save_icon_cache():
        return None

from security import is_sensitive_name, is_sensitive_path, resolve_shortcut_targets

PIN_FILE = Path.home() / ".nova" / "dashboard_apps.json"
APP_DISPLAY_RENAMES = {
    "Google Chrome": "Chrome",
    "Visual Studio Code": "VS Code",
    "Windows Terminal": "Terminal",
    "Python 3.14 (64-bit)": "Python 3.14",
}
APP_SKIP_WORDS = ("uninstall", "readme", "documentation", "website", "release notes", "repair")
DEFAULT_PIN_NAMES = ["Chrome", "VS Code", "Claude", "ChatGPT", "Obsidian", "Terminal", "Spotify", "File Explorer"]
VALID_ACTIONS = {"activate", "launch", "focus", "minimize", "maximize", "restore", "close"}
KNOWN_PROCESSES = {
    "Chrome": ("chrome.exe",),
    "VS Code": ("code.exe",),
    "Claude": ("claude.exe",),
    "ChatGPT": ("chatgpt.exe",),
    "Obsidian": ("obsidian.exe",),
    "Terminal": ("windowsterminal.exe",),
    "Spotify": ("spotify.exe",),
    "Microsoft Edge": ("msedge.exe",),
    "Outlook": ("outlook.exe", "olk.exe"),
}


@dataclass(slots=True)
class ApplicationRecord:
    app_id: str
    name: str
    app_type: str
    launch_target: str
    process_names: tuple[str, ...] = field(default_factory=tuple)
    aumid: str | None = None
    icon: str | None = None
    running: bool = False
    active: bool = False
    pinned: bool = False

    def public(self) -> dict:
        return {
            "id": self.app_id,
            "name": self.name,
            "type": self.app_type,
            "icon": self.icon,
            "running": self.running,
            "active": self.active,
            "pinned": self.pinned,
        }


def stable_app_id(app_type: str, launch_target: str) -> str:
    normalized = os.path.normcase(os.path.expandvars(launch_target.strip()))
    digest = hashlib.sha256(f"{app_type}|{normalized}".encode("utf-8", "surrogatepass")).hexdigest()[:20]
    return f"app_{digest}"


def normalize_record(
    *,
    name: str,
    app_type: str,
    launch_target: str,
    process_names: Iterable[str] = (),
    aumid: str | None = None,
) -> ApplicationRecord | None:
    clean_name = " ".join(name.split()).strip()
    target = os.path.expandvars(launch_target).strip()
    if not clean_name or not target or is_sensitive_path(target):
        return None
    processes = tuple(sorted({Path(p).name.casefold() for p in process_names if p}))
    return ApplicationRecord(
        app_id=stable_app_id(app_type, target),
        name=APP_DISPLAY_RENAMES.get(clean_name, clean_name),
        app_type=app_type,
        launch_target=target,
        process_names=processes,
        aumid=aumid,
    )


def _process_from_target(name: str, target: str) -> tuple[str, ...]:
    display = APP_DISPLAY_RENAMES.get(name, name)
    if display in KNOWN_PROCESSES:
        return KNOWN_PROCESSES[display]
    if target.casefold().endswith(".exe"):
        return (Path(target).name.casefold(),)
    return ()


def _shortcut_dirs() -> list[Path]:
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    app_data = Path(os.environ.get("APPDATA", ""))
    return [
        program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        app_data / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        app_data / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar",
    ]


def discover_shortcuts() -> list[ApplicationRecord]:
    shortcuts: list[Path] = []
    for directory in _shortcut_dirs():
        if directory.is_dir():
            shortcuts.extend(directory.rglob("*.lnk"))
    resolved = resolve_shortcut_targets(shortcuts)
    records: list[ApplicationRecord] = []
    for shortcut in shortcuts:
        name = shortcut.stem.strip()
        lowered = name.casefold()
        target = resolved.get(shortcut)
        if (
            not target
            or is_sensitive_name(name)
            or is_sensitive_path(target)
            or any(word in lowered for word in APP_SKIP_WORDS)
        ):
            continue
        record = normalize_record(
            name=name,
            app_type="shortcut",
            launch_target=str(shortcut),
            process_names=_process_from_target(name, target),
        )
        if record:
            records.append(record)
    return records


def discover_win32_registry() -> list[ApplicationRecord]:
    if os.name != "nt":
        return []
    try:  # pragma: no cover - Windows registry dependent
        import winreg
    except ImportError:
        return []
    roots = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
    paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    records: list[ApplicationRecord] = []
    for root in roots:
        for key_path in paths:
            try:
                key = winreg.OpenKey(root, key_path)
            except OSError:
                continue
            with key:
                for index in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        sub = winreg.OpenKey(key, winreg.EnumKey(key, index))
                        with sub:
                            name = str(winreg.QueryValueEx(sub, "DisplayName")[0]).strip()
                            icon = str(winreg.QueryValueEx(sub, "DisplayIcon")[0]).strip().strip('"')
                    except OSError:
                        continue
                    target = icon.split(",", 1)[0].strip().strip('"')
                    if not target.casefold().endswith(".exe") or not Path(target).is_file():
                        continue
                    record = normalize_record(
                        name=name,
                        app_type="win32",
                        launch_target=target,
                        process_names=(Path(target).name,),
                    )
                    if record:
                        records.append(record)
    return records


def discover_uwp() -> list[ApplicationRecord]:
    if os.name != "nt":
        return []
    script = "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    try:  # pragma: no cover - Windows dependent
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return []
    if isinstance(payload, dict):
        payload = [payload]
    records: list[ApplicationRecord] = []
    for row in payload if isinstance(payload, list) else []:
        name = str(row.get("Name", "")).strip()
        aumid = str(row.get("AppID", "")).strip()
        if not name or not aumid:
            continue
        record = normalize_record(
            name=name,
            app_type="uwp",
            launch_target=f"shell:AppsFolder\\{aumid}",
            aumid=aumid,
        )
        if record:
            records.append(record)
    return records


def _builtins() -> list[ApplicationRecord]:
    items = [
        normalize_record(name="File Explorer", app_type="win32", launch_target="explorer.exe", process_names=("explorer.exe",)),
        normalize_record(name="Settings", app_type="uwp", launch_target="ms-settings:", aumid="ms-settings:"),
    ]
    return [item for item in items if item]


def _load_pin_ids() -> set[str]:
    try:
        payload = json.loads(PIN_FILE.read_text(encoding="utf-8"))
        pins = payload.get("pinned", []) if isinstance(payload, dict) else []
        return {str(item) for item in pins if str(item).startswith("app_")}
    except (OSError, ValueError, json.JSONDecodeError):
        return set()


def _save_pin_ids(ids: set[str]) -> None:
    PIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = PIN_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps({"pinned": sorted(ids)}, indent=2), encoding="utf-8")
    temp.replace(PIN_FILE)


def _foreground_pid() -> int | None:
    if os.name != "nt":
        return None
    try:  # pragma: no cover - Windows dependent
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) or None
    except Exception:
        return None


def _annotate_runtime(records: list[ApplicationRecord]) -> None:
    process_map: dict[str, set[int]] = {}
    for process in psutil.process_iter(["pid", "name"]):
        name = (process.info.get("name") or "").casefold()
        if name:
            process_map.setdefault(name, set()).add(int(process.info["pid"]))
    foreground = _foreground_pid()
    for record in records:
        pids = set().union(*(process_map.get(name, set()) for name in record.process_names)) if record.process_names else set()
        record.running = bool(pids)
        record.active = foreground in pids if foreground else False


def build_registry() -> dict[str, ApplicationRecord]:
    candidates = [*discover_shortcuts(), *discover_win32_registry(), *discover_uwp(), *_builtins()]
    by_key: dict[tuple[str, str], ApplicationRecord] = {}
    for record in candidates:
        key = (record.name.casefold(), record.app_type)
        current = by_key.get(key)
        if current is None or (not current.icon and record.icon):
            by_key[key] = record
    records = list(by_key.values())
    # Prefer one visible record per name: shortcut > UWP > Win32 registry.
    priority = {"shortcut": 0, "uwp": 1, "win32": 2, "web_app": 3, "folder": 4}
    named: dict[str, ApplicationRecord] = {}
    for record in sorted(records, key=lambda r: (r.name.casefold(), priority.get(r.app_type, 9))):
        named.setdefault(record.name.casefold(), record)
    records = list(named.values())

    pin_ids = _load_pin_ids()
    if not pin_ids:
        pin_ids = {r.app_id for r in records if r.name in DEFAULT_PIN_NAMES}
    for record in records:
        record.pinned = record.app_id in pin_ids
        icon_source = record.launch_target
        if record.app_type == "uwp" and record.aumid:
            icon_source = f"shell:AppsFolder\\{record.aumid}"
        record.icon = icon_data_uri(icon_source)
    _annotate_runtime(records)
    save_icon_cache()
    return {record.app_id: record for record in records}


def public_message(registry: dict[str, ApplicationRecord]) -> dict:
    records = sorted(registry.values(), key=lambda r: r.name.casefold())
    return {
        "type": "apps",
        "records": [record.public() for record in records],
        "pinned": [record.name for record in records if record.pinned],
        "all": [record.name for record in records],
        "icons": {record.name: record.icon for record in records if record.icon},
    }


def set_pinned(registry: dict[str, ApplicationRecord], app_id: str, pinned: bool) -> bool:
    record = registry.get(app_id)
    if record is None:
        return False
    record.pinned = pinned
    ids = {item.app_id for item in registry.values() if item.pinned}
    _save_pin_ids(ids)
    return True


def _start(record: ApplicationRecord) -> bool:
    if is_sensitive_path(record.launch_target):
        return False
    try:
        if os.name == "nt":
            os.startfile(record.launch_target)  # type: ignore[attr-defined]
        else:
            return False
        return True
    except (OSError, AttributeError):
        return False


def _matching_windows(record: ApplicationRecord) -> list[int]:
    if os.name != "nt" or not record.process_names:
        return []
    matches: list[int] = []
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def callback(hwnd, _lparam):  # pragma: no cover - Windows dependent
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            name = psutil.Process(pid.value).name().casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return True
        if name in record.process_names:
            matches.append(int(hwnd))
        return True

    user32.EnumWindows(enum_proc(callback), 0)
    return matches


def _window_action(record: ApplicationRecord, action: str) -> bool:
    windows = _matching_windows(record)
    if not windows:
        return False
    user32 = ctypes.windll.user32
    hwnd = windows[0]
    commands = {"minimize": 6, "maximize": 3, "restore": 9, "focus": 9, "activate": 3}
    if action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
        return True
    user32.ShowWindow(hwnd, commands[action])
    if action in {"focus", "activate", "restore", "maximize"}:
        user32.SetForegroundWindow(hwnd)
    return True


def perform_action(registry: dict[str, ApplicationRecord], app_id: str, action: str) -> tuple[bool, str]:
    if action not in VALID_ACTIONS:
        return False, "invalid_action"
    record = registry.get(app_id)
    if record is None:
        return False, "invalid_app_id"
    if action == "launch":
        return (_start(record), "launched")
    if action == "activate":
        if _window_action(record, "activate"):
            return True, "focused"

        started = _start(record)
        if not started:
            return False, "launched"

        if record.process_names:
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                time.sleep(0.15)
                if _window_action(record, "maximize"):
                    break

        return True, "launched"
    if _window_action(record, action):
        return True, action
    return False, "not_running"
