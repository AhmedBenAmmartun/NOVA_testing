"""Background runtime coordinator for NOVA Guardian."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .ambient_vision import (
    AmbientVisionMonitor,
    LocalVisionResult,
)
from .config import (
    GuardianConfiguration,
    load_guardian_configuration,
)
from .security_monitor import SecurityMonitor
from .state import (
    GuardianState,
    get_guardian_state,
)
from .window_monitor import ActiveWindowMonitor


logger = logging.getLogger(__name__)


class GuardianRuntime:
    """
    Coordinate NOVA Guardian's background monitors.

    Window and security monitoring can remain active in the background.
    Screenshot analysis only starts after an explicit request.
    """

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

        self.window_monitor = ActiveWindowMonitor(
            configuration=self.configuration,
            state=self.state,
        )

        self.security_monitor = SecurityMonitor(
            configuration=self.configuration,
            state=self.state,
        )

        self.vision_monitor = AmbientVisionMonitor(
            configuration=self.configuration,
            state=self.state,
        )

        self._background_stop_event: asyncio.Event | None = None
        self._vision_stop_event: asyncio.Event | None = None

        self._background_tasks: list[asyncio.Task[Any]] = []
        self._vision_task: asyncio.Task[Any] | None = None
        self._vision_expiration_task: asyncio.Task[Any] | None = None

        self._runtime_lock = asyncio.Lock()

    @staticmethod
    def _task_finished(
        task: asyncio.Task[Any],
    ) -> None:
        """Log unexpected background-task failures."""

        if task.cancelled():
            return

        try:
            exception = task.exception()

        except asyncio.CancelledError:
            return

        if exception is not None:
            logger.error(
                "Guardian background task failed.",
                exc_info=(
                    type(exception),
                    exception,
                    exception.__traceback__,
                ),
            )

    async def start(self) -> bool:
        """
        Start window and security monitoring.

        Returns True when the runtime was newly started.
        """

        async with self._runtime_lock:
            if self._background_tasks:
                active_tasks = [
                    task
                    for task in self._background_tasks
                    if not task.done()
                ]

                if active_tasks:
                    return False

            self._background_tasks.clear()

            if not self.configuration.enabled:
                logger.info(
                    "Guardian runtime was not started because "
                    "Guardian is disabled."
                )
                return False

            self.state.start()

            self._background_stop_event = asyncio.Event()

            if (
                self.configuration
                .active_window_monitor_enabled
            ):
                window_task = asyncio.create_task(
                    self.window_monitor.run(
                        self._background_stop_event
                    ),
                    name="nova-guardian-window-monitor",
                )

                window_task.add_done_callback(
                    self._task_finished
                )

                self._background_tasks.append(
                    window_task
                )

            if (
                self.configuration
                .security_monitor_enabled
            ):
                security_task = asyncio.create_task(
                    self.security_monitor.run(
                        self._background_stop_event
                    ),
                    name="nova-guardian-security-monitor",
                )

                security_task.add_done_callback(
                    self._task_finished
                )

                self._background_tasks.append(
                    security_task
                )

            logger.info(
                "NOVA Guardian background runtime started."
            )

            return True

    async def stop(self) -> bool:
        """
        Stop all Guardian monitoring.

        Returns True when an active runtime was stopped.
        """

        await self.stop_vision()

        async with self._runtime_lock:
            had_active_tasks = any(
                not task.done()
                for task in self._background_tasks
            )

            if self._background_stop_event is not None:
                self._background_stop_event.set()

            tasks = list(
                self._background_tasks
            )

            for task in tasks:
                if not task.done():
                    task.cancel()

            if tasks:
                await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

            self._background_tasks.clear()
            self._background_stop_event = None

            if self.state.snapshot().running:
                self.state.stop()

            logger.info(
                "NOVA Guardian background runtime stopped."
            )

            return had_active_tasks

    async def _expire_vision_after(
        self,
        minutes: float,
    ) -> None:
        """Stop local vision after the requested duration."""

        try:
            await asyncio.sleep(
                max(1.0, minutes * 60.0)
            )

        except asyncio.CancelledError:
            return

        await self.stop_vision()

    async def start_vision(
        self,
        *,
        minutes: float | None = None,
    ) -> bool:
        """
        Start an explicit local-only vision session.

        The session automatically stops after the configured duration.
        """

        await self.start()

        async with self._runtime_lock:
            if (
                self._vision_task is not None
                and not self._vision_task.done()
            ):
                return False

            duration_minutes = (
                float(minutes)
                if minutes is not None
                else float(
                    self.configuration
                    .maximum_vision_session_minutes
                )
            )

            duration_minutes = max(
                0.25,
                min(duration_minutes, 30.0),
            )

            self._vision_stop_event = asyncio.Event()

            self._vision_task = asyncio.create_task(
                self.vision_monitor.run(
                    self._vision_stop_event
                ),
                name="nova-guardian-local-vision",
            )

            self._vision_task.add_done_callback(
                self._task_finished
            )

            self._vision_expiration_task = (
                asyncio.create_task(
                    self._expire_vision_after(
                        duration_minutes
                    ),
                    name=(
                        "nova-guardian-vision-expiration"
                    ),
                )
            )

        await asyncio.sleep(0)

        return True

    async def stop_vision(self) -> bool:
        """
        Stop the current local-vision session.

        This does not stop window or security monitoring.
        """

        async with self._runtime_lock:
            vision_was_active = (
                self.state.snapshot().vision_active
                or (
                    self._vision_task is not None
                    and not self._vision_task.done()
                )
            )

            if self._vision_stop_event is not None:
                self._vision_stop_event.set()

            current_task = asyncio.current_task()

            expiration_task = (
                self._vision_expiration_task
            )

            if (
                expiration_task is not None
                and expiration_task is not current_task
                and not expiration_task.done()
            ):
                expiration_task.cancel()

            vision_task = self._vision_task

            if (
                vision_task is not None
                and vision_task is not current_task
                and not vision_task.done()
            ):
                vision_task.cancel()

            tasks_to_finish = [
                task
                for task in (
                    vision_task,
                    expiration_task,
                )
                if (
                    task is not None
                    and task is not current_task
                )
            ]

            if tasks_to_finish:
                await asyncio.gather(
                    *tasks_to_finish,
                    return_exceptions=True,
                )

            self._vision_task = None
            self._vision_expiration_task = None
            self._vision_stop_event = None

            if self.state.snapshot().vision_active:
                self.state.stop_vision()

            return vision_was_active

    async def look_once(
        self,
        question: str,
    ) -> LocalVisionResult:
        """
        Analyze the current foreground window once.

        The screenshot remains local and is not stored.
        """

        await self.start()

        runtime_snapshot = self.state.snapshot()
        started_vision_here = (
            not runtime_snapshot.vision_active
        )

        if started_vision_here:
            self.state.start_vision()

        try:
            self.window_monitor.poll_once()

            return await self.vision_monitor.analyze_once(
                question=question,
                force=True,
            )

        finally:
            if started_vision_here:
                self.state.stop_vision()

    def scan_security_once(self) -> Any:
        """Run one immediate defensive security scan."""

        if not self.state.snapshot().running:
            self.state.start()

        return self.security_monitor.poll_once()

    def recent_alerts(
        self,
        *,
        limit: int = 10,
    ) -> list[Any]:
        """Return recent events that require attention."""

        safe_limit = max(
            1,
            min(int(limit), 50),
        )

        events = self.state.recent_events(
            limit=50
        )

        alerts = [
            event
            for event in events
            if event.requires_attention
            and not event.acknowledged
        ]

        return alerts[:safe_limit]

    def safe_summary(self) -> dict[str, Any]:
        """Return runtime status without exposing private data."""

        snapshot = self.state.snapshot()

        background_running = any(
            not task.done()
            for task in self._background_tasks
        )

        vision_task_running = (
            self._vision_task is not None
            and not self._vision_task.done()
        )

        return {
            "enabled": self.configuration.enabled,
            "running": snapshot.running,
            "background_running": background_running,
            "window_monitor_enabled": (
                self.configuration
                .active_window_monitor_enabled
            ),
            "security_monitor_enabled": (
                self.configuration
                .security_monitor_enabled
            ),
            "vision_active": snapshot.vision_active,
            "vision_paused": snapshot.vision_paused,
            "vision_pause_reason": (
                snapshot.vision_pause_reason
            ),
            "vision_task_running": vision_task_running,
            "vision_model": self.vision_monitor.model,
            "local_vision_only": (
                self.configuration.local_vision_only
            ),
            "automatic_response_enabled": (
                self.configuration
                .automatic_response_enabled
            ),
        }


_guardian_runtime: GuardianRuntime | None = None


def get_guardian_runtime() -> GuardianRuntime:
    """Return the shared Guardian runtime."""

    global _guardian_runtime

    if _guardian_runtime is None:
        _guardian_runtime = GuardianRuntime()

    return _guardian_runtime