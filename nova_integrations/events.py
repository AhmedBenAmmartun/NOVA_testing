"""Safe local event stream for future dashboard wiring."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .models import IntegrationEvent


class EventWriter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def emit(self, event: IntegrationEvent) -> None:
        line = json.dumps(event.safe_dict(), ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
