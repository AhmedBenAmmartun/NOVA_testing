from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from .models import TranscriptSegment
from .storage import ClassCaptureStorage


def _elapsed(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:04.1f}"
    return f"{minutes:02d}:{secs:04.1f}"


class TranscriptJournal:
    """Authoritative JSONL transcript plus a derived human-readable text view."""

    def __init__(
        self,
        path: Path,
        *,
        recent_limit: int = 200,
        readable_path: Path | None = None,
    ) -> None:
        self.path = path
        self.readable_path = readable_path or path.with_name("transcript.txt")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self.readable_path.touch(exist_ok=True)
        self._recent: deque[TranscriptSegment] = deque(
            maxlen=max(1, int(recent_limit))
        )

    def append(self, segment: TranscriptSegment) -> None:
        ClassCaptureStorage.append_jsonl(self.path, segment.as_dict())
        label = segment.speaker_id or segment.speaker.value
        with self.readable_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"[{_elapsed(segment.start_seconds)}] "
                f"[speaker={label}] {segment.text.strip()}\n"
            )
        self._recent.append(segment)

    def recent(self, limit: int = 20) -> tuple[TranscriptSegment, ...]:
        count = max(0, int(limit))
        if count == 0:
            return ()
        return tuple(list(self._recent)[-count:])

    def rebuild_readable(self, role_map: dict[str, dict[str, object]]) -> None:
        lines: list[str] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            speaker_id = item.get("speaker_id")
            role = role_map.get(str(speaker_id), {}) if speaker_id is not None else {}
            label = role.get("label") or (f"Speaker {speaker_id}" if speaker_id is not None else "Unknown")
            lines.append(
                f"[{_elapsed(item.get('start_seconds', 0.0))}] "
                f"[{label}] {str(item.get('text', '')).strip()}"
            )
        temporary = self.readable_path.with_suffix(".txt.tmp")
        temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        temporary.replace(self.readable_path)
