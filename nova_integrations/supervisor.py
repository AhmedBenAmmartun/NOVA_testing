"""Background integration supervisor designed to run beside wake-word standby."""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field

from .connectors import RateLimited
from .sync import SyncCoordinator


logger = logging.getLogger("nova.integrations.supervisor")


@dataclass(slots=True)
class _BackoffState:
    failures: int = 0
    next_allowed: float = 0.0


class IntegrationSupervisor:
    def __init__(
        self,
        coordinator: SyncCoordinator,
        interval_seconds: int = 180,
        max_backoff_seconds: int = 900,
    ) -> None:
        self.coordinator = coordinator
        self.interval_seconds = max(60, int(interval_seconds))
        self.max_backoff_seconds = max(self.interval_seconds, int(max_backoff_seconds))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._backoff: dict[str, _BackoffState] = {}
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="NOVA-EmailCalendar-Sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)

    def sync_now(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            accounts = self.coordinator.accounts.list()
            for account in accounts:
                if self._stop.is_set():
                    break
                state = self._backoff.setdefault(account.account_id, _BackoffState())
                now = time.monotonic()
                if now < state.next_allowed:
                    continue
                try:
                    self.coordinator.sync_account(account.account_id)
                    state.failures = 0
                    state.next_allowed = 0.0
                except RateLimited as exc:
                    state.failures += 1
                    exponential = min(
                        self.max_backoff_seconds,
                        max(exc.retry_after, self.interval_seconds * (2 ** min(state.failures, 5))),
                    )
                    jitter = random.uniform(0, min(30.0, exponential * 0.1))
                    state.next_allowed = time.monotonic() + exponential + jitter
                except Exception:
                    # Coordinator already redacts/audits ordinary failures. This protects the thread itself.
                    logger.exception("Integration supervisor iteration failed")
                    state.failures += 1
                    state.next_allowed = time.monotonic() + min(
                        self.max_backoff_seconds,
                        self.interval_seconds * (2 ** min(state.failures, 5)),
                    )

            elapsed = time.monotonic() - started
            wait_for = max(5.0, self.interval_seconds - elapsed)
            self._wake.wait(wait_for)
            self._wake.clear()
