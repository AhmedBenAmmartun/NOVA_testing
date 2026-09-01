from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable

from .events import EventBus, RuntimeEvent
from .task_state import TERMINAL_STATES, JobState, TaskSnapshot


@dataclass(frozen=True, slots=True)
class JobSpec:
    """One unit of work, plus where it sits in the graph.

    Carries a ``factory`` rather than a coroutine. That distinction is what
    makes deferral and retry expressible at all: a coroutine can only be
    awaited once, so a job that must wait for a dependency -- or run again
    after a failure -- cannot be represented by one. ``start()`` keeps taking a
    bare awaitable for its existing callers.

    ``required_permissions`` is recorded as DATA and never evaluated here. The
    task layer must not be able to decide its own authority; the orchestrator
    asks the trusted permission engine before dispatch.
    """

    name: str
    factory: Callable[[], Awaitable[Any]]
    depends_on: tuple[str, ...] = ()
    parent_id: str | None = None
    priority: int = 0
    owner: str | None = None
    required_permissions: tuple[str, ...] = field(default_factory=tuple)
    max_attempts: int = 1


class BackgroundJobManager:
    def __init__(
        self,
        event_bus: EventBus | None = None,
        *,
        max_jobs: int = 8,
    ) -> None:
        self._event_bus = event_bus or EventBus()
        self._max_jobs = max(1, int(max_jobs))
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._snapshots: dict[str, TaskSnapshot] = {}

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def snapshot(self, job_id: str) -> TaskSnapshot | None:
        return self._snapshots.get(job_id)

    def snapshots(self) -> tuple[TaskSnapshot, ...]:
        return tuple(self._snapshots.values())

    def active_count(self) -> int:
        return sum(not task.done() for task in self._tasks.values())

    async def start(self, name: str, awaitable: Awaitable[Any]) -> str:
        if self.active_count() >= self._max_jobs:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise RuntimeError("NOVA background job limit reached.")

        job_id = uuid.uuid4().hex
        created = TaskSnapshot(
            job_id=job_id,
            name=name,
            state=JobState.PENDING,
            created_at=TaskSnapshot.now(),
        )
        self._snapshots[job_id] = created

        async def runner() -> Any:
            self._snapshots[job_id] = replace(
                self._snapshots[job_id],
                state=JobState.RUNNING,
                started_at=TaskSnapshot.now(),
            )
            await self._event_bus.publish(
                RuntimeEvent(
                    "job.started",
                    {"job_id": job_id, "name": name},
                )
            )
            try:
                result = await awaitable
            except asyncio.CancelledError:
                self._snapshots[job_id] = replace(
                    self._snapshots[job_id],
                    state=JobState.CANCELLED,
                    finished_at=TaskSnapshot.now(),
                )
                await self._event_bus.publish(
                    RuntimeEvent(
                        "job.cancelled",
                        {"job_id": job_id, "name": name},
                    )
                )
                raise
            except Exception as error:
                self._snapshots[job_id] = replace(
                    self._snapshots[job_id],
                    state=JobState.FAILED,
                    finished_at=TaskSnapshot.now(),
                    error=f"{type(error).__name__}: {error}",
                )
                await self._event_bus.publish(
                    RuntimeEvent(
                        "job.failed",
                        {
                            "job_id": job_id,
                            "name": name,
                            "error": type(error).__name__,
                        },
                    )
                )
                return None
            else:
                self._snapshots[job_id] = replace(
                    self._snapshots[job_id],
                    state=JobState.COMPLETED,
                    finished_at=TaskSnapshot.now(),
                    result=result,
                )
                await self._event_bus.publish(
                    RuntimeEvent(
                        "job.completed",
                        {"job_id": job_id, "name": name},
                    )
                )
                return result

        task = asyncio.create_task(runner(), name=f"nova:{name}:{job_id[:8]}")
        self._tasks[job_id] = task

        # Give runner() one event-loop turn before start() returns.
        # This guarantees that runner() takes ownership of the supplied
        # awaitable and transitions the snapshot out of PENDING before an
        # immediate cancel() can occur.
        await asyncio.sleep(0)

        return job_id

    async def submit(self, spec: JobSpec) -> str:
        """Accept a job into the graph; dispatch it when its way is clear.

        Unlike ``start()``, this returns as soon as the job is *accepted*. A job
        with unmet dependencies sits in ``WAITING_DEPENDENCY`` until they
        complete, and ``wait()`` works either way, so a caller never has to know
        whether the work was deferred.
        """
        job_id = uuid.uuid4().hex
        waiting = bool(spec.depends_on)
        self._snapshots[job_id] = TaskSnapshot(
            job_id=job_id,
            name=spec.name,
            state=(
                JobState.WAITING_DEPENDENCY if waiting else JobState.PENDING
            ),
            created_at=TaskSnapshot.now(),
            parent_id=spec.parent_id,
            depends_on=tuple(spec.depends_on),
            priority=spec.priority,
            owner=spec.owner,
            max_attempts=spec.max_attempts,
            required_permissions=tuple(spec.required_permissions),
        )

        async def gated() -> Any:
            if spec.depends_on and not await self._await_dependencies(
                job_id, spec.depends_on
            ):
                return None
            return await self._run_job(job_id, spec.name, spec.factory())

        task = asyncio.create_task(
            gated(), name=f"nova:{spec.name}:{job_id[:8]}"
        )
        self._tasks[job_id] = task
        await asyncio.sleep(0)
        return job_id

    async def _await_dependencies(
        self, job_id: str, depends_on: tuple[str, ...]
    ) -> bool:
        """Wait for every dependency. False means this job must not run.

        A dependency that failed, was cancelled, or does not exist blocks the
        dependent rather than letting it run on a broken prerequisite. An
        unknown id is treated the same way deliberately: a typo in a graph must
        fail loudly instead of wedging the runtime on something that will never
        arrive.
        """
        for dependency in depends_on:
            task = self._tasks.get(dependency)
            if task is None:
                return self._block(job_id, f"Unknown dependency '{dependency}'.")
            try:
                await task
            except asyncio.CancelledError:
                pass
            state = self._snapshots.get(dependency)
            if state is None or state.state is not JobState.COMPLETED:
                observed = state.state if state else "missing"
                return self._block(
                    job_id, f"Dependency '{dependency}' ended as {observed}."
                )
        return True

    def _block(self, job_id: str, reason: str) -> bool:
        self._snapshots[job_id] = replace(
            self._snapshots[job_id],
            state=JobState.BLOCKED,
            finished_at=TaskSnapshot.now(),
            error=reason,
        )
        return False

    async def _run_job(
        self, job_id: str, name: str, awaitable: Awaitable[Any]
    ) -> Any:
        """The shared lifecycle: RUNNING -> COMPLETED / FAILED / CANCELLED."""
        self._snapshots[job_id] = replace(
            self._snapshots[job_id],
            state=JobState.RUNNING,
            started_at=TaskSnapshot.now(),
        )
        await self._event_bus.publish(
            RuntimeEvent("job.started", {"job_id": job_id, "name": name})
        )
        try:
            result = await awaitable
        except asyncio.CancelledError:
            self._snapshots[job_id] = replace(
                self._snapshots[job_id],
                state=JobState.CANCELLED,
                finished_at=TaskSnapshot.now(),
            )
            await self._event_bus.publish(
                RuntimeEvent("job.cancelled", {"job_id": job_id, "name": name})
            )
            raise
        except Exception as error:
            self._snapshots[job_id] = replace(
                self._snapshots[job_id],
                state=JobState.FAILED,
                finished_at=TaskSnapshot.now(),
                error=f"{type(error).__name__}: {error}",
            )
            await self._event_bus.publish(
                RuntimeEvent(
                    "job.failed",
                    {
                        "job_id": job_id,
                        "name": name,
                        "error": type(error).__name__,
                    },
                )
            )
            return None
        else:
            self._snapshots[job_id] = replace(
                self._snapshots[job_id],
                state=JobState.COMPLETED,
                finished_at=TaskSnapshot.now(),
                result=result,
            )
            await self._event_bus.publish(
                RuntimeEvent("job.completed", {"job_id": job_id, "name": name})
            )
            return result

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(job_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    async def wait(self, job_id: str) -> TaskSnapshot:
        task = self._tasks.get(job_id)
        if task is None:
            raise KeyError(job_id)
        try:
            await task
        except asyncio.CancelledError:
            pass
        snapshot = self._snapshots[job_id]
        return snapshot

    async def shutdown(self) -> None:
        active = [
            job_id
            for job_id, task in self._tasks.items()
            if not task.done()
        ]
        for job_id in active:
            await self.cancel(job_id)
