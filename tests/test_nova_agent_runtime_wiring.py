"""The task runtime must actually be part of the running NOVA.

`nova_runtime` has been on disk with a working job manager, an event bus, and a
coherent state machine -- consumed only by `nova_school/automation.py` and the
school CLI. `agent.py` never imported it, so the agent NOVA that Ahmed actually
talks to had no task layer at all. Durable background work, restart recovery,
and eventually the orchestrator all need it wired into the live agent.

These are contract tests over the source, matching the existing convention in
`tests/test_dashboard_detached_contract.py`: constructing a real LiveKit agent
session needs a room, credentials, and a live Gemini connection, none of which
belong in a unit test. What can be proven here is that the wiring exists, that
it recovers durable state at startup, that it shuts down cleanly, and that it
does not disturb the tokens the detached-dashboard contract pins.
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


def test_durable_task_state_is_recovered_at_startup() -> None:
    """A restart must not silently forget work that was in flight.

    Recovery is also what reinterprets a task left RUNNING by a process that
    died -- without this call, that record stays RUNNING forever.
    """
    assert "recover()" in AGENT_SOURCE


def test_the_runtime_is_shut_down_with_the_job() -> None:
    """An abandoned job manager would outlive the session that owns it."""
    assert "add_shutdown_callback" in AGENT_SOURCE
    assert "runtime.shutdown" in AGENT_SOURCE or "_shutdown_runtime" in AGENT_SOURCE


def test_recovery_failure_cannot_stop_nova_from_starting() -> None:
    """Task state is valuable; being able to talk to NOVA is more valuable.

    A corrupt or unreadable task store must degrade to "no recovered tasks",
    never to an agent that will not start.
    """
    start = AGENT_SOURCE.index("NovaRuntime()")
    window = AGENT_SOURCE[max(0, start - 800) : start + 1200]

    assert "try:" in window and "except" in window


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
