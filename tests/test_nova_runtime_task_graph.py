"""Widen the task record toward a real graph without breaking what runs.

`nova_runtime` already has the hard part right: immutable snapshots, a coherent
state machine, an event on every transition, failure captured rather than
raised. What it lacks is any way to express a task's *place* -- no parent, no
children, no dependencies, no retry state, no priority, and no permission
requirements. A durable task graph cannot be built on eight fields.

This step is deliberately additive. `nova_school/automation.py` and
`nova_school/cli.py` are live consumers today and NOVA's class-watch job runs
through them, so every existing call must keep working untouched. New fields
default; new states are new enum members; `start(name, awaitable)` keeps its
exact signature and semantics.

The tests below pin both halves: the new graph vocabulary, and the existing
behavior it must not disturb.
"""

from __future__ import annotations

import asyncio

import pytest

from nova_runtime import NovaRuntime
from nova_runtime.task_state import JobState, TaskSnapshot


# --- the existing contract, which must not move -----------------------------


def test_a_snapshot_still_constructs_from_the_four_original_fields() -> None:
    """jobs.py builds a PENDING snapshot with exactly these. Keep it valid."""
    snapshot = TaskSnapshot(
        job_id="j",
        name="n",
        state=JobState.PENDING,
        created_at=TaskSnapshot.now(),
    )

    assert snapshot.state is JobState.PENDING
    assert snapshot.result is None


@pytest.mark.parametrize(
    "member", ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
)
def test_the_original_states_keep_their_names_and_values(member: str) -> None:
    """Consumers compare by identity (`is JobState.COMPLETED`). Do not rename."""
    assert getattr(JobState, member).value == member.lower()


def test_a_job_still_runs_to_completion_through_the_legacy_signature() -> None:
    async def scenario() -> TaskSnapshot:
        runtime = NovaRuntime()

        async def work() -> str:
            return "done"

        job_id = await runtime.jobs.start("legacy", work())
        snapshot = await runtime.jobs.wait(job_id)
        await runtime.shutdown()
        return snapshot

    snapshot = asyncio.run(scenario())

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.result == "done"


def test_a_failing_job_is_recorded_not_raised() -> None:
    """wait() must return a FAILED snapshot rather than propagate."""

    async def scenario() -> TaskSnapshot:
        runtime = NovaRuntime()

        async def boom() -> None:
            raise ValueError("nope")

        job_id = await runtime.jobs.start("boom", boom())
        snapshot = await runtime.jobs.wait(job_id)
        await runtime.shutdown()
        return snapshot

    snapshot = asyncio.run(scenario())

    assert snapshot.state is JobState.FAILED
    assert "ValueError" in (snapshot.error or "")


# --- the new graph vocabulary ------------------------------------------------


def test_a_task_can_name_its_parent_and_children() -> None:
    parent = TaskSnapshot(
        job_id="p", name="parent", state=JobState.RUNNING, created_at=TaskSnapshot.now()
    )
    child = TaskSnapshot(
        job_id="c",
        name="child",
        state=JobState.PENDING,
        created_at=TaskSnapshot.now(),
        parent_id="p",
    )

    assert parent.parent_id is None
    assert child.parent_id == "p"
    assert parent.children == ()


def test_a_task_can_declare_dependencies() -> None:
    task = TaskSnapshot(
        job_id="c",
        name="compile",
        state=JobState.PENDING,
        created_at=TaskSnapshot.now(),
        depends_on=("research", "design"),
    )

    assert task.depends_on == ("research", "design")


def test_a_fresh_task_declares_no_dependencies() -> None:
    task = TaskSnapshot(
        job_id="j", name="n", state=JobState.PENDING, created_at=TaskSnapshot.now()
    )

    assert task.depends_on == ()
    assert task.children == ()
    assert task.priority == 0
    assert task.attempt == 0
    assert task.owner is None
    assert task.required_permissions == ()


def test_retry_state_is_representable() -> None:
    task = TaskSnapshot(
        job_id="j",
        name="flaky",
        state=JobState.RETRYING,
        created_at=TaskSnapshot.now(),
        attempt=2,
        max_attempts=3,
    )

    assert task.attempt == 2
    assert task.max_attempts == 3


@pytest.mark.parametrize(
    "member", ["BLOCKED", "PAUSED", "RETRYING", "INTERRUPTED", "WAITING_DEPENDENCY"]
)
def test_the_new_lifecycle_states_exist(member: str) -> None:
    assert hasattr(JobState, member)


def test_interrupted_is_distinct_from_failed() -> None:
    """A process killed mid-task did not fail; nobody observed a result.

    This is the same distinction the postprocess status fix rests on: a job
    whose process vanished has not reported anything, and recording that as
    FAILED invents an outcome nobody measured.
    """
    assert JobState.INTERRUPTED is not JobState.FAILED
    assert JobState.INTERRUPTED.value == "interrupted"


def test_a_task_can_carry_the_permissions_it_would_need() -> None:
    """Data only. nova_runtime must never decide permission itself."""
    task = TaskSnapshot(
        job_id="j",
        name="send",
        state=JobState.BLOCKED,
        created_at=TaskSnapshot.now(),
        required_permissions=("email_send",),
    )

    assert task.required_permissions == ("email_send",)


def test_nova_runtime_does_not_import_the_permission_engine() -> None:
    """CAPABILITY != PERMISSION, and the task layer is not the decider.

    If nova_runtime could import nova_policy it could evaluate its own
    authority. The orchestrator above it asks; the trusted engine answers.
    """
    import ast
    from pathlib import Path

    package = Path(__file__).resolve().parents[1] / "nova_runtime"
    offenders: list[str] = []
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(("nova_policy", "nova_os")):
                    offenders.append(f"{path.name} imports {name}")

    assert not offenders, "; ".join(offenders)


def test_a_snapshot_remains_immutable() -> None:
    """Snapshots are frozen so a worker cannot mutate shared task state."""
    task = TaskSnapshot(
        job_id="j", name="n", state=JobState.PENDING, created_at=TaskSnapshot.now()
    )

    with pytest.raises(Exception):
        task.state = JobState.COMPLETED  # type: ignore[misc]
