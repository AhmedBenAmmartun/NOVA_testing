"""LiveKit uses nova_runtime without owning canonical durable task state.

The persistent NOVA Core in nova_startup.py owns the canonical TaskStore and
restart recovery. agent.py still owns its session-local NovaRuntime for jobs,
events, context, and health, and shuts that runtime down with the LiveKit job.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_SOURCE = (ROOT / "agent.py").read_text(encoding="utf-8-sig")


def test_the_agent_imports_the_one_task_runtime() -> None:
    assert "from nova_runtime import" in AGENT_SOURCE or (
        "import nova_runtime" in AGENT_SOURCE
    )


def test_the_agent_does_not_import_the_superseded_core_package() -> None:
    """There must be exactly one task runtime, and it is not `core/`."""
    tree = ast.parse(AGENT_SOURCE)
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            assert name != "core" and not name.startswith("core.")


def test_the_runtime_is_constructed_in_the_session() -> None:
    assert "NovaRuntime()" in AGENT_SOURCE


def test_session_runtime_does_not_own_canonical_durable_state() -> None:
    assert "TaskStore(" not in AGENT_SOURCE
    assert "task_store.recover()" not in AGENT_SOURCE


def test_the_runtime_is_shut_down_with_the_job() -> None:
    """An abandoned job manager would outlive the session that owns it."""
    assert "add_shutdown_callback" in AGENT_SOURCE
    assert "runtime.shutdown" in AGENT_SOURCE or "_shutdown_runtime" in AGENT_SOURCE




@pytest.mark.parametrize(
    "token",
    [
        "nova_agent_bridge",
        "dashboard_bridge_loop",
        "stop_dashboard_bridge",
        "nova_dashboard_bridge",
        "AgentStatusReporter",
        "bridge_status",
    ],
)
def test_the_detached_dashboard_contract_still_holds(token: str) -> None:
    """Regression fence: this wiring must not reintroduce a forbidden token."""
    assert token not in AGENT_SOURCE


@pytest.mark.parametrize(
    "token",
    ["video_input=True", "build_default_capability_manager", "build_default_skill_registry"],
)
def test_the_required_agent_tokens_survive(token: str) -> None:
    assert token in AGENT_SOURCE
