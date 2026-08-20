from __future__ import annotations

from pathlib import Path

from .models import MarkerKind, MarkerRecord
from .storage import ClassCaptureStorage


class MarkerJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: list[MarkerRecord] = []

    def add(
        self,
        timestamp_seconds: float,
        kind: MarkerKind,
        label: str,
        *,
        topic: str | None = None,
    ) -> MarkerRecord:
        item = MarkerRecord(
            timestamp_seconds=max(0.0, float(timestamp_seconds)),
            kind=kind,
            label=label.strip(),
            topic=topic,
        )
        self._items.append(item)
        ClassCaptureStorage.append_jsonl(self.path, item.as_dict())
        return item

    def items(self) -> tuple[MarkerRecord, ...]:
        return tuple(self._items)
