"""Thread-safe runtime state for NOVA Guardian."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from .events import GuardianEvent


@dataclass(frozen=True, slots=True)
class GuardianRuntimeSnapshot:
    """Read-only snapshot of Guardian's current status."""

    running: bool
    vision_active: bool
    vision_paused: bool
    vision_pause_reason: str | None

    active_window_title: str | None
    active_process_name: str | None

    started_at: datetime | None
    vision_session_started_at: datetime | None

    recent_event_count: int
    attention_event_count: int

    def safe_summary(
        self,
        *,
        include_window_details: bool = False,
    ) -> dict[str, Any]:
        """Return state information without exposing window data by default."""

        summary: dict[str, Any] = {
            "running": self.running,
            "vision_active": self.vision_active,
            "vision_paused": self.vision_paused,
            "vision_pause_reason": self.vision_pause_reason,
            "started_at": (
                self.started_at.isoformat()
                if self.started_at
                else None
            ),
            "vision_session_started_at": (
                self.vision_session_started_at.isoformat()
                if self.vision_session_started_at
                else None
            ),
            "active_window_known": bool(
                self.active_window_title
                or self.active_process_name
            ),
            "recent_event_count": self.recent_event_count,
            "attention_event_count": (
                self.attention_event_count
            ),
        }

        if include_window_details:
            summary.update(
                {
                    "active_window_title": (
                        self.active_window_title
                    ),
                    "active_process_name": (
                        self.active_process_name
                    ),
                }
            )

        return summary


class GuardianState:
    """Store Guardian state and a bounded event history."""

    def __init__(
        self,
        *,
        maximum_events: int = 200,
    ) -> None:
        if maximum_events < 1:
            raise ValueError(
                "maximum_events must be at least 1."
            )

        self._lock = RLock()

        self._events: deque[GuardianEvent] = deque(
            maxlen=maximum_events
        )

        self._running = False
        self._vision_active = False
        self._vision_paused = False
        self._vision_pause_reason: str | None = None

        self._active_window_title: str | None = None
        self._active_process_name: str | None = None

        self._started_at: datetime | None = None
        self._vision_session_started_at: (
            datetime | None
        ) = None

    def start(self) -> None:
        """Mark Guardian as running."""

        with self._lock:
            if self._running:
                return

            self._running = True
            self._started_at = datetime.now(
                timezone.utc
            )

    def stop(self) -> None:
        """Stop Guardian and clear temporary runtime flags."""

        with self._lock:
            self._running = False

            self._vision_active = False
            self._vision_paused = False
            self._vision_pause_reason = None
            self._vision_session_started_at = None

    def start_vision(self) -> None:
        """Mark a local vision session as active."""

        with self._lock:
            self._vision_active = True
            self._vision_paused = False
            self._vision_pause_reason = None

            self._vision_session_started_at = (
                datetime.now(timezone.utc)
            )

    def stop_vision(self) -> None:
        """Stop the current local vision session."""

        with self._lock:
            self._vision_active = False
            self._vision_paused = False
            self._vision_pause_reason = None
            self._vision_session_started_at = None

    def pause_vision(
        self,
        reason: str,
    ) -> None:
        """Pause vision without ending the session."""

        with self._lock:
            if not self._vision_active:
                return

            self._vision_paused = True
            self._vision_pause_reason = (
                reason.strip()
                or "Vision was paused."
            )

    def resume_vision(self) -> None:
        """Resume a paused vision session."""

        with self._lock:
            if not self._vision_active:
                return

            self._vision_paused = False
            self._vision_pause_reason = None

    def set_active_window(
        self,
        *,
        title: str | None,
        process_name: str | None,
    ) -> None:
        """Update the locally observed active window."""

        with self._lock:
            self._active_window_title = (
                title.strip()
                if title and title.strip()
                else None
            )

            self._active_process_name = (
                process_name.strip().lower()
                if process_name
                and process_name.strip()
                else None
            )

    def record_event(
        self,
        event: GuardianEvent,
    ) -> None:
        """Add one event to Guardian's bounded history."""

        with self._lock:
            self._events.append(event)

    def recent_events(
        self,
        *,
        limit: int = 20,
        attention_only: bool = False,
    ) -> list[GuardianEvent]:
        """Return recent events, newest first."""

        if limit < 1:
            return []

        with self._lock:
            events = list(reversed(self._events))

        if attention_only:
            events = [
                event
                for event in events
                if event.requires_attention
                and not event.acknowledged
            ]

        return events[:limit]

    def acknowledge_event(
        self,
        event_id: str,
    ) -> bool:
        """Mark one event as acknowledged."""

        cleaned_id = event_id.strip()

        if not cleaned_id:
            return False

        with self._lock:
            updated_events: deque[GuardianEvent] = deque(
                maxlen=self._events.maxlen
            )

            found = False

            for event in self._events:
                if event.event_id == cleaned_id:
                    updated_events.append(
                        replace(
                            event,
                            acknowledged=True,
                        )
                    )
                    found = True
                else:
                    updated_events.append(event)

            self._events = updated_events

        return found

    def clear_events(self) -> None:
        """Clear Guardian's in-memory event history."""

        with self._lock:
            self._events.clear()

    def snapshot(self) -> GuardianRuntimeSnapshot:
        """Create a thread-safe state snapshot."""

        with self._lock:
            attention_count = sum(
                1
                for event in self._events
                if event.requires_attention
                and not event.acknowledged
            )

            return GuardianRuntimeSnapshot(
                running=self._running,
                vision_active=self._vision_active,
                vision_paused=self._vision_paused,
                vision_pause_reason=(
                    self._vision_pause_reason
                ),
                active_window_title=(
                    self._active_window_title
                ),
                active_process_name=(
                    self._active_process_name
                ),
                started_at=self._started_at,
                vision_session_started_at=(
                    self._vision_session_started_at
                ),
                recent_event_count=len(
                    self._events
                ),
                attention_event_count=attention_count,
            )


_guardian_state: GuardianState | None = None
_guardian_state_lock = RLock()


def get_guardian_state() -> GuardianState:
    """Return NOVA's shared Guardian runtime state."""

    global _guardian_state

    with _guardian_state_lock:
        if _guardian_state is None:
            _guardian_state = GuardianState()

        return _guardian_state