"""Canvas renderers for NOVA's Rainmeter-style desktop modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import tkinter as tk

from .status_service import LocalSnapshot


TRANSPARENT = "#010203"
PANEL = "#0b131b"
PANEL_ALT = "#101d27"
LINE = "#2a4250"
TEXT = "#eaf4f8"
MUTED = "#8da3b0"
CYAN = "#48d7ff"
GREEN = "#47d18c"
AMBER = "#ffbe5c"
RED = "#ff6b6b"


@dataclass(frozen=True, slots=True)
class WidgetDefinition:
    id: str
    title: str
    width: int
    height: int


WIDGET_DEFINITIONS = {
    "clock": WidgetDefinition("clock", "Clock", 320, 86),
    "orb": WidgetDefinition("orb", "NOVA", 152, 152),
    "focus": WidgetDefinition("focus", "Current Focus", 360, 126),
    "system": WidgetDefinition("system", "System", 360, 92),
    "memory": WidgetDefinition("memory", "Memory", 360, 132),
    "activity": WidgetDefinition("activity", "Activity", 360, 154),
}


def _font(size: int, bold: bool = False) -> tuple[str, int, str]:
    return ("Segoe UI", size, "bold" if bold else "normal")


def _fit(text: str, max_chars: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 3)].rstrip() + "..."


def _text(canvas: tk.Canvas, x: int, y: int, value: str, *, size: int = 10,
          color: str = TEXT, bold: bool = False, anchor: str = "nw") -> None:
    canvas.create_text(x + 1, y + 1, text=value, fill="#000000", font=_font(size, bold), anchor=anchor)
    canvas.create_text(x, y, text=value, fill=color, font=_font(size, bold), anchor=anchor)


def _panel(canvas: tk.Canvas, width: int, height: int, title: str, *, accent: str = CYAN,
           editable: bool = False) -> None:
    canvas.create_rectangle(4, 4, width - 4, height - 4, fill=PANEL, outline=LINE, width=1)
    canvas.create_rectangle(4, 4, 8, height - 4, fill=accent, outline="")
    _text(canvas, 18, 13, title.upper(), size=8, color=accent, bold=True)
    if editable:
        _text(canvas, width - 18, 12, "EDIT", size=8, color=AMBER, bold=True, anchor="ne")
        canvas.create_rectangle(7, 7, width - 7, height - 7, outline=AMBER, dash=(4, 3), width=1)


def _voice_color(snapshot: LocalSnapshot) -> str:
    if snapshot.voice_status == "running":
        return GREEN
    if snapshot.voice_status == "offline":
        return AMBER
    return RED


def _render_clock(canvas: tk.Canvas, snapshot: LocalSnapshot, editable: bool) -> None:
    _panel(canvas, 320, 86, "Desktop time", accent=MUTED, editable=editable)
    _text(canvas, 20, 31, snapshot.now, size=29, bold=True)
    _text(canvas, 174, 43, snapshot.date, size=11, color=MUTED)
    _text(canvas, 174, 60, f"{snapshot.profile.title()} profile", size=8, color=MUTED)


def _render_orb(canvas: tk.Canvas, snapshot: LocalSnapshot, pulse: float, editable: bool) -> None:
    canvas.delete("all")
    width = 152
    height = 152
    center = 76
    base = 44 + int((pulse % 1.0) * 3)
    color = _voice_color(snapshot)
    canvas.create_oval(center - base - 9, center - base - 9, center + base + 9, center + base + 9, outline=LINE, width=1)
    canvas.create_arc(center - base - 9, center - base - 9, center + base + 9, center + base + 9,
                      start=(pulse * 360) % 360, extent=92, outline=color, width=2)
    canvas.create_oval(center - base, center - base, center + base, center + base, fill=PANEL, outline=color, width=2)
    canvas.create_oval(center - 17, center - 17, center + 17, center + 17, fill=color, outline="")
    canvas.create_oval(center - 7, center - 7, center + 7, center + 7, fill=TEXT, outline="")
    _text(canvas, center, 128, "NOVA", size=11, color=TEXT, bold=True, anchor="center")
    _text(canvas, center, 143, snapshot.voice_status.upper(), size=7, color=color, bold=True, anchor="center")
    if editable:
        canvas.create_rectangle(7, 7, width - 7, height - 7, outline=AMBER, dash=(4, 3), width=1)


def _render_focus(canvas: tk.Canvas, snapshot: LocalSnapshot, editable: bool) -> None:
    _panel(canvas, 360, 126, "Current focus", accent=CYAN, editable=editable)
    _text(canvas, 20, 35, _fit(snapshot.current_focus, 33), size=15, bold=True)
    _text(canvas, 20, 62, snapshot.command_status, size=9, color=MUTED)
    _text(canvas, 20, 86, "Double-click NOVA for commands", size=9, color=TEXT)


def _render_system(canvas: tk.Canvas, snapshot: LocalSnapshot, editable: bool) -> None:
    _panel(canvas, 360, 92, "System", accent=GREEN, editable=editable)
    values = (("CPU", snapshot.cpu), ("RAM", snapshot.ram), ("BAT", snapshot.battery), ("NET", snapshot.network))
    for index, (label, value) in enumerate(values):
        x = 20 + index * 78
        _text(canvas, x, 38, label, size=8, color=GREEN, bold=True)
        _text(canvas, x, 55, _fit(value, 9), size=9, bold=True)
    _text(canvas, 20, 76, _fit(f"Voice: {snapshot.voice_detail}", 46), size=8, color=MUTED)


def _render_memory(canvas: tk.Canvas, snapshot: LocalSnapshot, editable: bool) -> None:
    accent = GREEN if snapshot.vault_status == "Vault connected" else AMBER
    _panel(canvas, 360, 132, "Obsidian memory", accent=accent, editable=editable)
    _text(canvas, 20, 37, snapshot.vault_status, size=12, color=accent, bold=True)
    _text(canvas, 20, 61, "Latest conversation", size=8, color=MUTED, bold=True)
    _text(canvas, 20, 77, _fit(snapshot.latest_conversation, 38), size=9)
    _text(canvas, 20, 105, "Search with: memory <words>", size=8, color=MUTED)


def _render_activity(canvas: tk.Canvas, snapshot: LocalSnapshot, editable: bool) -> None:
    _panel(canvas, 360, 154, "Observable activity", accent=MUTED, editable=editable)
    for index, event in enumerate(snapshot.latest_tool_events[:3]):
        y = 38 + index * 34
        canvas.create_oval(20, y + 4, 26, y + 10, fill=CYAN if index == 0 else LINE, outline="")
        _text(canvas, 34, y, _fit(event, 38), size=8 if index else 9, color=TEXT if index == 0 else MUTED)


_RENDERERS: dict[str, Callable[[tk.Canvas, LocalSnapshot, bool], None]] = {
    "clock": _render_clock,
    "focus": _render_focus,
    "system": _render_system,
    "memory": _render_memory,
    "activity": _render_activity,
}


def render_widget(
    canvas: tk.Canvas,
    widget_id: str,
    snapshot: LocalSnapshot,
    *,
    pulse: float = 0.0,
    editable: bool = False,
) -> None:
    """Render one registered skin module."""
    canvas.delete("all")
    if widget_id == "orb":
        _render_orb(canvas, snapshot, pulse, editable)
        return
    renderer = _RENDERERS.get(widget_id)
    if renderer is None:
        canvas.create_text(16, 16, text=f"Unknown widget: {widget_id}", fill=RED, anchor="nw")
        return
    definition = WIDGET_DEFINITIONS[widget_id]
    renderer(canvas, snapshot, editable)
    canvas.configure(width=definition.width, height=definition.height)
