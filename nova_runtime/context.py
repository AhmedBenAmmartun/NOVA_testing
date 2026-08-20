from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeContext:
    current_project: str | None = None
    active_job_id: str | None = None
    current_recording_id: str | None = None
    current_note_session_id: str | None = None
    recent_intent: str | None = None
    ephemeral: dict[str, Any] = field(default_factory=dict)

    def clear_ephemeral(self) -> None:
        self.ephemeral.clear()
        self.recent_intent = None
