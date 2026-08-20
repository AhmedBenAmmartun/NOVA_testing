from __future__ import annotations

from .context import RuntimeContext
from .events import EventBus
from .health import HealthRegistry, HealthState
from .jobs import BackgroundJobManager


class NovaRuntime:
    def __init__(self, *, max_background_jobs: int = 8) -> None:
        self.events = EventBus()
        self.jobs = BackgroundJobManager(
            self.events,
            max_jobs=max_background_jobs,
        )
        self.context = RuntimeContext()
        self.health = HealthRegistry()
        self.health.set("runtime", HealthState.HEALTHY, "initialized")
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def shutdown(self) -> None:
        if self._closed:
            return
        await self.jobs.shutdown()
        self.health.set("runtime", HealthState.STOPPED, "shutdown")
        self._closed = True
