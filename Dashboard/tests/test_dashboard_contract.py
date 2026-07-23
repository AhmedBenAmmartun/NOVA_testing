from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = DASHBOARD_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(DASHBOARD_DIR))

# The production app uses NOVA's provisioned Windows venv. These light stubs
# keep the pure contract tests runnable in source-review environments where
# aiohttp/psutil/python-dotenv are intentionally absent.
try:
    import psutil  # noqa: F401
except ModuleNotFoundError:
    sys.modules["psutil"] = types.ModuleType("psutil")

try:
    import aiohttp  # noqa: F401
except ModuleNotFoundError:
    aiohttp_stub = types.ModuleType("aiohttp")
    aiohttp_stub.web = types.ModuleType("aiohttp.web")
    sys.modules["aiohttp"] = aiohttp_stub
    sys.modules["aiohttp.web"] = aiohttp_stub.web

try:
    import dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False
    sys.modules["dotenv"] = dotenv_stub

import actions  # noqa: E402
import feeds  # noqa: E402
import server  # noqa: E402
from nova_bridge import CommandStore  # noqa: E402


class DashboardContractTests(unittest.TestCase):
    def test_snapshot_declares_live_contract(self) -> None:
        snapshot = server.Hub().snapshot()
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(snapshot["contractVersion"], server.CONTRACT_VERSION)
        self.assertEqual(snapshot["mode"], "live")

    def test_websocket_origin_rejects_untrusted_sites(self) -> None:
        request = SimpleNamespace(
            host="127.0.0.1:8787",
            headers={"Origin": "https://example.com"},
        )
        self.assertFalse(server._origin_allowed(request))

    def test_websocket_origin_accepts_local_ui(self) -> None:
        request = SimpleNamespace(
            host="127.0.0.1:8787",
            headers={"Origin": "http://127.0.0.1:8787"},
        )
        self.assertTrue(server._origin_allowed(request))

    def test_unknown_action_is_ignored(self) -> None:
        self.assertEqual(actions.handle({"type": "unknown"}, {}, None), [])

    def test_approval_action_enters_private_agent_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bridge = CommandStore(Path(directory))
            bridge.heartbeat("session_one")
            approvals = feeds.ApprovalsTracker()
            approvals.pending["abc123"] = {
                "id": "abc123",
                "action": "Close app",
                "detail": "Close Notepad",
                "at": 0,
            }
            replies = actions.handle(
                {
                    "type": "approval",
                    "id": "abc123",
                    "decision": "approve",
                },
                {},
                approvals,
                bridge,
            )
            self.assertEqual(len(replies), 2)
            claimed = bridge.claim("session_one")
            self.assertEqual(len(claimed), 1)
            self.assertEqual(claimed[0][1]["kind"], "approval")
            self.assertEqual(claimed[0][1]["payload"]["decision"], "approve")

    def test_conversation_parser_reads_real_turn_format(self) -> None:
        transcript = (
            "### Ahmed - 10:15:01\n\nOpen the dashboard.\n\n"
            "### NOVA - 10:15:03\n\nOpening it now.\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.md"
            path.write_text(transcript, encoding="utf-8")
            self.assertEqual(
                feeds.parse_conversation_turns(path),
                [
                    {"who": "user", "text": "Open the dashboard."},
                    {"who": "nova", "text": "Opening it now."},
                ],
            )


if __name__ == "__main__":
    unittest.main()
