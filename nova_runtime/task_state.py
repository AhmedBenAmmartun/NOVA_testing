from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    # The original five. Consumers compare by identity
    # (`snapshot.state is JobState.COMPLETED`), so these names and values are
    # a compatibility contract -- never rename or re-value them.
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Added for the task graph. New members are additive and cannot affect the
    # identity checks above.
    #: Waiting on another task in the graph to finish.
    WAITING_DEPENDENCY = "waiting_dependency"
    #: Cannot proceed for a reason outside the graph -- a missing credential, a
    #: provider outage. Distinct from FAILED: nothing was attempted and failed.
    BLOCKED = "blocked"
    PAUSED = "paused"
    RETRYING = "retrying"
    #: The process running this task disappeared without reporting an outcome.
    #: Deliberately NOT the same as FAILED. A killed job did not fail -- nobody
    #: observed a result, and recording one invents an outcome that was never
    #: measured. This is the same distinction that made a dead post-class job
    #: readable as "interrupted" rather than a confident, false "running".
    INTERRUPTED = "interrupted"


#: States from which a task will never move again on its own.
TERMINAL_STATES = frozenset(
    {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}
)


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """One task's observable state, immutable by design.

    Frozen so that a worker holding a snapshot can never mutate shared task
    state; transitions go through `dataclasses.replace` in the manager, which
    keeps every change a single atomic slot write.

    Everything below `result` is additive graph vocabulary with a default, so
    the four-field construction in `jobs.py` and every existing `replace()`
    call stay valid.
    """

    job_id: str
    name: str
    state: JobState
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: Any = None

    # --- task graph ---------------------------------------------------------
    parent_id: str | None = None
    children: tuple[str, ...] = ()
    #: Job ids that must reach COMPLETED before this one may be dispatched.
    depends_on: tuple[str, ...] = ()
    #: Higher runs first when several tasks are ready and the slot cap binds.
    priority: int = 0
    #: Free-form 0.0-1.0 or None when a task cannot report progress.
    progress: float | None = None
    #: Which worker holds this task. None means the orchestrator itself.
    owner: str | None = None

    # --- retry --------------------------------------------------------------
    attempt: int = 0
    max_attempts: int = 1

    # --- results and authority ----------------------------------------------
    #: A durable pointer to a large result, when `result` itself is too big to
    #: hold in memory or must survive a restart.
    result_ref: str | None = None
    #: Permissions this task WOULD need, recorded as data. nova_runtime never
    #: evaluates them -- it must not be able to decide its own authority. The
    #: orchestrator asks the trusted permission engine before dispatch.
    required_permissions: tuple[str, ...] = ()
    updated_at: datetime | None = None

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)
