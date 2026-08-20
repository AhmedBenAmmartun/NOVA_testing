from __future__ import annotations

from pathlib import Path

from .models import TopicSegment
from .storage import ClassCaptureStorage


class TopicTracker:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._segments: list[TopicSegment] = []

    @property
    def current(self) -> TopicSegment | None:
        return self._segments[-1] if self._segments else None

    def update(
        self,
        timestamp_seconds: float,
        topic: str,
        *,
        subtopic: str | None = None,
        summary: str = "",
    ) -> TopicSegment:
        segment = TopicSegment(
            start_seconds=max(0.0, float(timestamp_seconds)),
            topic=topic.strip(),
            subtopic=subtopic.strip() if subtopic else None,
            summary=summary.strip(),
        )
        self._segments.append(segment)
        ClassCaptureStorage.append_jsonl(self.path, segment.as_dict())
        return segment

    def items(self) -> tuple[TopicSegment, ...]:
        return tuple(self._segments)
