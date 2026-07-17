"""Focused tests for native NOVA desktop skin state and safe commands."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from .command_service import SafeCommandService
from .desktop_host import MonitorInfo
from .skin_state import (
    PROFILE_WIDGETS,
    SkinStateStore,
    default_widget_states,
    snap_position,
    widget_visible,
)


class SkinStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.monitor = MonitorInfo("DISPLAY1", -1920, 0, 1920, 1080, -1920, 0, 1920, 1040)

    def test_default_layout_is_right_aligned_and_monitor_relative(self) -> None:
        widgets = default_widget_states(self.monitor)
        self.assertEqual(widgets["clock"].monitor, "DISPLAY1")
        self.assertGreaterEqual(widgets["clock"].x, 0)
        self.assertLessEqual(widgets["clock"].x + widgets["clock"].width, self.monitor.work_width)
        self.assertGreaterEqual(widgets["clock"].y, 0)

    def test_legacy_state_migrates_to_v2(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "desktop_widget_state.json"
            primary = root / "desktop_skin_state.json"
            legacy.write_text(json.dumps({"mode": "orb", "x": -1800, "y": 100}), encoding="utf-8")
            state = SkinStateStore(primary, legacy).load(self.monitor)
            self.assertEqual(state.version, 3)
            self.assertEqual(state.profile, "minimal")
            self.assertEqual(state.widgets["orb"].x, 120)
            self.assertEqual(state.widgets["orb"].y, 100)
            self.assertTrue(primary.exists())

    def test_profile_visibility_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = SkinStateStore(Path(directory) / "state.json").reset(self.monitor)
            state.profile = "study"
            self.assertTrue(widget_visible(state, "memory"))
            self.assertFalse(widget_visible(state, "system"))
            self.assertEqual(PROFILE_WIDGETS["study"], {"clock", "orb", "focus", "memory", "activity"})

    def test_positions_snap_to_eight_pixel_grid(self) -> None:
        self.assertEqual(snap_position(13, 22), (16, 24))


class SafeCommandTests(unittest.TestCase):
    def test_help_is_available_without_network(self) -> None:
        result = SafeCommandService().execute("help")
        self.assertTrue(result.ok)
        self.assertIn("find", result.message)

    def test_sensitive_commands_are_not_exposed(self) -> None:
        result = SafeCommandService().execute("close Chrome")
        self.assertFalse(result.ok)
        self.assertEqual(result.action, "confirmation_required")
        self.assertEqual(result.sensitivity, "sensitive")

    def test_unknown_commands_do_not_fall_through_to_shell(self) -> None:
        result = SafeCommandService().execute("run arbitrary shell command")
        self.assertFalse(result.ok)
        self.assertEqual(result.action, "none")


if __name__ == "__main__":
    unittest.main()
