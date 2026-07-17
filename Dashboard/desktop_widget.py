"""Run the native NOVA Rainmeter-style desktop skin."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))
    __package__ = "Dashboard"

from .command_service import CommandResult, SafeCommandService
from .desktop_host import (
    attach_to_desktop,
    desktop_layer_diagnostics,
    enumerate_monitors,
    place_window,
    set_window_desktop_style,
    window_exists,
)
from .skin_registry import TRANSPARENT, WIDGET_DEFINITIONS, render_widget
from .skin_state import (
    PROFILE_NAMES,
    SkinState,
    SkinStateStore,
    WidgetState,
    absolute_position,
    snap_position,
    widget_visible,
)
from .status_service import LocalSnapshot, LocalStatusService


START_SCRIPT = Path(__file__).resolve().parent / "start_desktop_widget.ps1"
APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
STARTUP_FILE = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "NOVA Desktop Skin.cmd"
MUTEX_NAME = "Local\\NOVA.DesktopSkin.v2"
MODE_TO_PROFILE = {
    "orb": "minimal",
    "mini": "focus",
    "compact": "focus",
    "full": "focus",
    "minimal": "minimal",
    "focus": "focus",
    "study": "study",
    "system": "system",
}


class SingleInstance:
    """Keep a process-wide Windows mutex alive for the application lifetime."""

    def __init__(self, name: str) -> None:
        self.handle: int | None = None
        self.already_running = False
        if os.name != "nt":
            return
        user32 = ctypes.windll.kernel32
        self.handle = int(user32.CreateMutexW(None, False, name) or 0)
        self.already_running = ctypes.windll.kernel32.GetLastError() == 183

    def close(self) -> None:
        if self.handle and os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


class GlobalHotkey:
    """Deliver Ctrl+Alt+N to the Tk thread without taking focus."""

    WM_HOTKEY = 0x0312
    MOD_CONTROL = 0x0002
    MOD_ALT = 0x0001
    MOD_NOREPEAT = 0x4000

    class Message(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("message", ctypes.c_uint),
            ("wParam", ctypes.c_size_t),
            ("lParam", ctypes.c_ssize_t),
            ("time", ctypes.c_uint),
            ("pt_x", ctypes.c_long),
            ("pt_y", ctypes.c_long),
        ]

    def __init__(self, events: queue.Queue[str]) -> None:
        self.events = events
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.thread_id: int | None = None
        self.registered = False

    def start(self) -> None:
        if os.name != "nt":
            return
        self.thread = threading.Thread(target=self._run, name="nova-hotkey", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self.thread_id = int(ctypes.windll.kernel32.GetCurrentThreadId())
        hotkey_id = 0x4E4F
        self.registered = bool(
            user32.RegisterHotKey(
                None,
                hotkey_id,
                self.MOD_CONTROL | self.MOD_ALT | self.MOD_NOREPEAT,
                ord("N"),
            )
        )
        if not self.registered:
            return
        message = self.Message()
        while not self.stop_event.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == self.WM_HOTKEY:
                self.events.put("command")
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        self.stop_event.set()
        if os.name == "nt" and self.registered and self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)


class TrayController:
    """Optional system tray bridge; the widget remains usable without it."""

    def __init__(self, app: "DesktopSkinApp") -> None:
        self.app = app
        self.icon: Any = None
        self.thread: threading.Thread | None = None
        try:
            import pystray
            from PIL import Image, ImageDraw
        except Exception:
            return

        image = Image.new("RGBA", (64, 64), (7, 16, 24, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, 56, 56), outline=(72, 215, 255, 255), width=3)
        draw.ellipse((24, 24, 40, 40), fill=(72, 215, 255, 255))
        self.icon = pystray.Icon(
            "nova-desktop-skin",
            image,
            "NOVA Desktop Skin",
            pystray.Menu(
                pystray.MenuItem("Edit layout", lambda _icon, _item: self._call(self.app.toggle_edit)),
                pystray.MenuItem("Focus profile", lambda _icon, _item: self._call(lambda: self.app.set_profile("focus"))),
                pystray.MenuItem("Study / Quiz profile", lambda _icon, _item: self._call(lambda: self.app.set_profile("study"))),
                pystray.MenuItem("System profile", lambda _icon, _item: self._call(lambda: self.app.set_profile("system"))),
                pystray.MenuItem("Refresh", lambda _icon, _item: self._call(self.app.refresh)),
                pystray.MenuItem("Show skins", lambda _icon, _item: self._call(self.app.show_skins)),
                pystray.MenuItem("Command bar", lambda _icon, _item: self._call(self.app.show_command_bar)),
                pystray.MenuItem("Quit", lambda _icon, _item: self._call(self.app.close)),
            ),
        )

    def _call(self, callback: Any) -> None:
        self.app.root.after(0, callback)

    def start(self) -> None:
        if self.icon is None:
            return
        self.thread = threading.Thread(target=self.icon.run, name="nova-tray", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.icon is not None:
            self.icon.stop()


class SkinWindow:
    """One independent desktop module window."""

    def __init__(self, app: "DesktopSkinApp", widget_id: str, state: WidgetState) -> None:
        self.app = app
        self.widget_id = widget_id
        self.state = state
        definition = WIDGET_DEFINITIONS[widget_id]
        self.window = tk.Toplevel(app.root)
        self.window.title(f"NOVA {definition.title}")
        self.window.overrideredirect(True)
        self.window.configure(bg=TRANSPARENT)
        try:
            self.window.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(
            self.window,
            width=state.width,
            height=state.height,
            bg=TRANSPARENT,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", self._context)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.window.bind("<Escape>", lambda _event: self.app.close())
        self.window.update_idletasks()
        self.hwnd = int(self.window.winfo_id())
        self.render()
        self.attach()

    def attach(self) -> None:
        monitor = self.app.monitor_for(self.state.monitor)
        x, y = absolute_position(self.state, monitor)
        attach_to_desktop(self.hwnd, x, y, self.state.width, self.state.height)
        self.apply_style()
        place_window(self.hwnd, x, y, self.state.width, self.state.height)

    def apply_style(self) -> None:
        locked = self.app.state.locked and self.widget_id != "orb" and not self.app.editing
        set_window_desktop_style(self.hwnd, locked=locked)

    def render(self) -> None:
        snapshot = self.app.snapshot
        render_widget(
            self.canvas,
            self.widget_id,
            snapshot,
            pulse=self.app.pulse,
            editable=self.app.editing,
        )

    def place(self) -> None:
        monitor = self.app.monitor_for(self.state.monitor)
        x, y = absolute_position(self.state, monitor)
        x, y = monitor.clamp(x, y, self.state.width, self.state.height)
        place_window(self.hwnd, x, y, self.state.width, self.state.height)

    def _press(self, event: tk.Event) -> None:
        if not self.app.editing or self.widget_id == "orb" and self.app.state.locked:
            return
        self.app.drag_start = (self.widget_id, int(event.x_root), int(event.y_root), self.state.x, self.state.y)

    def _drag(self, event: tk.Event) -> None:
        if not self.app.drag_start or not self.app.editing:
            return
        widget_id, start_x, start_y, original_x, original_y = self.app.drag_start
        if widget_id != self.widget_id:
            return
        monitor = self.app.monitor_for(self.state.monitor)
        x, y = snap_position(original_x + int(event.x_root) - start_x, original_y + int(event.y_root) - start_y)
        x, y = monitor.clamp(monitor.work_left + x, monitor.work_top + y, self.state.width, self.state.height)
        self.state.x = x - monitor.work_left
        self.state.y = y - monitor.work_top
        self.place()

    def _release(self, _event: tk.Event) -> None:
        if self.app.drag_start:
            self.app.drag_start = None
            self.app.save_state()

    def _double_click(self, _event: tk.Event) -> None:
        if self.widget_id == "orb":
            self.app.show_command_bar()

    def _context(self, event: tk.Event) -> None:
        self.app.show_context_menu(event.x_root, event.y_root)

    def destroy(self) -> None:
        if window_exists(self.hwnd):
            self.window.destroy()


class CommandBar:
    def __init__(self, app: "DesktopSkinApp") -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self.window.title("NOVA Command Bar")
        self.window.overrideredirect(True)
        self.window.configure(bg="#0b131b")
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.value = tk.StringVar()
        self.entry = tk.Entry(
            self.window,
            textvariable=self.value,
            bg="#101d27",
            fg="#eaf4f8",
            insertbackground="#48d7ff",
            relief="flat",
            font=("Segoe UI", 13),
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(14, 8), pady=14)
        self.submit = tk.Button(
            self.window,
            text="Run",
            command=self.execute,
            bg="#48d7ff",
            fg="#071018",
            activebackground="#eaf4f8",
            relief="flat",
            bd=0,
            font=("Segoe UI", 10, "bold"),
            padx=12,
        )
        self.submit.pack(side="right", padx=(0, 14), pady=14)
        self.output = tk.Label(
            self.window,
            text="Safe commands: help, find, open, read, memory, conversation",
            bg="#0b131b",
            fg="#8da3b0",
            justify="left",
            anchor="w",
            wraplength=620,
            font=("Segoe UI", 9),
        )
        self.output.pack(fill="x", padx=14, pady=(0, 14))
        self.entry.bind("<Return>", lambda _event: self.execute())
        self.entry.bind("<Escape>", lambda _event: self.close())
        self.window.update_idletasks()
        width = 680
        height = 120
        x = max(12, (self.window.winfo_screenwidth() - width) // 2)
        y = max(12, self.window.winfo_screenheight() - height - 70)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.entry.focus_force()
        self.result_queue: queue.Queue[CommandResult] = queue.Queue()
        self.window.after(100, self.poll_result)

    def execute(self) -> None:
        text = self.value.get().strip()
        if not text:
            return
        self.submit.configure(state="disabled")
        self.output.configure(text="Working locally...")
        threading.Thread(target=self._run, args=(text,), daemon=True).start()

    def _run(self, text: str) -> None:
        result = self.app.command_service.execute(text)
        self.result_queue.put(result)

    def poll_result(self) -> None:
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            if self.window.winfo_exists():
                self.window.after(100, self.poll_result)
            return
        self.output.configure(
            text=result.message,
            fg="#47d18c" if result.ok else "#ffbe5c" if result.sensitivity == "sensitive" else "#ff6b6b",
        )
        self.submit.configure(state="normal")
        self.app.command_status = "Command completed" if result.ok else "Command needs attention"
        self.app.refresh()

    def close(self) -> None:
        self.window.destroy()
        self.app.command_bar = None


class DesktopSkinApp:
    def __init__(self, root: tk.Tk, profile: str | None = None, no_tray: bool = False) -> None:
        self.root = root
        self.root.withdraw()
        self.root.configure(bg=TRANSPARENT)
        self.monitors = enumerate_monitors()
        self.primary_monitor = self.monitors[0]
        self.state_store = SkinStateStore()
        self.state = self.state_store.load(self.primary_monitor)
        if profile in PROFILE_NAMES:
            self.state.profile = profile
        self.snapshot: LocalSnapshot = LocalStatusService().snapshot(
            current_focus=self.state.current_focus,
            profile=self.state.profile,
        )
        self.status_service = LocalStatusService()
        self.command_service = SafeCommandService()
        self.command_status = "Ready for safe commands"
        self.windows: dict[str, SkinWindow] = {}
        self.command_bar: CommandBar | None = None
        self.drag_start: tuple[str, int, int, int, int] | None = None
        self.editing = not self.state.locked
        self.pulse = 0.0
        self.hotkey_events: queue.Queue[str] = queue.Queue()
        self.hotkey = GlobalHotkey(self.hotkey_events)
        self.tray = TrayController(self) if not no_tray else None
        self.context_menu: tk.Menu | None = None
        self.build_windows()
        self.hotkey.start()
        if self.tray:
            self.tray.start()
        self.root.after(1000, self.refresh)
        self.root.after(40, self.animate)
        self.root.after(200, self.poll_hotkeys)
        self.root.after(2500, self.reconnect_desktop)

    def monitor_for(self, name: str) -> Any:
        for monitor in self.monitors:
            if monitor.name == name:
                return monitor
        return self.primary_monitor

    def build_windows(self) -> None:
        for window in self.windows.values():
            window.destroy()
        self.windows.clear()
        for widget_id, state in self.state.widgets.items():
            if widget_visible(self.state, widget_id) and widget_id in WIDGET_DEFINITIONS and not self.state.hidden:
                self.windows[widget_id] = SkinWindow(self, widget_id, state)

    def refresh(self) -> None:
        self.snapshot = self.status_service.snapshot(
            current_focus=self.state.current_focus,
            profile=self.state.profile,
            command_status=self.command_status,
        )
        for window in self.windows.values():
            window.render()
            window.apply_style()
            window.place()

    def animate(self) -> None:
        self.pulse = (self.pulse + 0.012) % 1.0
        orb = self.windows.get("orb")
        if orb:
            orb.render()
        self.root.after(40, self.animate)

    def reconnect_desktop(self) -> None:
        for window in self.windows.values():
            if not window_exists(window.hwnd):
                continue
            window.attach()
        self.root.after(2500, self.reconnect_desktop)

    def poll_hotkeys(self) -> None:
        try:
            while True:
                event = self.hotkey_events.get_nowait()
                if event == "command":
                    self.show_command_bar()
        except queue.Empty:
            pass
        self.root.after(200, self.poll_hotkeys)

    def save_state(self) -> None:
        self.state_store.save(self.state)

    def toggle_edit(self) -> None:
        self.editing = not self.editing
        self.state.locked = not self.editing
        self.save_state()
        self.refresh()

    def set_profile(self, profile: str) -> None:
        if profile not in PROFILE_NAMES:
            return
        self.state.profile = profile
        self.state.hidden = False
        self.save_state()
        self.build_windows()
        self.refresh()

    def reset_layout(self) -> None:
        self.state = self.state_store.reset(self.primary_monitor)
        self.editing = False
        self.build_windows()
        self.refresh()

    def show_command_bar(self) -> None:
        if self.command_bar is not None and self.command_bar.window.winfo_exists():
            self.command_bar.entry.focus_force()
            return
        self.command_bar = CommandBar(self)

    def show_context_menu(self, x: int, y: int) -> None:
        if self.context_menu is not None:
            self.context_menu.destroy()
        self.context_menu = tk.Menu(self.root, tearoff=False, bg="#101d27", fg="#eaf4f8", activebackground="#48d7ff")
        self.context_menu.add_command(label="Lock layout" if self.editing else "Edit layout", command=self.toggle_edit)
        profile_menu = tk.Menu(self.context_menu, tearoff=False, bg="#101d27", fg="#eaf4f8", activebackground="#48d7ff")
        for profile in PROFILE_NAMES:
            profile_menu.add_command(label=profile.title(), command=lambda value=profile: self.set_profile(value))
        self.context_menu.add_cascade(label="Profiles", menu=profile_menu)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Safe command bar", command=self.show_command_bar)
        self.context_menu.add_command(label="Refresh", command=self.refresh)
        self.context_menu.add_command(label="Start voice NOVA", command=self.start_voice_agent)
        self.context_menu.add_command(label="Enable startup" if not self.state.startup_enabled else "Disable startup", command=self.toggle_startup)
        self.context_menu.add_command(label="Reset layout", command=self.reset_layout)
        self.context_menu.add_command(label="Hide skins", command=self.hide_skins)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Exit", command=self.close)
        self.context_menu.tk_popup(x, y)

    def hide_skins(self) -> None:
        self.state.hidden = True
        self.save_state()
        for window in self.windows.values():
            window.window.withdraw()

    def show_skins(self) -> None:
        self.state.hidden = False
        self.save_state()
        self.build_windows()
        self.refresh()

    def start_voice_agent(self) -> None:
        python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
        if not python.exists():
            python = Path(sys.executable)
        try:
            subprocess.Popen([str(python), str(PROJECT_ROOT / "agent.py"), "console"], cwd=PROJECT_ROOT)
            self.command_status = "Voice agent launch requested"
            self.refresh()
        except OSError:
            self.command_status = "Could not start voice agent"
            self.refresh()

    def toggle_startup(self) -> None:
        if os.name != "nt":
            self.command_status = "Windows startup is unavailable on this platform"
            return
        try:
            if self.state.startup_enabled:
                STARTUP_FILE.unlink(missing_ok=True)
                self.state.startup_enabled = False
            else:
                STARTUP_FILE.parent.mkdir(parents=True, exist_ok=True)
                command = f'@echo off\npowershell.exe -ExecutionPolicy Bypass -File "{START_SCRIPT}" -Profile {self.state.profile}\n'
                STARTUP_FILE.write_text(command, encoding="utf-8")
                self.state.startup_enabled = True
            self.save_state()
            self.command_status = "Startup setting updated"
            self.refresh()
        except OSError:
            self.command_status = "Could not update startup setting"
            self.refresh()

    def close(self) -> None:
        self.save_state()
        if self.command_bar is not None:
            self.command_bar.close()
        if self.context_menu is not None:
            self.context_menu.destroy()
        if self.tray:
            self.tray.stop()
        self.hotkey.stop()
        for window in self.windows.values():
            window.destroy()
        self.windows.clear()
        self.root.quit()


def diagnostics() -> int:
    service = LocalStatusService()
    snapshot = service.snapshot()
    payload = {
        "snapshot": snapshot.to_dict(),
        "desktop": desktop_layer_diagnostics(),
        "monitors": [asdict(monitor) for monitor in enumerate_monitors()],
        "state_path": str(SkinStateStore().state_path),
    }
    print(json.dumps(payload, indent=2, default=list))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NOVA Rainmeter-style desktop skin.")
    parser.add_argument("--mode", choices=sorted(MODE_TO_PROFILE), default=None, help="Legacy mode or profile name.")
    parser.add_argument("--profile", choices=PROFILE_NAMES, default=None)
    parser.add_argument("--self-test", action="store_true", help="Print local status and desktop diagnostics without opening windows.")
    parser.add_argument("--diagnostics", action="store_true", help="Print desktop-layer and monitor diagnostics.")
    parser.add_argument("--no-tray", action="store_true", help="Skip the optional tray icon.")
    args = parser.parse_args()

    if args.self_test or args.diagnostics:
        return diagnostics()

    instance = SingleInstance(MUTEX_NAME)
    if instance.already_running:
        instance.close()
        return 0

    try:
        if os.name == "nt":
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
        root = tk.Tk()
        profile = args.profile or MODE_TO_PROFILE.get(args.mode or "", None)
        DesktopSkinApp(root, profile=profile, no_tray=args.no_tray)
        root.mainloop()
        return 0
    finally:
        instance.close()


if __name__ == "__main__":
    raise SystemExit(main())
