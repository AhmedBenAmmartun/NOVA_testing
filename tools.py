import ctypes
import logging
import os
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path

import psutil
import requests
from duckduckgo_search import DDGS
from livekit.agents import function_tool, RunContext

PROJECT_ROOT = Path(__file__).resolve().parent
NOTES_PATH = PROJECT_ROOT / "notes.txt"

# One log file for tool calls and errors (Phase 1 roadmap item).
logger = logging.getLogger("nova.tools")
if not logger.handlers:
    _handler = logging.FileHandler(PROJECT_ROOT / "nova_tools.log", encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------

_HOME = Path.home()
# File tools may only touch these folders (plus the project itself).
_SAFE_DIRS = [PROJECT_ROOT] + [
    base / sub
    for base in (_HOME, _HOME / "OneDrive")
    for sub in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")
]

# Only these apps can be launched; values are fixed strings we control,
# never model input. "start" resolves App Paths, so apps off PATH work.
_APP_WHITELIST = {
    "chrome": "chrome",
    "google": "chrome",
    "edge": "msedge",
    "vscode": "code",
    "vs code": "code",
    "notepad": "notepad",
    "calculator": "calc",
    "spotify": "spotify:",
    "cmd": "cmd",
    "powershell": "powershell",
    "explorer": "explorer",
    "file explorer": "explorer",
}


def _resolve_safe_path(raw_path: str) -> Path | None:
    """Return the resolved path if it is inside an approved folder, else None.

    Secrets files are always blocked, even inside approved folders.
    """
    try:
        path = Path(raw_path).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if path.name.startswith(".env") or path.name == ".spotify_cache":
        return None
    for root in _SAFE_DIRS:
        try:
            if path.is_relative_to(root):
                return path
        except (OSError, ValueError):
            continue
    return None


_SANDBOX_DENIED = (
    "Access denied: that path is outside NOVA's approved folders "
    "(Desktop, Documents, Downloads, Pictures, Music, Videos, and the NOVA project)."
)


def _press_key(vk_code: int) -> None:
    """Press and release a Windows virtual key (media/volume keys)."""
    KEYEVENTF_KEYUP = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def _spotify_window_title() -> str | None:
    """Title of the main Spotify window, or None if Spotify isn't running.

    When a song plays, the title is "Artist - Song"; paused/idle it is just
    "Spotify" (or "Spotify Free"). Lets us read the current song without the
    Spotify API.
    """
    from ctypes import wintypes

    spotify_pids = {
        p.pid
        for p in psutil.process_iter(["name"])
        if (p.info["name"] or "").lower() == "spotify.exe"
    }
    if not spotify_pids:
        return None

    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in spotify_pids:
                length = user32.GetWindowTextLengthW(hwnd)
                if length:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    titles.append(buffer.value)
        return True

    user32.EnumWindows(_enum_proc, 0)
    for title in titles:
        if " - " in title:
            return title
    return titles[0] if titles else "Spotify"


_spotify_client_cache = None


def _spotify_client():
    """Spotipy client if SPOTIFY_CLIENT_ID/SECRET are configured, else None.

    First use opens a browser once for Spotify login (token cached in
    .spotify_cache). Playback control requires Spotify Premium.
    """
    global _spotify_client_cache
    if _spotify_client_cache is not None:
        return _spotify_client_cache
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    _spotify_client_cache = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope="user-modify-playback-state user-read-playback-state",
            cache_path=str(PROJECT_ROOT / ".spotify_cache"),
        )
    )
    return _spotify_client_cache


_SPOTIFY_NOT_CONFIGURED = (
    "The Spotify API is not set up yet. To play specific songs, create a free app at "
    "developer.spotify.com, then add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to the "
    ".env file (redirect URI http://127.0.0.1:8888/callback). "
    "I can still pause, resume, skip tracks, and change volume without it."
)


# ---------------------------------------------------------------------------
# Information tools
# ---------------------------------------------------------------------------


@function_tool()
async def get_weather(context: RunContext, city: str) -> str:
    """Get the current weather for a city."""
    try:
        response = requests.get(f"https://wttr.in/{city}?format=3", timeout=10)
        return response.text.strip() if response.status_code == 200 else f"Weather error: {response.status_code}"
    except Exception as e:
        logger.error("get_weather failed: %s", e)
        return f"Error getting weather: {e}"


@function_tool()
async def search_web(context: RunContext, query: str) -> str:
    """Search the web with DuckDuckGo and return the top results."""
    try:
        results = DDGS().text(query, max_results=5)
        if not results:
            return "No results found."
        return "\n".join(f"{r['title']}: {r['body']} ({r['href']})" for r in results)
    except Exception as e:
        logger.error("search_web failed: %s", e)
        return f"Error searching web: {e}"


@function_tool()
async def get_system_info(context: RunContext) -> str:
    """Get CPU, RAM, battery, and disk information."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        battery = psutil.sensors_battery()

        battery_text = "Battery info not available"
        if battery:
            battery_text = f"Battery: {battery.percent}%"

        return (
            f"CPU usage: {cpu}%\n"
            f"RAM usage: {ram.percent}%\n"
            f"Disk usage: {disk.percent}%\n"
            f"{battery_text}"
        )
    except Exception as e:
        logger.error("get_system_info failed: %s", e)
        return f"Error getting system info: {e}"


@function_tool()
async def get_time(context: RunContext) -> str:
    """Get the current date and time."""
    now = datetime.now()
    return now.strftime("Today is %A, %B %d, %Y. The time is %I:%M %p.")


# ---------------------------------------------------------------------------
# Desktop / browser tools
# ---------------------------------------------------------------------------


@function_tool()
async def open_website(context: RunContext, url: str) -> str:
    """Open a website in the default browser."""
    try:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        logger.info("open_website: %s", url)
        return f"Opened {url}"
    except Exception as e:
        logger.error("open_website failed: %s", e)
        return f"Error opening website: {e}"


@function_tool()
async def open_app(context: RunContext, app_name: str) -> str:
    """Open an approved app on Windows.

    Approved apps: chrome, edge, vscode, notepad, calculator, spotify, cmd,
    powershell, file explorer. Anything else is refused.
    """
    command = _APP_WHITELIST.get(app_name.lower().strip())
    if command is None:
        logger.warning("open_app rejected: %r", app_name)
        return (
            f"'{app_name}' is not in the approved app list. "
            f"I can open: {', '.join(sorted(set(_APP_WHITELIST)))}."
        )
    try:
        # Fixed argv from our whitelist - never raw model input.
        subprocess.Popen(["cmd", "/c", "start", "", command])
        logger.info("open_app: %s -> %s", app_name, command)
        return f"Opened {app_name}"
    except Exception as e:
        logger.error("open_app failed: %s", e)
        return f"Error opening app: {e}"


# Friendly names -> actual process names (without .exe)
_PROCESS_ALIASES = {
    "google": "chrome",
    "vs code": "code",
    "vscode": "code",
    "edge": "msedge",
    "calculator": "calculatorapp",
    "file explorer": "explorer",
}


@function_tool()
async def is_app_running(context: RunContext, app_name: str) -> str:
    """Check whether an app (by name, e.g. 'spotify') is currently running."""
    try:
        needle = app_name.lower().strip()
        # Exact process-name match: substring matching wrongly counted helper
        # stubs like SpotifyLauncher as the real app.
        target = _PROCESS_ALIASES.get(needle, needle).replace(" ", "")
        running = any(
            (p.info["name"] or "").lower().removesuffix(".exe") == target
            for p in psutil.process_iter(["name"])
        )
        return f"Yes, {app_name} is running." if running else f"No, {app_name} is not running."
    except Exception as e:
        logger.error("is_app_running failed: %s", e)
        return f"Error checking apps: {e}"


@function_tool()
async def play_youtube_song(context: RunContext, song_name: str) -> str:
    """Open YouTube search for a song."""
    try:
        query = song_name.replace(" ", "+")
        url = f"https://www.youtube.com/results?search_query={query}"
        webbrowser.open(url)
        return f"Opened YouTube search for {song_name}"
    except Exception as e:
        logger.error("play_youtube_song failed: %s", e)
        return f"Error opening YouTube: {e}"


# ---------------------------------------------------------------------------
# Music / Spotify tools
# ---------------------------------------------------------------------------


@function_tool()
async def control_music(context: RunContext, action: str) -> str:
    """Control whatever music is playing (Spotify or any player) via media keys.

    action must be one of: "play_pause", "next", "previous".
    """
    keys = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
    vk_code = keys.get(action.lower().strip())
    if vk_code is None:
        return f"Unknown action '{action}'. Use one of: {', '.join(keys)}."
    try:
        _press_key(vk_code)
        logger.info("control_music: %s", action)
        return f"Sent {action.replace('_', '/')} to the music player."
    except Exception as e:
        logger.error("control_music failed: %s", e)
        return f"Error controlling music: {e}"


@function_tool()
async def change_volume(context: RunContext, action: str, steps: int = 5) -> str:
    """Change the system volume.

    action must be one of: "up", "down", "mute" (mute toggles).
    steps is how many notches to move for up/down (1-20, each is ~2%).
    """
    keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
    vk_code = keys.get(action.lower().strip())
    if vk_code is None:
        return f"Unknown action '{action}'. Use one of: {', '.join(keys)}."
    try:
        presses = 1 if action == "mute" else max(1, min(int(steps), 20))
        for _ in range(presses):
            _press_key(vk_code)
        logger.info("change_volume: %s x%d", action, presses)
        return f"Volume {action}" + ("" if action == "mute" else f" by {presses} steps.")
    except Exception as e:
        logger.error("change_volume failed: %s", e)
        return f"Error changing volume: {e}"


@function_tool()
async def get_current_song(context: RunContext) -> str:
    """Get the song currently playing in Spotify."""
    try:
        title = _spotify_window_title()
        if title is None:
            return "Spotify is not running."
        if " - " in title:
            return f"Now playing: {title}"
        return "Spotify is open, but nothing seems to be playing."
    except Exception as e:
        logger.error("get_current_song failed: %s", e)
        return f"Error reading current song: {e}"


@function_tool()
async def play_spotify_song(context: RunContext, song_name: str) -> str:
    """Search Spotify for a song and start playing it.

    Requires the Spotify API to be configured and Spotify Premium; otherwise
    explains what is missing. First use opens a browser for Spotify login.
    """
    client = _spotify_client()
    if client is None:
        return _SPOTIFY_NOT_CONFIGURED
    try:
        # spotipy calls are typed Optional - "or {}" guards the None case
        results = client.search(q=song_name, type="track", limit=1) or {}
        items = results.get("tracks", {}).get("items", [])
        if not items:
            return f"I couldn't find '{song_name}' on Spotify."
        track = items[0]
        devices = (client.devices() or {}).get("devices", [])
        if not devices:
            return "No Spotify device is active. Open Spotify first, then ask me again."
        client.start_playback(device_id=devices[0]["id"], uris=[track["uri"]])
        artist = track["artists"][0]["name"] if track["artists"] else "unknown artist"
        logger.info("play_spotify_song: %s - %s", artist, track["name"])
        return f"Playing {track['name']} by {artist} on Spotify."
    except Exception as e:
        logger.error("play_spotify_song failed: %s", e)
        return f"Error playing on Spotify (note: playback control needs Spotify Premium): {e}"


# ---------------------------------------------------------------------------
# Notes tools
# ---------------------------------------------------------------------------


@function_tool()
async def save_note(context: RunContext, note: str) -> str:
    """Save a note to NOVA's notes file."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with NOTES_PATH.open("a", encoding="utf-8") as file:
            file.write(f"[{timestamp}] {note}\n")
        logger.info("save_note: %d chars", len(note))
        return "Note saved."
    except Exception as e:
        logger.error("save_note failed: %s", e)
        return f"Error saving note: {e}"


@function_tool()
async def read_notes(context: RunContext) -> str:
    """Read saved notes."""
    try:
        if not NOTES_PATH.exists():
            return "You do not have any saved notes yet."
        return NOTES_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("read_notes failed: %s", e)
        return f"Error reading notes: {e}"


# ---------------------------------------------------------------------------
# File tools (sandboxed to approved folders)
# ---------------------------------------------------------------------------


@function_tool()
async def list_files(context: RunContext, folder_path: str = ".") -> str:
    """List files in a folder (approved folders only)."""
    folder = _resolve_safe_path(folder_path)
    if folder is None:
        logger.warning("list_files denied: %r", folder_path)
        return _SANDBOX_DENIED
    try:
        if not folder.exists():
            return "Folder does not exist."
        items = list(folder.iterdir())
        if not items:
            return "Folder is empty."
        return "\n".join(item.name for item in items[:50])
    except Exception as e:
        logger.error("list_files failed: %s", e)
        return f"Error listing files: {e}"


@function_tool()
async def read_file(context: RunContext, file_path: str) -> str:
    """Read a text file (approved folders only)."""
    path = _resolve_safe_path(file_path)
    if path is None:
        logger.warning("read_file denied: %r", file_path)
        return _SANDBOX_DENIED
    try:
        if not path.exists():
            return "File does not exist."
        if path.stat().st_size > 20000:
            return "File is too large to read safely."
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("read_file failed: %s", e)
        return f"Error reading file: {e}"


@function_tool()
async def create_file(context: RunContext, file_path: str, content: str) -> str:
    """Create a new file (approved folders only). Does not overwrite existing files."""
    path = _resolve_safe_path(file_path)
    if path is None:
        logger.warning("create_file denied: %r", file_path)
        return _SANDBOX_DENIED
    try:
        if path.exists():
            return "File already exists. I will not overwrite it without confirmation."
        path.write_text(content, encoding="utf-8")
        logger.info("create_file: %s", path)
        return f"Created file: {path}"
    except Exception as e:
        logger.error("create_file failed: %s", e)
        return f"Error creating file: {e}"
