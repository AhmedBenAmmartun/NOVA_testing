"""Versioned state and layout persistence for NOVA desktop skins."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .desktop_host import MonitorInfo


STATE_VERSION = 3
PROFILE_NAMES = ("minimal", "focus", "study", "system")
WIDGET_IDS = ("clock", "orb", "focus", "system", "memory", "activity")
PROFILE_WIDGETS = {
    "minimal": frozenset({"clock", "orb", "system"}),
    "focus": frozenset(WIDGET_IDS),
    "study": frozenset({"clock", "orb", "focus", "memory", "activity"}),
    "system": frozenset({"clock", "orb", "system", "activity"}),
}

APP_STATE_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "NOVA"
STATE_PATH = APP_STATE_DIR / "desktop_skin_state.json"
LEGACY_STATE_PATH = APP_STATE_DIR / "desktop_widget_state.json"


@dataclass(slots=True)
class WidgetState:
    """A widget position relative to its monitor work area."""

    id: str
    monitor: str
    x: int
    y: int
    width: int
    height: int
    visible: bool = True


@dataclass(slots=True)
class SkinState:
    version: int = STATE_VERSION
    profile: str = "focus"
    locked: bool = True
    theme: str = "graphite"
    startup_enabled: bool = False
    hidden: bool = False
    current_focus: str = ""
    widgets: dict[str, WidgetState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["widgets"] = {
            widget_id: asdict(widget)
            for widget_id, widget in self.widgets.items()
        }
        return data


def _right_aligned(monitor: MonitorInfo, width: int, margin: int = 28) -> int:
    return max(16, monitor.work_width - width - margin)


def default_widget_states(monitor: MonitorInfo) -> dict[str, WidgetState]:
    """Return the wallpaper-first default layout for one monitor."""
    specs = {
        "clock": (320, 86, 28, 28),
        "orb": (152, 152, 58, 116),
        "focus": (360, 126, 28, 276),
        "system": (360, 92, 28, 410),
        "memory": (360, 132, 28, 510),
        "activity": (360, 154, 28, 650),
    }
    result: dict[str, WidgetState] = {}
    for widget_id, (width, height, margin, y) in specs.items():
        x = _right_aligned(monitor, width, margin)
        max_y = max(16, monitor.work_height - height - 16)
        result[widget_id] = WidgetState(
            id=widget_id,
            monitor=monitor.name,
            x=x,
            y=min(max(16, y), max_y),
            width=width,
            height=height,
        )
    return result


def widget_visible(state: SkinState, widget_id: str) -> bool:
    widget = state.widgets.get(widget_id)
    return bool(
        widget
        and widget.visible
        and widget_id in PROFILE_WIDGETS.get(state.profile, PROFILE_WIDGETS["focus"])
    )


class SkinStateStore:
    """Load, migrate, validate, and atomically save desktop skin state."""

    def __init__(
        self,
        state_path: Path = STATE_PATH,
        legacy_path: Path = LEGACY_STATE_PATH,
    ) -> None:
        self.state_path = state_path
        self.legacy_path = legacy_path

    def load(self, primary_monitor: MonitorInfo) -> SkinState:
        if self.state_path.exists():
            try:
                raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                state = self._validate(self._from_dict(raw), primary_monitor)
                self.save(state)
                return state
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        state = self._migrate_legacy(primary_monitor)
        self.save(state)
        return state

    def save(self, state: SkinState) -> None:
        state.version = STATE_VERSION
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.state_path)

    def reset(self, monitor: MonitorInfo) -> SkinState:
        state = SkinState(widgets=default_widget_states(monitor))
        self.save(state)
        return state

    def _migrate_legacy(self, monitor: MonitorInfo) -> SkinState:
        state = SkinState(widgets=default_widget_states(monitor))
        if not self.legacy_path.exists():
            return state

        try:
            legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return state

        mode = str(legacy.get("mode", "mini"))
        state.profile = "minimal" if mode == "orb" else "focus"
        try:
            old_x = int(legacy.get("x", -1)) - monitor.work_left
            old_y = int(legacy.get("y", -1)) - monitor.work_top
        except (TypeError, ValueError):
            old_x = old_y = -1

        if old_x >= 0 and old_y >= 0:
            orb = state.widgets["orb"]
            orb.x = min(max(0, old_x), max(0, monitor.work_width - orb.width))
            orb.y = min(max(0, old_y), max(0, monitor.work_height - orb.height))
        return state

    def _from_dict(self, raw: dict[str, Any]) -> SkinState:
        raw_widgets = raw.get("widgets") if isinstance(raw, dict) else {}
        widgets: dict[str, WidgetState] = {}
        if isinstance(raw_widgets, dict):
            for widget_id, value in raw_widgets.items():
                if not isinstance(value, dict):
                    continue
                try:
                    widgets[str(widget_id)] = WidgetState(
                        id=str(value.get("id", widget_id)),
                        monitor=str(value.get("monitor", "")),
                        x=int(value.get("x", 0)),
                        y=int(value.get("y", 0)),
                        width=int(value.get("width", 240)),
                        height=int(value.get("height", 100)),
                        visible=bool(value.get("visible", True)),
                    )
                except (TypeError, ValueError):
                    continue

        return SkinState(
            version=int(raw.get("version", 0)),
            profile=str(raw.get("profile", "focus")),
            locked=bool(raw.get("locked", True)),
            theme=str(raw.get("theme", "graphite")),
            startup_enabled=bool(raw.get("startup_enabled", False)),
            hidden=bool(raw.get("hidden", False)),
            current_focus=str(raw.get("current_focus", ""))[:240],
            widgets=widgets,
        )

    def _validate(self, state: SkinState, monitor: MonitorInfo) -> SkinState:
        if state.version < STATE_VERSION:
            # Version 2 was an intermediate prototype that stored some
            # positions in screen pixels. Rebuild only the layout while
            # preserving the user's selected profile and settings.
            state.widgets = default_widget_states(monitor)
            state.locked = True
        state.version = STATE_VERSION
        if state.profile not in PROFILE_NAMES:
            state.profile = "focus"
        if state.theme not in {"graphite", "light"}:
            state.theme = "graphite"

        defaults = default_widget_states(monitor)
        for widget_id in WIDGET_IDS:
            widget = state.widgets.get(widget_id)
            if widget is None:
                state.widgets[widget_id] = defaults[widget_id]
                continue
            widget.id = widget_id
            widget.width = max(128, min(widget.width, monitor.work_width))
            widget.height = max(72, min(widget.height, monitor.work_height))
            if not widget.monitor:
                widget.monitor = monitor.name
            widget.x = min(max(0, widget.x), max(0, monitor.work_width - widget.width))
            widget.y = min(max(0, widget.y), max(0, monitor.work_height - widget.height))
        return state


def snap_position(x: int, y: int, grid: int = 8) -> tuple[int, int]:
    """Snap a layout position to the skin grid."""
    safe_grid = max(1, grid)
    return round(x / safe_grid) * safe_grid, round(y / safe_grid) * safe_grid


def absolute_position(widget: WidgetState, monitor: MonitorInfo) -> tuple[int, int]:
    """Translate a monitor-relative position to screen coordinates."""
    return monitor.work_left + widget.x, monitor.work_top + widget.y
