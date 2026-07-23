"""Local active-window monitoring for NOVA Guardian on Windows."""

from __future__ import annotations

import asyncio
import ctypes
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psutil

from .config import (
    GuardianConfiguration,
    load_guardian_configuration,
)
from .events import (
    GuardianEventCategory,
    GuardianEventSeverity,
    GuardianEventType,
    create_guardian_event,
)
from .state import (
    GuardianState,
    get_guardian_state,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActiveWindowSnapshot:
    """Information about the currently focused Windows application."""

    window_handle: int
    process_id: int | None
    process_name: str | None
    window_title: str | None
    sensitive: bool
    captured_at: datetime

    def safe_summary(
        self,
        *,
        include_title: bool = False,
    ) -> dict[str, Any]:
        """Return active-window information safely."""

        summary: dict[str, Any] = {
            "window_handle": self.window_handle,
            "process_id": self.process_id,
            "process_name": self.process_name,
            "window_title_known": bool(
                self.window_title
            ),
            "sensitive": self.sensitive,
            "captured_at": self.captured_at.isoformat(),
        }

        if include_title:
            summary["window_title"] = (
                "[REDACTED]"
                if self.sensitive
                else self.window_title
            )

        return summary


class ActiveWindowMonitor:
    """Observe the current Windows foreground application."""

    def __init__(
        self,
        *,
        configuration: GuardianConfiguration | None = None,
        state: GuardianState | None = None,
    ) -> None:
        self.configuration = (
            configuration
            if configuration is not None
            else load_guardian_configuration()
        )

        self.state = (
            state
            if state is not None
            else get_guardian_state()
        )

        self._last_snapshot: (
            ActiveWindowSnapshot | None
        ) = None

        self._vision_paused_by_monitor = False

    @staticmethod
    def _window_title(
        window_handle: int,
    ) -> str | None:
        """Read the foreground window title."""

        user32 = ctypes.windll.user32

        title_length = user32.GetWindowTextLengthW(
            window_handle
        )

        if title_length <= 0:
            return None

        buffer = ctypes.create_unicode_buffer(
            title_length + 1
        )

        user32.GetWindowTextW(
            window_handle,
            buffer,
            title_length + 1,
        )

        title = buffer.value.strip()

        return title or None

    @staticmethod
    def _process_id(
        window_handle: int,
    ) -> int | None:
        """Read the process ID associated with a window."""

        process_id = ctypes.c_ulong()

        ctypes.windll.user32.GetWindowThreadProcessId(
            window_handle,
            ctypes.byref(process_id),
        )

        return process_id.value or None

    @staticmethod
    def _process_name(
        process_id: int | None,
    ) -> str | None:
        """Read the executable name for a process ID."""

        if process_id is None:
            return None

        try:
            return psutil.Process(
                process_id
            ).name().strip().lower()

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            return None

    def _is_sensitive(
        self,
        *,
        process_name: str | None,
        window_title: str | None,
    ) -> bool:
        """Check whether vision should pause for this window."""

        process_sensitive = (
            bool(process_name)
            and self.configuration.process_is_excluded(
                process_name or ""
            )
        )

        title_sensitive = (
            bool(window_title)
            and self.configuration.title_is_sensitive(
                window_title or ""
            )
        )

        return process_sensitive or title_sensitive

    def _capture_snapshot(
        self,
    ) -> ActiveWindowSnapshot | None:
        """Capture the current Windows foreground window."""

        window_handle = (
            ctypes.windll.user32.GetForegroundWindow()
        )

        if not window_handle:
            return None

        process_id = self._process_id(
            window_handle
        )

        process_name = self._process_name(
            process_id
        )

        window_title = self._window_title(
            window_handle
        )

        sensitive = self._is_sensitive(
            process_name=process_name,
            window_title=window_title,
        )

        return ActiveWindowSnapshot(
            window_handle=window_handle,
            process_id=process_id,
            process_name=process_name,
            window_title=window_title,
            sensitive=sensitive,
            captured_at=datetime.now(
                timezone.utc
            ),
        )

    def _window_changed(
        self,
        snapshot: ActiveWindowSnapshot,
    ) -> bool:
        """Return whether the active window changed."""

        previous = self._last_snapshot

        if previous is None:
            return True

        return (
            snapshot.window_handle
            != previous.window_handle
            or snapshot.process_id
            != previous.process_id
            or snapshot.process_name
            != previous.process_name
            or snapshot.window_title
            != previous.window_title
            or snapshot.sensitive
            != previous.sensitive
        )

    def _record_window_change(
        self,
        snapshot: ActiveWindowSnapshot,
    ) -> None:
        """Record a safe active-window event."""

        event = create_guardian_event(
            event_type=(
                GuardianEventType.ACTIVE_WINDOW_CHANGED
            ),
            category=GuardianEventCategory.WINDOW,
            severity=GuardianEventSeverity.INFO,
            title="Active window changed",
            message=(
                "The foreground application changed."
            ),
            source="window_monitor",
            metadata={
                "process_id": snapshot.process_id,
                "process_name": snapshot.process_name,
                "sensitive": snapshot.sensitive,
                "window_title": (
                    "[REDACTED]"
                    if snapshot.sensitive
                    else snapshot.window_title
                ),
            },
            requires_attention=False,
        )

        self.state.record_event(event)

    def _pause_for_sensitive_window(
        self,
        snapshot: ActiveWindowSnapshot,
    ) -> None:
        """Pause vision when sensitive content is detected."""

        runtime = self.state.snapshot()

        if not runtime.vision_active:
            return

        if runtime.vision_paused:
            return

        self.state.pause_vision(
            "Sensitive or excluded window detected."
        )

        self._vision_paused_by_monitor = True

        sensitive_event = create_guardian_event(
            event_type=(
                GuardianEventType
                .SENSITIVE_WINDOW_DETECTED
            ),
            category=GuardianEventCategory.WINDOW,
            severity=GuardianEventSeverity.MEDIUM,
            title="Sensitive window detected",
            message=(
                "NOVA detected a sensitive or excluded "
                "window and paused local vision."
            ),
            source="window_monitor",
            metadata={
                "process_name": snapshot.process_name,
                "window_title": "[REDACTED]",
            },
            requires_attention=False,
        )

        pause_event = create_guardian_event(
            event_type=(
                GuardianEventType.VISION_PAUSED
            ),
            category=GuardianEventCategory.VISION,
            severity=GuardianEventSeverity.LOW,
            title="Vision paused",
            message=(
                "Local vision was paused to protect "
                "sensitive information."
            ),
            source="window_monitor",
            metadata={
                "reason": "sensitive_window",
            },
            requires_attention=False,
        )

        self.state.record_event(
            sensitive_event
        )

        self.state.record_event(
            pause_event
        )

    def _resume_after_sensitive_window(
        self,
    ) -> None:
        """Resume vision after leaving a sensitive window."""

        if not self._vision_paused_by_monitor:
            return

        runtime = self.state.snapshot()

        if not runtime.vision_active:
            self._vision_paused_by_monitor = False
            return

        self.state.resume_vision()

        self._vision_paused_by_monitor = False

        event = create_guardian_event(
            event_type=(
                GuardianEventType.VISION_RESUMED
            ),
            category=GuardianEventCategory.VISION,
            severity=GuardianEventSeverity.INFO,
            title="Vision resumed",
            message=(
                "Local vision resumed after the "
                "sensitive window was closed or changed."
            ),
            source="window_monitor",
            requires_attention=False,
        )

        self.state.record_event(event)

    def poll_once(
        self,
    ) -> ActiveWindowSnapshot | None:
        """Perform one active-window check."""

        if not self.configuration.enabled:
            return None

        if not (
            self.configuration
            .active_window_monitor_enabled
        ):
            return None

        try:
            snapshot = self._capture_snapshot()

        except Exception:
            logger.exception(
                "Guardian could not inspect "
                "the active window."
            )
            return None

        if snapshot is None:
            return None

        self.state.set_active_window(
            title=snapshot.window_title,
            process_name=snapshot.process_name,
        )

        if self._window_changed(snapshot):
            self._record_window_change(
                snapshot
            )

        if snapshot.sensitive:
            self._pause_for_sensitive_window(
                snapshot
            )
        else:
            self._resume_after_sensitive_window()

        self._last_snapshot = snapshot

        return snapshot

    async def run(
        self,
        stop_event: asyncio.Event,
        *,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        """Monitor active windows until stopped."""

        interval = max(
            0.25,
            poll_interval_seconds,
        )

        logger.info(
            "NOVA active-window monitor started."
        )

        while not stop_event.is_set():
            self.poll_once()

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=interval,
                )

            except TimeoutError:
                continue

        logger.info(
            "NOVA active-window monitor stopped."
        )

    def last_snapshot(
        self,
    ) -> ActiveWindowSnapshot | None:
        """Return the latest active-window observation."""

        return self._last_snapshot