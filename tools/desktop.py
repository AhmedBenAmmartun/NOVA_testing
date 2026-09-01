import ctypes
import subprocess
import sys
import time
import webbrowser
from functools import lru_cache
from ctypes import wintypes

import psutil
from livekit.agents import RunContext, function_tool

from nova_policy import Principal, permission_engine

from .common import logger


# Only approved applications can be opened.
APP_WHITELIST = {
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
    "task manager": "taskmgr",
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "teams": "ms-teams:",
    "obsidian": "obsidian",
    "paint": "mspaint",
    "snipping tool": "snippingtool",
    "terminal": "wt",
}


# Friendly names mapped to real Windows process names.
PROCESS_ALIASES = {
    "google": "chrome",
    "vs code": "code",
    "vscode": "code",
    "edge": "msedge",
    "calculator": "calculatorapp",
    "file explorer": "explorer",
    "task manager": "taskmgr",
    "word": "winword",
    "powerpoint": "powerpnt",
    "terminal": "windows terminal",
}


# Applications that NOVA may close or restart.
CLOSE_APP_PROCESS_MAP = {
    "chrome": "chrome.exe",
    "google": "chrome.exe",
    "edge": "msedge.exe",
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "notepad": "notepad.exe",
    "calculator": "CalculatorApp.exe",
    "spotify": "Spotify.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
}


SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_MINIMIZE = 6
SW_RESTORE = 9

VK_CONTROL = 0x11
VK_LWIN = 0x5B
VK_MENU = 0x12
VK_TAB = 0x09
VK_A = 0x41
VK_D = 0x44
VK_N = 0x4E
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_UP = 0x26
VK_DOWN = 0x28

KEYEVENTF_KEYUP = 0x0002

@lru_cache(maxsize=1)
def _get_user32():
    """Return the Win32 user32 API only when a Windows action is invoked.

    Keeping this lookup lazy lets the module import safely during tests, CI,
    documentation builds, and code review on non-Windows hosts.
    """

    if sys.platform != "win32" or not hasattr(ctypes, "windll"):
        raise RuntimeError("NOVA desktop controls require Windows.")
    return ctypes.windll.user32


def _press_key(
    vk_code: int,
    *,
    key_up: bool = False,
) -> None:
    """Press or release one Windows virtual key."""

    flags = (
        KEYEVENTF_KEYUP
        if key_up
        else 0
    )

    _get_user32().keybd_event(
        vk_code,
        0,
        flags,
        0,
    )


def _press_combo(
    *keys: int,
) -> None:
    """Press and release a Windows keyboard shortcut."""

    for key in keys:
        _press_key(key)
        time.sleep(0.02)

    for key in reversed(keys):
        _press_key(
            key,
            key_up=True,
        )

        time.sleep(0.02)


def _window_text(
    hwnd: int,
) -> str:
    """Return the title of a visible Windows window."""

    length = _get_user32().GetWindowTextLengthW(
        hwnd
    )

    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(
        length + 1
    )

    _get_user32().GetWindowTextW(
        hwnd,
        buffer,
        length + 1,
    )

    return buffer.value


def _window_process_name(
    hwnd: int,
) -> str:
    """Return the process name associated with a window."""

    pid = wintypes.DWORD()

    _get_user32().GetWindowThreadProcessId(
        hwnd,
        ctypes.byref(pid),
    )

    try:
        return psutil.Process(
            pid.value
        ).name().lower()

    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
    ):
        return ""


def _foreground_window() -> int | None:
    """Return the currently focused window handle."""

    hwnd = _get_user32().GetForegroundWindow()

    return hwnd or None


def _find_window(
    query: str,
) -> int | None:
    """Find a visible window by title or process name."""

    cleaned_query = (
        query
        .lower()
        .strip()
    )

    if cleaned_query in {
        "",
        "active",
        "current",
        "current window",
        "focused",
    }:
        return _foreground_window()

    alias = (
        PROCESS_ALIASES.get(
            cleaned_query,
            cleaned_query,
        )
        .replace(" ", "")
    )

    matches: list[int] = []

    enum_proc_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    def _callback(
        hwnd: int,
        _lparam: int,
    ) -> bool:
        if not _get_user32().IsWindowVisible(
            hwnd
        ):
            return True

        title = (
            _window_text(hwnd)
            .lower()
        )

        process_name = (
            _window_process_name(hwnd)
            .removesuffix(".exe")
            .replace(" ", "")
        )

        if (
            cleaned_query in title
            or alias == process_name
            or alias in process_name
        ):
            matches.append(hwnd)

            return False

        return True

    _get_user32().EnumWindows(
        enum_proc_type(_callback),
        0,
    )

    return (
        matches[0]
        if matches
        else None
    )


def _focus_window(
    hwnd: int,
) -> None:
    """Restore and focus a Windows window."""

    _get_user32().ShowWindow(
        hwnd,
        SW_RESTORE,
    )

    _get_user32().SetForegroundWindow(
        hwnd
    )

    time.sleep(0.12)


@function_tool()
async def open_website(
    context: RunContext,
    url: str,
) -> str:
    """Open a website in the default browser."""

    try:
        cleaned_url = url.strip()

        if not cleaned_url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            cleaned_url = (
                "https://"
                + cleaned_url
            )

        webbrowser.open(
            cleaned_url
        )

        logger.info(
            "open_website: %s",
            cleaned_url,
        )

        return (
            f"Opened {cleaned_url}"
        )

    except Exception:
        logger.exception(
            "open_website failed"
        )

        return (
            "I could not open that website."
        )


@function_tool()
async def open_app(
    context: RunContext,
    app_name: str,
) -> str:
    """Open an approved Windows application."""

    cleaned_name = (
        app_name
        .lower()
        .strip()
    )

    command = APP_WHITELIST.get(
        cleaned_name
    )

    if command is None:
        logger.warning(
            "open_app rejected: %r",
            app_name,
        )

        approved_apps = ", ".join(
            sorted(
                set(
                    APP_WHITELIST.keys()
                )
            )
        )

        return (
            f"{app_name} is not in the approved "
            "application list. "
            f"I can open: {approved_apps}."
        )

    try:
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "start",
                "",
                command,
            ],
            shell=False,
        )

        logger.info(
            "open_app: %s -> %s",
            cleaned_name,
            command,
        )

        return (
            f"Opened {app_name}."
        )

    except Exception:
        logger.exception(
            "open_app failed"
        )

        return (
            f"I could not open {app_name}."
        )


@function_tool()
async def is_app_running(
    context: RunContext,
    app_name: str,
) -> str:
    """Check whether an application is currently running."""

    try:
        cleaned_name = (
            app_name
            .lower()
            .strip()
        )

        target = PROCESS_ALIASES.get(
            cleaned_name,
            cleaned_name,
        )

        target = (
            target
            .replace(" ", "")
            .lower()
        )

        running = any(
            (
                process.info["name"]
                or ""
            )
            .lower()
            .removesuffix(".exe")
            .replace(" ", "")
            == target
            for process in psutil.process_iter(
                ["name"]
            )
        )

        if running:
            return (
                f"Yes, {app_name} is running."
            )

        return (
            f"No, {app_name} is not running."
        )

    except Exception:
        logger.exception(
            "is_app_running failed"
        )

        return (
            "I could not check whether "
            f"{app_name} is running."
        )


async def _close_app_impl(
    app_name: str,
) -> str:
    """
    Close an approved application.

    This is an internal helper and must only run after
    the permission engine authorizes the action.
    """

    cleaned_name = (
        app_name
        .lower()
        .strip()
    )

    process_name = (
        CLOSE_APP_PROCESS_MAP.get(
            cleaned_name
        )
    )

    if process_name is None:
        logger.warning(
            "_close_app_impl rejected: %r",
            app_name,
        )

        approved_apps = ", ".join(
            sorted(
                CLOSE_APP_PROCESS_MAP.keys()
            )
        )

        return (
            f"{app_name} is not in the approved "
            "close-app list. "
            f"I can close: {approved_apps}."
        )

    try:
        result = subprocess.run(
            [
                "taskkill",
                "/IM",
                process_name,
                "/T",
            ],
            capture_output=True,
            text=True,
            shell=False,
        )

        if result.returncode == 0:
            logger.info(
                "close_app: %s -> %s",
                cleaned_name,
                process_name,
            )

            return (
                f"Closed {app_name}."
            )

        error_message = (
            result.stderr.strip()
            or result.stdout.strip()
        )

        logger.warning(
            "close_app failed: %s",
            error_message,
        )

        return (
            f"I could not close {app_name}. "
            "It may not be running."
        )

    except Exception:
        logger.exception(
            "_close_app_impl failed"
        )

        return (
            f"I could not close {app_name}."
        )


@function_tool()
async def close_app(
    context: RunContext,
    app_name: str,
) -> str:
    """Request permission before closing an approved application."""

    return await permission_engine.run(
        action_name="close_app",
        summary=(
            f"Close application: {app_name}"
        ),
        session_id="voice",
        # Invoked from a tool the user is talking to. When the orchestrator
        # spawns workers, it passes a worker principal here instead.
        principal=Principal.user(),

        executor=lambda: _close_app_impl(
            app_name
        ),
    )


@function_tool()
async def restart_app(
    context: RunContext,
    app_name: str,
) -> str:
    """Request permission before restarting an approved application."""

    async def execute_restart() -> str:
        close_result = (
            await _close_app_impl(
                app_name
            )
        )

        if (
            "Closed" not in close_result
            and "not be running"
            not in close_result
        ):
            return close_result

        return await open_app(
            context,
            app_name,
        )

    return await permission_engine.run(
        action_name="restart_app",
        summary=(
            f"Restart application: {app_name}"
        ),
        session_id="voice",
        # Invoked from a tool the user is talking to. When the orchestrator
        # spawns workers, it passes a worker principal here instead.
        principal=Principal.user(),

        executor=execute_restart,
    )


@function_tool()
async def control_window(
    context: RunContext,
    window_name: str,
    action: str,
) -> str:
    """Focus, minimize, maximize, restore, or snap a visible window."""

    cleaned_action = (
        action
        .lower()
        .strip()
        .replace(" ", "_")
    )

    valid_actions = {
        "focus",
        "minimize",
        "maximize",
        "restore",
        "snap_left",
        "snap_right",
        "snap_up",
        "snap_down",
    }

    if cleaned_action not in valid_actions:
        return (
            "Unknown window action. Use focus, "
            "minimize, maximize, restore, "
            "snap_left, snap_right, snap_up, "
            "or snap_down."
        )

    try:
        hwnd = _find_window(
            window_name
        )

        if hwnd is None:
            return (
                "I could not find a visible "
                f"window matching {window_name}."
            )

        if cleaned_action == "focus":
            _focus_window(hwnd)

        elif cleaned_action == "minimize":
            _get_user32().ShowWindow(
                hwnd,
                SW_MINIMIZE,
            )

        elif cleaned_action == "maximize":
            _get_user32().ShowWindow(
                hwnd,
                SW_SHOWMAXIMIZED,
            )

        elif cleaned_action == "restore":
            _get_user32().ShowWindow(
                hwnd,
                SW_RESTORE,
            )

        else:
            _focus_window(hwnd)

            key = {
                "snap_left": VK_LEFT,
                "snap_right": VK_RIGHT,
                "snap_up": VK_UP,
                "snap_down": VK_DOWN,
            }[cleaned_action]

            _press_combo(
                VK_LWIN,
                key,
            )

        logger.info(
            "control_window: %s action=%s",
            window_name,
            cleaned_action,
        )

        return (
            "Window action completed: "
            f"{cleaned_action}."
        )

    except Exception:
        logger.exception(
            "control_window failed"
        )

        return (
            "I could not control that window."
        )


@function_tool()
async def open_notifications(
    context: RunContext,
) -> str:
    """Open the Windows notifications panel."""

    try:
        _press_combo(
            VK_LWIN,
            VK_N,
        )

        logger.info(
            "open_notifications"
        )

        return (
            "Opened notifications."
        )

    except Exception:
        logger.exception(
            "open_notifications failed"
        )

        return (
            "I could not open notifications."
        )


@function_tool()
async def open_quick_settings(
    context: RunContext,
) -> str:
    """Open Windows Quick Settings."""

    try:
        _press_combo(
            VK_LWIN,
            VK_A,
        )

        logger.info(
            "open_quick_settings"
        )

        return (
            "Opened quick settings."
        )

    except Exception:
        logger.exception(
            "open_quick_settings failed"
        )

        return (
            "I could not open quick settings."
        )


@function_tool()
async def manage_virtual_desktop(
    context: RunContext,
    action: str,
) -> str:
    """Create, switch, or view Windows virtual desktops."""

    cleaned_action = (
        action
        .lower()
        .strip()
        .replace(" ", "_")
    )

    combos = {
        "new": (
            VK_LWIN,
            VK_CONTROL,
            VK_D,
        ),
        "create": (
            VK_LWIN,
            VK_CONTROL,
            VK_D,
        ),
        "next": (
            VK_LWIN,
            VK_CONTROL,
            VK_RIGHT,
        ),
        "right": (
            VK_LWIN,
            VK_CONTROL,
            VK_RIGHT,
        ),
        "previous": (
            VK_LWIN,
            VK_CONTROL,
            VK_LEFT,
        ),
        "prev": (
            VK_LWIN,
            VK_CONTROL,
            VK_LEFT,
        ),
        "left": (
            VK_LWIN,
            VK_CONTROL,
            VK_LEFT,
        ),
        "task_view": (
            VK_LWIN,
            VK_TAB,
        ),
        "show_desktop": (
            VK_LWIN,
            VK_D,
        ),
    }

    combo = combos.get(
        cleaned_action
    )

    if combo is None:
        return (
            "Unknown virtual desktop action. "
            "Use new, next, previous, "
            "task_view, or show_desktop."
        )

    try:
        _press_combo(
            *combo
        )

        logger.info(
            "manage_virtual_desktop: %s",
            cleaned_action,
        )

        return (
            "Virtual desktop action completed: "
            f"{cleaned_action}."
        )

    except Exception:
        logger.exception(
            "manage_virtual_desktop failed"
        )

        return (
            "I could not manage the "
            "virtual desktop."
        )