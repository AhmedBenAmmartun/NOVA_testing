"""Windows desktop-layer helpers for the NOVA skin windows."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Any

from ctypes import wintypes


GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
SW_SHOWNOACTIVATE = 4
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SMTO_NORMAL = 0x0000
GA_ROOT = 2
WM_SHELL_RERUN = 0x052C
HWND_BOTTOM = 1


class Rect(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MonitorInfoEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", Rect),
        ("rcWork", Rect),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """A physical display and its usable work area."""

    name: str
    left: int
    top: int
    width: int
    height: int
    work_left: int
    work_top: int
    work_width: int
    work_height: int

    def contains(self, x: int, y: int) -> bool:
        return (
            self.left <= x < self.left + self.width
            and self.top <= y < self.top + self.height
        )

    def clamp(self, x: int, y: int, width: int, height: int) -> tuple[int, int]:
        max_x = self.work_left + max(0, self.work_width - width)
        max_y = self.work_top + max(0, self.work_height - height)
        return (
            min(max(x, self.work_left), max_x),
            min(max(y, self.work_top), max_y),
        )


def _primary_fallback() -> MonitorInfo:
    width = 1280
    height = 720
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
        except Exception:
            pass
    return MonitorInfo("primary", 0, 0, width, height, 0, 0, width, height)


def enumerate_monitors() -> list[MonitorInfo]:
    """Return Windows monitors, or one safe fallback on non-Windows hosts."""
    if os.name != "nt":
        return [_primary_fallback()]

    user32 = ctypes.windll.user32
    monitors: list[MonitorInfo] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.HDC,
        ctypes.POINTER(Rect),
        wintypes.LPARAM,
    )

    def callback(handle: int, _dc: Any, _rect: Any, _data: int) -> bool:
        info = MonitorInfoEx()
        info.cbSize = ctypes.sizeof(MonitorInfoEx)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            monitor = info.rcMonitor
            work = info.rcWork
            monitors.append(
                MonitorInfo(
                    name=info.szDevice.rstrip("\x00") or f"monitor-{len(monitors) + 1}",
                    left=int(monitor.left),
                    top=int(monitor.top),
                    width=int(monitor.right - monitor.left),
                    height=int(monitor.bottom - monitor.top),
                    work_left=int(work.left),
                    work_top=int(work.top),
                    work_width=int(work.right - work.left),
                    work_height=int(work.bottom - work.top),
                )
            )
        return True

    try:
        user32.EnumDisplayMonitors(None, None, callback_type(callback), 0)
    except Exception:
        return [_primary_fallback()]
    return monitors or [_primary_fallback()]


def _find_worker_window() -> int | None:
    """Ask Explorer to expose the wallpaper WorkerW host and locate it."""
    if os.name != "nt":
        return None

    user32 = ctypes.windll.user32
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        return None

    result = ctypes.c_ulonglong()
    user32.SendMessageTimeoutW(
        progman,
        WM_SHELL_RERUN,
        0xD,
        0,
        SMTO_NORMAL,
        1000,
        ctypes.byref(result),
    )

    worker: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _data: int) -> bool:
        shell_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if shell_view:
            candidate = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            rect = Rect()
            if candidate and user32.GetWindowRect(candidate, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
                worker.append(candidate)
                return False
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return worker[0] if worker else progman


def _root_window(hwnd: int) -> int:
    if os.name != "nt":
        return hwnd
    root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def _get_window_long(hwnd: int, index: int) -> int:
    user32 = ctypes.windll.user32
    if hasattr(user32, "GetWindowLongPtrW"):
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        return int(user32.GetWindowLongPtrW(hwnd, index))
    return int(user32.GetWindowLongW(hwnd, index))


def _set_window_long(hwnd: int, index: int, value: int) -> None:
    user32 = ctypes.windll.user32
    if hasattr(user32, "SetWindowLongPtrW"):
        user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.SetWindowLongPtrW(hwnd, index, value)
    else:
        user32.SetWindowLongW(hwnd, index, value)


def set_window_desktop_style(hwnd: int, locked: bool) -> dict[str, int | bool]:
    """Apply a taskbar-free popup style and optional click-through behavior."""
    if os.name != "nt":
        return {"hwnd": hwnd, "locked": locked, "click_through": False}

    root = _root_window(hwnd)
    exstyle = _get_window_long(root, GWL_EXSTYLE)
    exstyle = (exstyle | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    if locked:
        exstyle |= WS_EX_TRANSPARENT
    else:
        exstyle &= ~WS_EX_TRANSPARENT
    _set_window_long(root, GWL_EXSTYLE, exstyle)
    return {
        "hwnd": root,
        "locked": locked,
        "click_through": bool(exstyle & WS_EX_TRANSPARENT),
    }


def attach_to_desktop(hwnd: int, x: int, y: int, width: int, height: int) -> dict[str, int | bool | str]:
    """Parent a skin to Explorer's wallpaper host and place it."""
    if os.name != "nt":
        return {"attached": False, "fallback": True, "reason": "non-windows"}

    user32 = ctypes.windll.user32
    root = _root_window(hwnd)
    worker = _find_worker_window()
    if not worker:
        # Some Windows shells omit Progman/SHELLDLL_DefView. Keep the skin as
        # a normal bottom-level popup instead of parenting it to a zero-sized
        # WorkerW that would make the window invisible.
        user32.SetParent(root, 0)
        style = _get_window_long(root, GWL_STYLE)
        _set_window_long(root, GWL_STYLE, (style | WS_POPUP) & ~WS_CHILD)
        user32.SetWindowPos(
            root,
            HWND_BOTTOM,
            x,
            y,
            width,
            height,
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )
        user32.ShowWindow(root, SW_SHOWNOACTIVATE)
        return {"attached": False, "fallback": True, "reason": "WorkerW unavailable"}

    style = _get_window_long(root, GWL_STYLE)
    _set_window_long(root, GWL_STYLE, (style | WS_CHILD) & ~WS_POPUP)
    user32.SetParent(root, worker)

    point = wintypes.POINT(x, y)
    user32.ScreenToClient(worker, ctypes.byref(point))
    user32.SetWindowPos(
        root,
        0,
        int(point.x),
        int(point.y),
        width,
        height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )
    user32.ShowWindow(root, SW_SHOWNOACTIVATE)
    return {"attached": True, "fallback": False, "parent": int(worker)}


def desktop_layer_diagnostics() -> dict[str, Any]:
    """Return safe diagnostics without exposing window titles or secrets."""
    if os.name != "nt":
        return {"platform": os.name, "worker_available": False}
    user32 = ctypes.windll.user32
    progman = int(user32.FindWindowW("Progman", None) or 0)
    worker = _find_worker_window() or 0
    return {
        "platform": "windows",
        "progman_available": bool(progman),
        "worker_available": bool(worker),
        "worker_handle": worker,
        "monitor_count": len(enumerate_monitors()),
    }


def place_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """Place an attached skin using screen coordinates."""
    if os.name != "nt":
        return
    user32 = ctypes.windll.user32
    root = _root_window(hwnd)
    parent = user32.GetParent(root)
    point = wintypes.POINT(x, y)
    if parent:
        user32.ScreenToClient(parent, ctypes.byref(point))
    user32.SetWindowPos(
        root,
        0,
        int(point.x),
        int(point.y),
        width,
        height,
        SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )


def window_exists(hwnd: int) -> bool:
    return bool(os.name == "nt" and hwnd and ctypes.windll.user32.IsWindow(hwnd))
