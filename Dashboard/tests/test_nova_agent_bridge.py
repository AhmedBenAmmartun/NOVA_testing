from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from nova_agent_bridge import (  # noqa: E402
    dashboard_bridge_loop,
    dispatch_dashboard_command,
    stop_dashboard_bridge,
)
from nova_bridge import CommandStore  # noqa: E402


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_reply(self, **kwargs) -> None:
        self.calls.append(kwargs)


class FakePermissions:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def approve(self, *, action_id: str, scope: str) -> str:
        self.calls.append(("approve", action_id, scope))
        return "Approved in agent process."

    def deny(self, *, action_id: str) -> str:
        self.calls.append(("deny", action_id))
        return "Denied in agent process."


class NovaAgentBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegate_is_injected_as_user_input(self) -> None:
        session = FakeSession()
        result = await dispatch_dashboard_command(
            session,
            {"kind": "delegate", "payload": {"text": "Check my tasks"}},
            FakePermissions(),
        )
        self.assertIn("delivered", result)
        self.assertEqual(
            session.calls,
            [{"user_input": "Check my tasks", "allow_interruptions": True}],
        )

    async def test_approval_uses_in_process_permission_engine(self) -> None:
        permissions = FakePermissions()
        result = await dispatch_dashboard_command(
            FakeSession(),
            {
                "kind": "approval",
                "payload": {
                    "action_id": "abc123",
                    "decision": "approve",
                    "scope": "once",
                },
            },
            permissions,
        )
        self.assertEqual(result, "Approved in agent process.")
        self.assertEqual(permissions.calls, [("approve", "abc123", "once")])

    async def test_poll_loop_returns_result_to_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CommandStore(Path(directory))
            session = FakeSession()
            permissions = FakePermissions()
            store.heartbeat("session_one")
            store.enqueue_delegate("Summarize the current page")
            task = asyncio.create_task(
                dashboard_bridge_loop(
                    session,
                    "session_one",
                    store,
                    permissions,
                )
            )
            results = []
            for _ in range(20):
                await asyncio.sleep(0.05)
                results = store.read_results()
                if results:
                    break
            await stop_dashboard_bridge(task)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "completed")
            self.assertEqual(session.calls[0]["user_input"], "Summarize the current page")


if __name__ == "__main__":
    unittest.main()
