from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nova_os.catalog import build_default_capability_manager
from tools import class_capture as class_tools


class FakeActive:
    def __init__(self, root: Path):
        self.course = "COT3400"
        self.session_id = "session-test"
        self.session_path = str(root)
        self.started_at = "2026-08-24T16:00:00+00:00"


class OneNovaClassCapabilityTests(unittest.TestCase):
    def test_class_intelligence_is_default_active(self):
        manager = build_default_capability_manager()
        spec = manager.registry.get("class_intelligence")
        self.assertIsNotNone(spec)
        self.assertTrue(spec.default_active)
        self.assertTrue(manager.is_active("class_intelligence"))
        self.assertIn("start_class_capture", spec.tool_names)
        self.assertIn("end_class_capture", spec.tool_names)

    def test_recent_transcript_reader_uses_readable_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "transcript.txt").write_text(
                "[00:01] [Teacher] Big O notation\n"
                "[00:02] [Teacher] Insertion sort\n",
                encoding="utf-8",
            )
            text = class_tools._read_recent_transcript(root, max_lines=1)
            self.assertIn("Insertion sort", text)
            self.assertNotIn("Big O notation", text)

    def test_status_reports_active_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            active = FakeActive(Path(tmp))
            with patch.object(class_tools, "read_active_session", return_value=active):
                result = asyncio.run(class_tools.get_class_capture_status())
            self.assertIn("COT3400", result)
            self.assertIn("session-test", result)

    def test_end_class_uses_existing_control_finalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "audio.wav").write_bytes(b"RIFF" + b"x" * 100)
            (root / "session.json").write_text('{"status":"completed"}', encoding="utf-8")
            active = FakeActive(root)
            with (
                patch.object(class_tools, "request_stop", return_value=active),
                patch.object(class_tools, "wait_until_inactive", return_value=True),
                patch.object(
                    class_tools,
                    "close_legacy_launcher_after_save",
                    return_value="class capture process tree closed (2 process(es))",
                ) as cleanup,
            ):
                result = asyncio.run(class_tools.end_class_capture())
            cleanup.assert_called_once_with(active)
            self.assertIn("finalized", result)
            self.assertIn("transcript saved", result)
            self.assertIn("audio saved", result)
            self.assertIn("Capture cleanup", result)
            self.assertIn("still running normally", result)


if __name__ == "__main__":
    unittest.main()
