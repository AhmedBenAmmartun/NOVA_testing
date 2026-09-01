"""Task state must survive a restart, and must never lie about what happened.

`nova_runtime` holds every task in two plain dicts. Nothing is written to disk,
so a NOVA restart loses all knowledge of work in flight. A personal agent that
forgets every job the moment it restarts cannot be trusted with long work.

The second requirement is the one this repository keeps re-learning: a process
that is killed never writes its own ending. Post-class processing died and left
`{"status": "running"}` for eight hours; a live session left
`audio_integrity_ok: false` meaning "nobody checked". So the store records the
process identity alongside the task, and recovery reinterprets rather than
trusts -- a task left RUNNING by a process that no longer exists becomes
INTERRUPTED, which is explicitly *not* FAILED. Nothing observed a failure.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psutil
import pytest

from nova_runtime.store import TaskStore, runtime_root
from nova_runtime.task_state import JobState, TaskSnapshot


def _snapshot(job_id: str = "j", state: JobState = JobState.RUNNING) -> TaskSnapshot:
    return TaskSnapshot(
        job_id=job_id,
        name="lecture-notes",
        state=state,
        created_at=TaskSnapshot.now(),
    )


# --- the root ----------------------------------------------------------------


def test_the_runtime_root_matches_the_school_path_authority() -> None:
    """Two resolvers, one path -- verified, not assumed.

    `nova_school/paths.py` declares itself the authority for runtime paths, but
    importing it from `nova_runtime` costs ~372ms (its package __init__ pulls
    all of course intelligence) and inverts layering: infrastructure would
    depend on a domain package. So `nova_runtime` resolves the root itself
    using the same environment contract.

    That is exactly the "split-brain" `paths.py` warns about, so this test
    holds the two implementations together mechanically. If either drifts, this
    fails rather than silently writing task state somewhere new.
    """
    from nova_school.paths import runtime_root as school_runtime_root

    assert runtime_root() == school_runtime_root()


def test_the_runtime_root_honors_the_documented_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_RUNTIME_ROOT", str(tmp_path))

    assert runtime_root() == tmp_path.resolve()


def test_task_state_lives_outside_the_git_repository(monkeypatch) -> None:
    monkeypatch.delenv("NOVA_RUNTIME_ROOT", raising=False)
    project = Path(__file__).resolve().parents[1]

    assert project not in runtime_root().parents
    assert runtime_root() != project


# --- persistence -------------------------------------------------------------


def test_a_task_survives_being_written_and_read_back(tmp_path) -> None:
    store = TaskStore(tmp_path)
    store.record(_snapshot("abc", JobState.RUNNING))

    loaded = TaskStore(tmp_path).load()

    assert "abc" in loaded
    assert loaded["abc"].name == "lecture-notes"


def test_the_latest_state_of_a_task_wins(tmp_path) -> None:
    """The log is append-only; reading it replays to the newest state."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("abc", JobState.PENDING))
    store.record(_snapshot("abc", JobState.RUNNING))
    store.record(_snapshot("abc", JobState.COMPLETED))

    assert TaskStore(tmp_path).load()["abc"].state is JobState.COMPLETED


def test_history_is_never_rewritten(tmp_path) -> None:
    """Append-only: an incident reviewer must see every transition."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("abc", JobState.PENDING))
    store.record(_snapshot("abc", JobState.COMPLETED))

    lines = [
        json.loads(line)
        for line in store.log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [entry["state"] for entry in lines] == ["pending", "completed"]


def test_the_graph_fields_round_trip(tmp_path) -> None:
    store = TaskStore(tmp_path)
    store.record(
        TaskSnapshot(
            job_id="child",
            name="compile",
            state=JobState.WAITING_DEPENDENCY,
            created_at=TaskSnapshot.now(),
            parent_id="root",
            depends_on=("research", "design"),
            priority=5,
            attempt=1,
            max_attempts=3,
            required_permissions=("files_write_approved",),
        )
    )

    task = TaskStore(tmp_path).load()["child"]

    assert task.parent_id == "root"
    assert task.depends_on == ("research", "design")
    assert task.priority == 5
    assert task.max_attempts == 3
    assert task.required_permissions == ("files_write_approved",)
    assert task.state is JobState.WAITING_DEPENDENCY


def test_a_corrupt_line_does_not_destroy_the_rest_of_the_log(tmp_path) -> None:
    """One bad write must not cost every other task's state."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("good", JobState.COMPLETED))
    with store.log_path.open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")
    store.record(_snapshot("also-good", JobState.RUNNING))

    loaded = TaskStore(tmp_path).load()

    assert set(loaded) == {"good", "also-good"}


def test_an_absent_store_loads_empty(tmp_path) -> None:
    assert TaskStore(tmp_path / "never-written").load() == {}


# --- recovery ----------------------------------------------------------------


def test_a_task_left_running_by_a_dead_process_becomes_interrupted(tmp_path) -> None:
    """The recurring bug in this repo, now handled at the task layer."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("orphan", JobState.RUNNING), pid=999_999, pid_created_at=1.0)

    recovered = TaskStore(tmp_path).recover()

    assert recovered["orphan"].state is JobState.INTERRUPTED
    assert recovered["orphan"].error


def test_interrupted_is_not_reported_as_failed(tmp_path) -> None:
    """Nothing observed a failure. Recording one would invent an outcome."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("orphan", JobState.RUNNING), pid=999_999, pid_created_at=1.0)

    assert TaskStore(tmp_path).recover()["orphan"].state is not JobState.FAILED


def test_a_task_owned_by_a_live_process_is_left_alone(tmp_path) -> None:
    store = TaskStore(tmp_path)
    process = psutil.Process(os.getpid())
    store.record(
        _snapshot("mine", JobState.RUNNING),
        pid=process.pid,
        pid_created_at=process.create_time(),
    )

    assert TaskStore(tmp_path).recover()["mine"].state is JobState.RUNNING


def test_a_recycled_pid_does_not_keep_a_dead_task_alive(tmp_path) -> None:
    store = TaskStore(tmp_path)
    store.record(
        _snapshot("recycled", JobState.RUNNING),
        pid=os.getpid(),
        pid_created_at=1.0,
    )

    assert TaskStore(tmp_path).recover()["recycled"].state is JobState.INTERRUPTED


@pytest.mark.parametrize(
    "terminal",
    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED],
)
def test_a_finished_task_is_never_reinterpreted(tmp_path, terminal) -> None:
    """Only RUNNING is ambiguous. A reported ending is a fact."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("done", terminal), pid=999_999, pid_created_at=1.0)

    assert TaskStore(tmp_path).recover()["done"].state is terminal


def test_recovery_persists_what_it_concluded(tmp_path) -> None:
    """A second restart must not have to re-derive the same conclusion."""
    store = TaskStore(tmp_path)
    store.record(_snapshot("orphan", JobState.RUNNING), pid=999_999, pid_created_at=1.0)
    TaskStore(tmp_path).recover()

    assert TaskStore(tmp_path).load()["orphan"].state is JobState.INTERRUPTED


def test_the_store_does_not_import_the_permission_engine() -> None:
    """Durable task state must not be able to decide its own authority."""
    import ast

    source = (Path(__file__).resolve().parents[1] / "nova_runtime" / "store.py").read_text(
        encoding="utf-8"
    )
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            assert not name.startswith(("nova_policy", "nova_os", "nova_school"))
