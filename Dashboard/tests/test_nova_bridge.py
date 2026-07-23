from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from nova_bridge import BridgeValidationError, CommandStore  # noqa: E402


class NovaBridgeTests(unittest.TestCase):
    def test_delegate_round_trip_is_atomic_and_targeted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CommandStore(Path(directory))
            store.heartbeat("session_one")
            command = store.enqueue_delegate("Open the dashboard")

            self.assertEqual(command["target_session"], "session_one")
            self.assertEqual(store.claim("session_two"), [])

            claimed = store.claim("session_one")
            self.assertEqual(len(claimed), 1)
            claimed_path, claimed_command = claimed[0]
            self.assertFalse((store.inbox / f"{command['id']}.json").exists())
            self.assertTrue(claimed_path.exists())

            store.complete(
                claimed_path,
                claimed_command,
                "completed",
                "Delivered to NOVA.",
            )
            self.assertFalse(claimed_path.exists())
            results = store.read_results()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["contract"], "nova.local-command.v1")
            self.assertEqual(results[0]["id"], command["id"])
            self.assertEqual(results[0]["kind"], "delegate")
            self.assertEqual(results[0]["status"], "completed")
            self.assertEqual(results[0]["message"], "Delivered to NOVA.")
            self.assertIsInstance(results[0]["completed_at"], float)

    def test_approval_contract_rejects_unknown_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CommandStore(Path(directory))
            with self.assertRaises(BridgeValidationError):
                store.enqueue_approval("abc123", "maybe")

    def test_expired_command_is_reported_without_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CommandStore(Path(directory))
            command = store.enqueue_delegate("A short-lived command")
            path = store.inbox / f"{command['id']}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["expires_at"] = time.time() - 1
            path.write_text(json.dumps(payload), encoding="utf-8")

            self.assertEqual(store.claim("session_one"), [])
            result = store.read_results()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["status"], "expired")

    def test_only_owner_can_clear_active_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CommandStore(Path(directory))
            store.heartbeat("session_one")
            store.clear_heartbeat("session_two")
            self.assertTrue(store.active_session()["active"])
            store.clear_heartbeat("session_one")
            self.assertFalse(store.active_session()["active"])


if __name__ == "__main__":
    unittest.main()
