from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import Any, Awaitable

from .events import EventBus, RuntimeEvent
from .task_state import JobState, TaskSnapshot


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
