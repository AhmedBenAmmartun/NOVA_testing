from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(slots=True)
class ComponentHealth:
    name: str
    state: HealthState = HealthState.HEALTHY
    detail: str = ""
    updated_at: datetime = datetime.now(timezone.utc)

    def update(self, state: HealthState, detail: str = "") -> None:
        self.state = state
        self.detail = detail
        self.updated_at = datetime.now(timezone.utc)


class HealthRegistry:
    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {}

    def set(self, name: str, state: HealthState, detail: str = "") -> None:
        component = self._components.setdefault(name, ComponentHealth(name=name))
        component.update(state, detail)

    def get(self, name: str) -> ComponentHealth | None:
        return self._components.get(name)

    def snapshot(self) -> dict[str, ComponentHealth]:
        return dict(self._components)
