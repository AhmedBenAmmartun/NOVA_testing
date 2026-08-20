from __future__ import annotations

from collections import deque
from pathlib import Path

from .models import TranscriptSegment
from .storage import ClassCaptureStorage


class TranscriptJournal:
    def __init__(
        self,
        path: Path,
        *,
        recent_limit: int = 200,
    ) -> None:
        self.path = path
        self._recent: deque[TranscriptSegment] = deque(
            maxlen=max(1, int(recent_limit))
        )

    def append(self, segment: TranscriptSegment) -> None:
        ClassCaptureStorage.append_jsonl(self.path, segment.as_dict())
        self._recent.append(segment)

    def recent(self, limit: int = 20) -> tuple[TranscriptSegment, ...]:
        count = max(0, int(limit))
        if count == 0:
            return ()
        return tuple(list(self._recent)[-count:])
