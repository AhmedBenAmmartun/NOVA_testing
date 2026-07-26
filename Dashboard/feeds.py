"""Data collectors that feed the NOVA dashboard with real system state.

Every collector returns plain dicts shaped like the WebSocket messages the
web shell understands (see web/index.html onLive). Nothing here imports the
LiveKit tool stack; the dashboard only reads the files NOVA already writes
(nova_tools.log, audit_logs/, conversation_logs/, the Obsidian vault) plus
the OS itself (psutil, Start Menu, Spotify window).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import psutil

from app_registry import build_registry, public_message, refresh_runtime
from security import is_sensitive_path, resolve_shortcut_targets, safe_recent_target

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
NOVA_TOOLS_LOG = PROJECT_ROOT / "nova_tools.log"
AUDIT_LOG = PROJECT_ROOT / "audit_logs" / "nova_actions.jsonl"
CONVERSATION_LOGS = PROJECT_ROOT / "conversation_logs"
CUSTOM_FOLDERS_FILE = RUNTIME_DIR / "custom_folders.json"

TASKS_NOTE_RELATIVE = Path("NOVA") / "Tasks.md"
MEMORY_TRASH_RELATIVE = Path("NOVA") / ".trash"

# Providers in cloud_usage.json -> model chips on the NOVA page.
MODEL_CHIPS = ["Gemini Flash", "Groq Llama", "Ollama", "GPT-5.6", "Obsidian Brain"]
PROVIDER_TO_CHIP = {
    "gemini": "Gemini Flash",
    "google": "Gemini Flash",
    "groq": "Groq Llama",
    "ollama": "Ollama",
    "openai": "GPT-5.6",
    "gpt": "GPT-5.6",
    "obsidian": "Obsidian Brain",
}

# Start Menu names -> the shorter names the design's BRAND map uses.
APP_DISPLAY_RENAMES = {
    "Google Chrome": "Chrome",
    "Visual Studio Code": "VS Code",
    "Windows Terminal": "Terminal",
    "Python 3.14 (64-bit)": "Python 3.14",
}
APP_SKIP_WORDS = (
    "uninstall",
    "readme",
    "documentation",
    "website",
    "release notes",
    "repair",
)
PINNED_PREFERENCE = [
    "Chrome",
    "VS Code",
    "Claude",
    "ChatGPT",
    "Obsidian",
    "Terminal",
    "Spotify",
    "File Explorer",
]


def now_label() -> str:
    """Local time like '3:05 PM' (matches the design's timestamps)."""
    try:
        return datetime.now().strftime("%#I:%M %p")
    except ValueError:
        return datetime.now().strftime("%I:%M %p").lstrip("0")


def age_label(timestamp: float) -> str:
    """Compact age like '4m' / '2h' / '3d'."""
    delta = max(0.0, time.time() - timestamp)
    if delta < 3600:
        return f"{max(1, int(delta // 60))}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


# ---------------------------------------------------------
# System stats
# ---------------------------------------------------------

def stats_message() -> dict:
    return {
        "type": "stats",
        "cpu": round(psutil.cpu_percent(interval=None)),
        "ram": round(psutil.virtual_memory().percent),
    }


# ---------------------------------------------------------
# Spotify (window title first, Spotify Web API when available)
# ---------------------------------------------------------

def spotify_window_title() -> str | None:
    """Title of the main Spotify window ('Artist - Track' while playing)."""
    spotify_pids = {
        process.pid
        for process in psutil.process_iter(["name"])
        if (process.info["name"] or "").lower() == "spotify.exe"
    }
    if not spotify_pids:
        return None

    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_window(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if process_id.value in spotify_pids:
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    titles.append(buffer.value)
        return True

    user32.EnumWindows(enum_window, 0)

    for title in titles:
        if " - " in title:
            return title
    return titles[0] if titles else "Spotify"


_spotify_client = None
_spotify_client_failed = False


def _spotify_api_client():
    """Spotify Web API client from the cached OAuth token; never opens a browser."""
    global _spotify_client, _spotify_client_failed

    if _spotify_client is not None or _spotify_client_failed:
        return _spotify_client

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    cache_path = PROJECT_ROOT / ".spotify_cache"

    if not client_id or not client_secret or not cache_path.is_file():
        _spotify_client_failed = True
        return None

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        _spotify_client = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=os.getenv(
                    "SPOTIFY_REDIRECT_URI",
                    "http://127.0.0.1:8888/callback",
                ),
                scope="user-modify-playback-state user-read-playback-state",
                cache_path=str(cache_path),
                open_browser=False,
            )
        )
    except Exception:
        _spotify_client_failed = True
        _spotify_client = None

    return _spotify_client


def spotify_message() -> dict:
    """Real now-playing state. Never invents a track when Spotify is idle."""
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    artwork: str | None = None
    device: str | None = None
    playing = False
    progress: int | None = None
    progress_ms: int | None = None
    duration_ms: int | None = None
    configured = False

    client = _spotify_api_client()
    if client is not None:
        configured = True
        try:
            playback = client.current_playback()
            if playback:
                device_info = playback.get("device") or {}
                device = device_info.get("name")
                item = playback.get("item")
                if item:
                    title = item.get("name")
                    artist = ", ".join(
                        a.get("name", "") for a in item.get("artists", []) if a.get("name")
                    ) or None
                    album_info = item.get("album") or {}
                    album = album_info.get("name")
                    images = album_info.get("images") or []
                    artwork = images[0].get("url") if images else None
                    playing = bool(playback.get("is_playing"))
                    duration_ms = item.get("duration_ms") or None
                    progress_ms = playback.get("progress_ms")
                    if duration_ms and progress_ms is not None:
                        progress = max(0, min(100, round(progress_ms / duration_ms * 100)))
        except Exception:
            pass

    window_title = spotify_window_title()
    spotify_open = window_title is not None
    if title is None and window_title and " - " in window_title:
        artist, title = window_title.split(" - ", 1)
        playing = True

    if title:
        status = "playing" if playing else "paused"
    elif spotify_open:
        status = "idle"
    else:
        status = "closed"

    return {
        "type": "spotify",
        "available": bool(title or spotify_open or configured),
        "configured": configured,
        "open": spotify_open,
        "status": status,
        "title": title,
        "artist": artist,
        "album": album,
        "artwork": artwork,
        "device": device,
        "playing": playing,
        "progress": progress,
        "progressMs": progress_ms,
        "durationMs": duration_ms,
    }


# ---------------------------------------------------------
# Weather (wttr.in, no API key)
# ---------------------------------------------------------

async def weather_message(http_session) -> dict | None:
    city = os.getenv("NOVA_CITY", "").strip()
    url = f"https://wttr.in/{city}?format=j1"
    try:
        async with http_session.get(url, timeout=10) as response:
            data = await response.json(content_type=None)
        current = data["current_condition"][0]
        today = data["weather"][0]
        temp = f"{current['temp_F']}°"
        condition = current["weatherDesc"][0]["value"].strip()
        desc = f"{condition} · H {today['maxtempF']}° L {today['mintempF']}°"
        return {
            "type": "weather",
            "temp": temp,
            "desc": desc,
            "brief": f"{temp} {condition}",
        }
    except Exception:
        return None


# ---------------------------------------------------------
# Obsidian vault: note counts, recent notes, memories, tasks
# ---------------------------------------------------------

def vault_path() -> Path | None:
    raw = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None


def _iter_vault_notes(vault: Path):
    for note in vault.rglob("*.md"):
        parts = note.relative_to(vault).parts
        if ".obsidian" in parts or ".trash" in parts:
            continue
        yield note


def _note_snippet(note: Path) -> str:
    try:
        text = note.read_text(encoding="utf-8", errors="ignore")[:1500]
    except OSError:
        return ""
    if text.startswith("---"):
        closing = text.find("---", 3)
        if closing != -1:
            text = text[closing + 3 :]
    lines = [
        line.strip().lstrip("#").strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("---", "![", "```"))
    ]
    snippet = " ".join(lines)[:110]
    return snippet


def obsidian_message() -> dict:
    vault = vault_path()
    if vault is None:
        return {
            "type": "obsidian",
            "available": False,
            "count": 0,
            "recent": [],
            "memories": [],
        }

    notes = list(_iter_vault_notes(vault))
    recent = sorted(notes, key=lambda n: n.stat().st_mtime, reverse=True)[:3]

    nova_folder = vault / "NOVA"
    memories: list[dict] = []
    if nova_folder.is_dir():
        memory_notes = [
            note
            for note in nova_folder.rglob("*.md")
            if "Conversations" not in note.relative_to(nova_folder).parts
            and ".trash" not in note.relative_to(nova_folder).parts
            and note.name != "Tasks.md"
        ]
        memory_notes.sort(key=lambda n: n.stat().st_mtime, reverse=True)
        for index, note in enumerate(memory_notes[:8]):
            memories.append(
                {
                    "id": index + 1,
                    "title": note.name,
                    "snippet": _note_snippet(note),
                    "when": age_label(note.stat().st_mtime),
                }
            )

    return {
        "type": "obsidian",
        "available": True,
        "count": len(notes),
        "recent": [
            {"title": note.name, "when": age_label(note.stat().st_mtime)}
            for note in recent
        ],
        "memories": memories,
    }


def _tasks_note() -> Path | None:
    vault = vault_path()
    if vault is None:
        return None
    note = vault / TASKS_NOTE_RELATIVE
    return note if note.is_file() else None


_TASK_LINE = re.compile(r"^\s*[-*] \[( |x|X)\] (.+)$")


def tasks_message() -> dict:
    note = _tasks_note()
    if note is None:
        return {"type": "tasks", "available": False, "items": []}
    items = []
    try:
        for line in note.read_text(encoding="utf-8").splitlines():
            match = _TASK_LINE.match(line)
            if match:
                items.append(
                    {
                        "id": len(items) + 1,
                        "label": match.group(2).strip(),
                        "done": match.group(1).lower() == "x",
                    }
                )
    except OSError:
        return None
    return {"type": "tasks", "available": True, "items": items}


def set_task_done(task_id: int, done: bool) -> bool:
    """Flip one checkbox in the vault Tasks note. Never touches other lines."""
    note = _tasks_note()
    if note is None:
        return False
    try:
        lines = note.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    seen = 0
    for index, line in enumerate(lines):
        match = _TASK_LINE.match(line)
        if not match:
            continue
        seen += 1
        if seen == task_id:
            mark = "x" if done else " "
            prefix = line[: line.index("[") + 1]
            lines[index] = f"{prefix}{mark}] {match.group(2).strip()}"
            note.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    return False


def forget_memory(title: str) -> bool:
    """Move a NOVA memory note into the vault's NOVA/.trash (reversible)."""
    vault = vault_path()
    if vault is None or not title or "/" in title or "\\" in title:
        return False
    source = vault / "NOVA" / title
    if not source.is_file() or source.suffix.lower() != ".md":
        return False
    trash = vault / MEMORY_TRASH_RELATIVE
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"{source.stem}-{int(time.time())}{source.suffix}"
    source.rename(target)
    return True


# ---------------------------------------------------------
# Cloud usage (nova_core writes cloud_usage.json)
# ---------------------------------------------------------

def _usage_file() -> Path:
    custom = os.getenv("NOVA_CLOUD_USAGE_FILE", "").strip()
    if custom:
        return Path(custom).expanduser()
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "NOVA" / "cloud_usage.json"
    return Path.home() / ".nova" / "cloud_usage.json"


def usage_message() -> dict:
    counts: dict[str, int] = {chip: 0 for chip in MODEL_CHIPS}
    total = 0
    try:
        state = json.loads(_usage_file().read_text(encoding="utf-8"))
        if state.get("date") == datetime.now().date().isoformat():
            for provider, used in (state.get("providers") or {}).items():
                chip = PROVIDER_TO_CHIP.get(str(provider).lower())
                if chip:
                    counts[chip] += int(used)
            total = int(state.get("total_requests", 0))
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    return {
        "type": "usage",
        "models": {chip: f"{n} req" for chip, n in counts.items()},
        "total": f"Today · {total} cloud requests",
    }


# ---------------------------------------------------------
# Apps, quick folders, recent files
# ---------------------------------------------------------

def _desktop_path() -> Path:
    home = Path.home()
    onedrive_desktop = home / "OneDrive" / "Desktop"
    return onedrive_desktop if onedrive_desktop.is_dir() else home / "Desktop"


def _recent_id(shortcut: Path) -> str:
    digest = hashlib.sha256(str(shortcut).encode("utf-8", "surrogatepass")).hexdigest()[:18]
    return f"recent_{digest}"


def apps_runtime_message(registry: dict) -> dict:
    """Return only frequently changing application runtime state."""
    refresh_runtime(registry)
    return {
        "type": "apps_runtime",
        "records": [
            {
                "id": record.app_id,
                "running": record.running,
                "active": record.active,
                "group": record.public().get("group"),
                "groupName": record.public().get("groupName"),
                "windowCount": len(record.window_titles),
                "windows": [{"title": title} for title in record.window_titles],
            }
            for record in registry.values()
        ],
    }

def _load_custom_folder_paths() -> list[str]:
    if not CUSTOM_FOLDERS_FILE.is_file():
        return []
    try:
        value = json.loads(CUSTOM_FOLDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _save_custom_folder_paths(paths: list[str]) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CUSTOM_FOLDERS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(paths, indent=2), encoding="utf-8")
    temporary.replace(CUSTOM_FOLDERS_FILE)


def remove_custom_folder(target: str) -> bool:
    wanted = os.path.normcase(os.path.abspath(target))
    current = _load_custom_folder_paths()
    remaining = [
        item
        for item in current
        if os.path.normcase(os.path.abspath(item)) != wanted
    ]
    if len(remaining) == len(current):
        return False
    try:
        _save_custom_folder_paths(remaining)
    except OSError:
        return False
    return True


def _unique_folder_label(name: str, existing: dict[str, str]) -> str:
    base = name.strip() or "Folder"
    label = base
    number = 2
    while label.casefold() in {item.casefold() for item in existing}:
        label = f"{base} ({number})"
        number += 1
    return label

def scan_apps() -> tuple[dict, dict]:
    """Return the normalized app catalog plus trusted backend targets."""
    registry = build_registry()

    folder_targets: dict[str, str] = {}
    home = Path.home()
    desktop = _desktop_path()
    for label, path in (
        ("Desktop", desktop),
        ("Downloads", home / "Downloads"),
        ("Documents", home / "OneDrive" / "Documents"),
    ):
        if path.is_dir():
            folder_targets[label] = str(path)
    vault = vault_path()
    if vault is not None:
        folder_targets["Obsidian Vault"] = str(vault)
    try:
        subfolders = sorted(
            (d for d in desktop.iterdir() if d.is_dir() and not d.name.startswith(".")),
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for sub in subfolders[:4]:
            folder_targets.setdefault(sub.name, str(sub))
    except OSError:
        pass

    custom_folder_targets: dict[str, str] = {}
    existing_paths = {
        os.path.normcase(os.path.abspath(path))
        for path in folder_targets.values()
    }
    for raw_path in _load_custom_folder_paths():
        path = Path(raw_path).expanduser()
        if not path.is_dir() or is_sensitive_path(path):
            continue
        normalized = os.path.normcase(os.path.abspath(str(path)))
        if normalized in existing_paths:
            continue
        label = _unique_folder_label(path.name, folder_targets)
        folder_targets[label] = str(path)
        custom_folder_targets[label] = str(path)
        existing_paths.add(normalized)

    recent_targets: dict[str, str] = {}
    recent_items: list[dict] = []
    recent_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
    if recent_dir.is_dir():
        try:
            shortcuts = sorted(
                recent_dir.glob("*.lnk"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            shortcuts = []
        resolved_shortcuts = resolve_shortcut_targets(shortcuts)
        for shortcut in shortcuts:
            safe = safe_recent_target(shortcut, resolver=resolved_shortcuts.get)
            if safe is None:
                continue
            file_name, target = safe
            if "." not in file_name or file_name.casefold().startswith(("http", "www.")):
                continue
            extension = file_name.rsplit(".", 1)[1].upper()
            if not (1 <= len(extension) <= 6) or not extension.isalnum() or extension.isdigit():
                continue
            item_id = _recent_id(shortcut)
            recent_targets[item_id] = target
            try:
                when = age_label(shortcut.stat().st_mtime)
            except OSError:
                when = "now"
            recent_items.append({"id": item_id, "name": file_name, "ext": extension, "when": when})
            if len(recent_items) >= 8:
                break

    message = public_message(registry)
    message.update({
        "folders": list(folder_targets.keys()),
        "custom_folders": list(custom_folder_targets.keys()),
        "recent": recent_items,
    })
    targets = {
        "apps": registry,
        "folders": folder_targets,
        "custom_folders": custom_folder_targets,
        "recent": recent_targets,
    }
    return message, targets


# ---------------------------------------------------------
# nova_tools.log tail -> agent phase + activity feed
# ---------------------------------------------------------

_LOG_LINE = re.compile(r"^\S+ \S+ (?:INFO|WARNING|ERROR) (.*)$")
_STATE_LINE = re.compile(r"conversation agent_state .*-> *(\S+)")

PHASES = {"idle", "listening", "thinking", "speaking"}


def tag_for(message: str) -> str:
    lowered = message.lower()
    if any(k in lowered for k in ("obsidian", "memory", "conversation", "note")):
        return "Memory"
    if any(k in lowered for k in ("specialist", "router", "groq", "ollama", "gpt")):
        return "Route"
    if any(k in lowered for k in ("screen", "vision", "capture")):
        return "Vision"
    return "Tool"


def parse_log_line(line: str) -> dict | None:
    """One nova_tools.log line -> a phase or activity message (or None)."""
    match = _LOG_LINE.match(line.strip())
    if not match:
        return None
    message = match.group(1).strip()
    if not message:
        return None

    if message.startswith("conversation agent_state"):
        state_match = _STATE_LINE.search(message)
        if not state_match:
            return None
        phase = state_match.group(1).lower().rsplit(".", 1)[-1].strip()
        if phase in ("initializing", "idle"):
            phase = "idle"
        if phase not in PHASES:
            return None
        return {"type": "phase", "phase": phase}

    if message.startswith("conversation "):
        return None  # speech bookkeeping; the transcript feed covers it

    return {
        "type": "activity",
        "time": now_label(),
        "tag": tag_for(message),
        "text": message[:88],
        "status": "ok",
    }


class FileTail:
    """Poll-based tail that survives log truncation and missing files."""

    def __init__(self, path: Path, from_start: bool = False):
        self.path = path
        self.position = 0 if from_start else None

    def read_new_lines(self) -> list[str]:
        try:
            size = self.path.stat().st_size
        except OSError:
            self.position = None if self.position is None else 0
            return []

        if self.position is None or self.position > size:
            self.position = 0 if self.position == 0 else size
            if self.position == size:
                return []

        try:
            with self.path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(self.position)
                chunk = handle.read()
                self.position = handle.tell()
        except OSError:
            return []

        return [line for line in chunk.splitlines() if line.strip()]


# ---------------------------------------------------------
# audit_logs/nova_actions.jsonl tail -> approvals + activity
# ---------------------------------------------------------

PENDING_MAX_AGE_SECONDS = 15 * 60


class ApprovalsTracker:
    """Reconstruct the pending-approval queue from the audit trail."""

    def __init__(self):
        self.pending: dict[str, dict] = {}

    def feed(self, line: str) -> list[dict]:
        """Consume one audit record; return dashboard messages to broadcast."""
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return []

        action_id = record.get("action_id")
        status = str(record.get("status", ""))
        action = str(record.get("action", "")).replace("_", " ").strip() or "action"
        summary = str(record.get("summary", ""))[:110]
        messages: list[dict] = []

        if status == "confirmation_required" and action_id:
            self.pending[action_id] = {
                "id": action_id,
                "action": action.capitalize(),
                "detail": summary,
                "at": time.time(),
            }
            messages.append(
                {
                    "type": "activity",
                    "time": now_label(),
                    "tag": "Task",
                    "text": f"{action} awaiting approval ({action_id})",
                    "status": "running",
                }
            )
        elif action_id and action_id in self.pending and status in (
            "approved",
            "executed",
            "denied",
            "expired",
            "failed",
        ):
            self.pending.pop(action_id, None)
            outcome = {
                "approved": "approved",
                "executed": "ok",
                "denied": "denied",
                "expired": "denied",
                "failed": "denied",
            }[status]
            messages.append(
                {
                    "type": "activity",
                    "time": now_label(),
                    "tag": tag_for(action),
                    "text": f"{action}: {status}",
                    "status": outcome,
                }
            )

        return messages

    def drop_stale(self) -> bool:
        cutoff = time.time() - PENDING_MAX_AGE_SECONDS
        stale = [key for key, item in self.pending.items() if item["at"] < cutoff]
        for key in stale:
            self.pending.pop(key, None)
        return bool(stale)

    def message(self) -> dict:
        items = sorted(self.pending.values(), key=lambda item: item["at"])
        return {
            "type": "approvals",
            "items": [
                {"id": item["id"], "action": item["action"], "detail": item["detail"]}
                for item in items
            ],
        }


# ---------------------------------------------------------
# conversation_logs -> live chat bubbles + transcript pill
# ---------------------------------------------------------

_TURN_HEADER = re.compile(r"^### (Ahmed|NOVA) - \d{2}:\d{2}:\d{2}$")
CONVERSATION_FRESH_SECONDS = 6 * 3600


def _newest_conversation_log() -> Path | None:
    if not CONVERSATION_LOGS.is_dir():
        return None
    newest, newest_mtime = None, 0.0
    for path in CONVERSATION_LOGS.rglob("*.md"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > newest_mtime:
            newest, newest_mtime = path, mtime
    return newest


def parse_conversation_turns(path: Path) -> list[dict]:
    turns: list[dict] = []
    current: dict | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines:
        header = _TURN_HEADER.match(line.strip())
        if header:
            if current and current["text"]:
                turns.append(current)
            current = {
                "who": "user" if header.group(1) == "Ahmed" else "nova",
                "text": "",
            }
        elif current is not None and line.strip():
            current["text"] = (current["text"] + " " + line.strip()).strip()
    if current and current["text"]:
        turns.append(current)
    return turns


class ConversationWatch:
    """Watch the newest conversation log for fresh turns."""

    def __init__(self):
        self.last_mtime = 0.0
        self.last_turn_count = 0
        self.seeded = False

    def poll(self) -> list[dict]:
        path = _newest_conversation_log()
        if path is None:
            return []
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return []
        if time.time() - mtime > CONVERSATION_FRESH_SECONDS:
            return []
        if datetime.fromtimestamp(mtime).date() != datetime.now().date():
            return []
        if self.seeded and mtime <= self.last_mtime:
            return []

        turns = parse_conversation_turns(path)
        messages: list[dict] = []
        if turns:
            messages.append({"type": "talk", "items": turns[-4:]})
            new_turns = turns[self.last_turn_count :] if self.seeded else []
            for turn in new_turns:
                if turn["who"] == "user":
                    messages.append({"type": "transcript", "text": turn["text"][:160]})
        self.last_mtime = mtime
        self.last_turn_count = len(turns)
        self.seeded = True
        return messages
