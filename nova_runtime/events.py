from __future__ import annotations

import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

EventHandler = Callable[["RuntimeEvent"], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, kind: str, handler: EventHandler) -> Callable[[], None]:
        self._handlers[kind].append(handler)

        def unsubscribe() -> None:
            handlers = self._handlers.get(kind, [])
            if handler in handlers:
                handlers.remove(handler)

        return unsubscribe

    async def publish(self, event: RuntimeEvent) -> None:
        handlers = [
            *self._handlers.get(event.kind, []),
            *self._handlers.get("*", []),
        ]
        for handler in tuple(handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
