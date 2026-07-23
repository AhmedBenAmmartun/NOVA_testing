from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nova_integrations.accounts import AccountRegistry
from nova_integrations.config import IntegrationConfig, MicrosoftConfig
from nova_integrations.connectors.base import AdminApprovalRequired, RateLimited, ReconnectRequired
from nova_integrations.connectors.microsoft_graph import MicrosoftGraphConnector
from nova_integrations.secrets import MemorySecretStore
from nova_integrations.storage import IntegrationDatabase


class FakeResponse:
    def __init__(self, status_code: int, data=None, headers=None) -> None:
        self.status_code = status_code
        self._data = data or {}
        self.headers = headers or {}
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._data


class GraphErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        config = IntegrationConfig(
            data_root=root,
            database_path=root / "db.sqlite",
            event_log_path=root / "events.jsonl",
            microsoft=MicrosoftConfig(client_id="public-client-id"),
        )
        db = IntegrationDatabase(config.database_path)
        secrets = MemorySecretStore()
        self.connector = MicrosoftGraphConnector(config, AccountRegistry(db, secrets), secrets)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @patch("nova_integrations.connectors.microsoft_graph.requests.get")
    def test_401_triggers_reconnect_not_loop(self, get) -> None:
        get.return_value = FakeResponse(401)
        with self.assertRaises(ReconnectRequired):
            self.connector._graph_get("/me", "token")
        self.assertEqual(get.call_count, 1)

    @patch("nova_integrations.connectors.microsoft_graph.requests.get")
    def test_429_preserves_retry_after(self, get) -> None:
        get.return_value = FakeResponse(429, headers={"Retry-After": "73"})
        with self.assertRaises(RateLimited) as caught:
            self.connector._graph_get("/me", "token")
        self.assertEqual(caught.exception.retry_after, 73)

    @patch("nova_integrations.connectors.microsoft_graph.requests.get")
    def test_403_consent_error_is_actionable(self, get) -> None:
        get.return_value = FakeResponse(
            403,
            {"error": {"code": "Authorization_RequestDenied", "message": "Consent required"}},
        )
        with self.assertRaises(AdminApprovalRequired):
            self.connector._graph_get("/me", "token")


if __name__ == "__main__":
    unittest.main()
