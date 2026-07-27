from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from unittest.mock import patch

import pytest

from nova_bridge import BridgeValidationError, CommandStore


def test_agent_status_heartbeat_round_trip(tmp_path: Path) -> None:
    store = CommandStore(tmp_path / "bridge")
    with patch("nova_bridge.time.time", return_value=100.0):
        store.heartbeat(
            "job_status_test",
            phase="starting",
            route="Gemini Flash",
            model="gemini-test",
        )
    with patch("nova_bridge.time.time", return_value=102.0):
        status = store.agent_status()
    assert status["active"] is True
    assert status["phase"] == "starting"
    assert status["route"] == "Gemini Flash"
    assert status["model"] == "gemini-test"
    assert status["heartbeat_age"] == 2.0


def test_agent_status_becomes_offline_after_timeout(tmp_path: Path) -> None:
    store = CommandStore(tmp_path / "bridge")
    with patch("nova_bridge.time.time", return_value=100.0):
        store.heartbeat("job_timeout_test", phase="idle")
    # Threshold widened to 15s (2026-07-27) so a long NOVA response doesn't
    # flicker the dashboard to "offline" mid-conversation; 16s exceeds it.
    with patch("nova_bridge.time.time", return_value=116.0):
        status = store.agent_status()
    assert status["active"] is False
    assert status["phase"] == "offline"
    assert status["session_id"] is None


def test_agent_status_rejects_unknown_phase(tmp_path: Path) -> None:
    store = CommandStore(tmp_path / "bridge")
    with pytest.raises(BridgeValidationError):
        store.heartbeat("job_invalid_phase", phase="pretending")


def test_phase_transition_updates_timestamp(tmp_path: Path) -> None:
    store = CommandStore(tmp_path / "bridge")
    with patch("nova_bridge.time.time", return_value=100.0):
        store.heartbeat("job_transition", phase="idle")
    with patch("nova_bridge.time.time", return_value=101.0):
        store.update_agent_status("job_transition", "listening")
    with patch("nova_bridge.time.time", return_value=102.0):
        status = store.agent_status()
    assert status["phase"] == "listening"
    assert status["last_transition_at"] == 101.0
