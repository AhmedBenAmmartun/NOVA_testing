"""The one owner of a class sitting.

Before this module the *LiveKit AgentSession* was, in practice, the owner of a
class: when it went away for any reason -- an STT disconnect, a transport
error, a job shutdown -- the shutdown callback stopped the microphone and the
lecture recording ended with it. A real 38m36s lecture was lost that way on
2026-08-27 while the user was still in class.

``ClassSessionSupervisor`` inverts that. It owns the session id, the session
path, the stop request, and the health of every worker. Workers may fail,
restart, or never start at all; the sitting stays the same sitting, with the
same id, until the user asks it to stop or the microphone itself dies
unrecoverably.

Everything here is deliberately dependency-free (no LiveKit, no providers, no
network) so a full 180-minute session can be simulated deterministically in a
test in milliseconds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from .audio_chunks import atomic_write_json, scan_audio_dir


HEALTH_NAME = "health.json"
EVENTS_NAME = "events.jsonl"


class WorkerStatus(StrEnum):
    """Every state a Class Capture worker may report."""

    STARTING = "starting"
    RECORDING = "recording"
    CONNECTED = "connected"
    ACTIVE = "active"
    TRACKING = "tracking"
    QUEUED = "queued"
    RECOVERING = "recovering"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    FAILED = "failed"
    STOPPED = "stopped"
    DISABLED = "disabled"


#: Statuses that mean "this worker is doing its job right now".
_HEALTHY = frozenset(
    {
        WorkerStatus.RECORDING,
        WorkerStatus.CONNECTED,
        WorkerStatus.ACTIVE,
        WorkerStatus.TRACKING,
    }
)

#: Statuses that must downgrade a finalized session to completed_with_warnings.
_WARNING = frozenset(
    {
        WorkerStatus.RECOVERING,
        WorkerStatus.DEGRADED,
        WorkerStatus.OFFLINE,
        WorkerStatus.QUEUED,
        WorkerStatus.FAILED,
    }
)


class SessionOutcome(StrEnum):
    """How a sitting actually ended. ``completed`` is never assumed."""

    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    ABORTED = "aborted"


class CaptureEvent(StrEnum):
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_STOPPING = "SESSION_STOPPING"
    SESSION_FINALIZED = "SESSION_FINALIZED"
    AUDIO_STARTED = "AUDIO_STARTED"
    AUDIO_FAILED = "AUDIO_FAILED"
    AUDIO_STOPPED = "AUDIO_STOPPED"
    AUDIO_RESTARTED = "AUDIO_RESTARTED"
    STT_CONNECTED = "STT_CONNECTED"
    STT_GAP_START = "STT_GAP_START"
    STT_GAP_END = "STT_GAP_END"
    STT_RESTART = "STT_RESTART"
    STT_FAILED = "STT_FAILED"
    WORKER_STATUS = "WORKER_STATUS"
    WORKER_LOST = "WORKER_LOST"
    NOTES_QUEUED = "NOTES_QUEUED"
    NOTES_UPDATED = "NOTES_UPDATED"
    NOTES_DEGRADED = "NOTES_DEGRADED"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    PROVIDER_RECOVERED = "PROVIDER_RECOVERED"
    SPEAKER_ROLE_CHANGED = "SPEAKER_ROLE_CHANGED"
    STOP_REQUESTED = "STOP_REQUESTED"
    ERROR = "ERROR"


@dataclass(slots=True)
class WorkerHealth:
    name: str
    status: WorkerStatus = WorkerStatus.STARTING
    detail: str | None = None
    updated_seconds: float = 0.0
    restarts: int = 0
    failures: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self, *, now_seconds: float) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value,
            "detail": self.detail,
            "updated_seconds": round(self.updated_seconds, 3),
            "age_seconds": round(max(0.0, now_seconds - self.updated_seconds), 3),
            "restarts": self.restarts,
            "failures": self.failures,
        }
        payload.update(self.extra)
        return payload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClassSessionSupervisor:
    """Owns one logical class sitting and everything that reports into it.

    The supervisor never touches the microphone itself. It is told what the
    recorder is doing (``audio_progress``) and what the intelligence workers
    are doing (``set_worker``), and it decides what that means for the sitting.
    """

    def __init__(
        self,
        *,
        session_id: str,
        course: str,
        session_path: Path,
        clock: Callable[[], float] = time.monotonic,
        health_interval_seconds: float = 5.0,
    ) -> None:
        self.session_id = str(session_id)
        self.course = str(course)
        self.session_path = Path(session_path)
        self._clock = clock
        self.health_interval_seconds = max(0.5, float(health_interval_seconds))

        self.started_at_wall = _utc_now_iso()
        self._started = self._clock()
        self._stop_requested = False
        self._stop_reason: str | None = None
        self._finalized = False
        self._outcome: SessionOutcome | None = None
        self._finalization_errors: list[str] = []

        self._workers: dict[str, WorkerHealth] = {}
        self._audio_written_until = 0.0
        self._transcription_confirmed_until = 0.0
        self._stt_gap_open_at: float | None = None
        self._stt_gaps: list[dict[str, float]] = []
        self._stt_reconnects = 0

        self.health_path = self.session_path / HEALTH_NAME
        self.events_path = self.session_path / EVENTS_NAME
        self._last_health_write = -1e9

    # --- time ------------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self._clock() - self._started)

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def finalized(self) -> bool:
        return self._finalized

    @property
    def outcome(self) -> SessionOutcome | None:
        return self._outcome

    @property
    def stt_reconnects(self) -> int:
        return self._stt_reconnects

    @property
    def audio_written_until(self) -> float:
        return self._audio_written_until

    @property
    def transcription_confirmed_until(self) -> float:
        return self._transcription_confirmed_until

    # --- lifecycle -------------------------------------------------------

    def open(self) -> None:
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self.record_event(
            CaptureEvent.SESSION_STARTED,
            session_id=self.session_id,
            course=self.course,
        )
        self.write_health(force=True)

    def request_stop(self, reason: str = "user_requested") -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        self._stop_reason = reason
        self.record_event(CaptureEvent.STOP_REQUESTED, reason=reason)
        self.write_health(force=True)

    def note_finalization_error(self, stage: str, error: BaseException | str) -> None:
        """Record a finalization failure so stop can never silently claim success."""
        detail = (
            f"{stage}: {type(error).__name__}: {error}"
            if isinstance(error, BaseException)
            else f"{stage}: {error}"
        )
        self._finalization_errors.append(detail)
        self.record_event(CaptureEvent.ERROR, stage=stage, detail=detail)

    def resolve_outcome(self, *, requested: str | None = None) -> SessionOutcome:
        """Decide what actually happened. Never optimistic."""
        if requested in {"failed", "error"}:
            return SessionOutcome.FAILED
        if requested == "aborted":
            return SessionOutcome.ABORTED

        if self._finalization_errors:
            return SessionOutcome.FAILED

        audio = self._workers.get("audio")
        if audio is None or audio.status in {WorkerStatus.FAILED, WorkerStatus.OFFLINE}:
            return SessionOutcome.FAILED

        integrity = self.audio_integrity()
        if not integrity.healthy:
            return SessionOutcome.COMPLETED_WITH_WARNINGS

        if self._stt_gaps or self._stt_reconnects:
            return SessionOutcome.COMPLETED_WITH_WARNINGS

        for worker in self._workers.values():
            if worker.status in _WARNING or worker.failures:
                return SessionOutcome.COMPLETED_WITH_WARNINGS

        if not self._stop_requested:
            # Finalizing without an explicit stop means something else ended
            # the sitting. That is exactly the 2026-08-27 failure mode and it
            # must never be reported as a clean completion.
            return SessionOutcome.COMPLETED_WITH_WARNINGS

        return SessionOutcome.COMPLETED

    def finalize(self, *, requested: str | None = None) -> SessionOutcome:
        outcome = self.resolve_outcome(requested=requested)
        self._outcome = outcome
        self._finalized = True
        self.record_event(
            CaptureEvent.SESSION_FINALIZED,
            outcome=outcome.value,
            stop_requested=self._stop_requested,
            stop_reason=self._stop_reason,
            errors=list(self._finalization_errors),
        )
        self.write_health(force=True)
        return outcome

    # --- workers ---------------------------------------------------------

    def set_worker(
        self,
        name: str,
        status: WorkerStatus,
        *,
        detail: str | None = None,
        restarted: bool = False,
        failed: bool = False,
        **extra: Any,
    ) -> WorkerHealth:
        worker = self._workers.get(name)
        if worker is None:
            worker = WorkerHealth(name=name)
            self._workers[name] = worker

        changed = worker.status is not status or worker.detail != detail
        worker.status = status
        worker.detail = detail
        worker.updated_seconds = self.elapsed_seconds
        if restarted:
            worker.restarts += 1
        if failed:
            worker.failures += 1
        if extra:
            worker.extra.update(extra)

        if changed:
            self.record_event(
                CaptureEvent.WORKER_STATUS,
                worker=name,
                status=status.value,
                detail=detail,
            )
        self.write_health()
        return worker

    def worker(self, name: str) -> WorkerHealth | None:
        return self._workers.get(name)

    def worker_status(self, name: str) -> WorkerStatus:
        worker = self._workers.get(name)
        return worker.status if worker is not None else WorkerStatus.OFFLINE

    @staticmethod
    def status_is_healthy(status: WorkerStatus) -> bool:
        """True when the status means the worker is doing its job right now."""
        return status in _HEALTHY

    def worker_is_healthy(self, name: str) -> bool:
        return self.status_is_healthy(self.worker_status(name))

    # --- audio -----------------------------------------------------------

    def audio_progress(
        self,
        *,
        recorded_seconds: float,
        chunks: int,
        last_chunk: int,
        last_write_age_seconds: float | None,
        status: WorkerStatus = WorkerStatus.RECORDING,
        detail: str | None = None,
    ) -> None:
        self._audio_written_until = max(
            self._audio_written_until, max(0.0, float(recorded_seconds))
        )
        self.set_worker(
            "audio",
            status,
            detail=detail,
            chunks=int(chunks),
            last_chunk=int(last_chunk),
            recorded_seconds=round(float(recorded_seconds), 3),
            last_write_age_seconds=(
                None
                if last_write_age_seconds is None
                else round(float(last_write_age_seconds), 3)
            ),
        )

    def audio_integrity(self):
        """Integrity of the recording, judged against whether it is still live."""
        return scan_audio_dir(
            self.session_path / "audio",
            recording=self.worker_status("audio") is WorkerStatus.RECORDING,
        )

    # --- STT -------------------------------------------------------------

    def transcription_progress(self, confirmed_until_seconds: float) -> None:
        self._transcription_confirmed_until = max(
            self._transcription_confirmed_until,
            max(0.0, float(confirmed_until_seconds)),
        )
        if self._stt_gap_open_at is not None:
            self.stt_gap_end()
        self.set_worker(
            "stt",
            WorkerStatus.CONNECTED,
            confirmed_until_seconds=round(self._transcription_confirmed_until, 3),
        )

    @property
    def transcript_lag_seconds(self) -> float:
        return max(
            0.0, self._audio_written_until - self._transcription_confirmed_until
        )

    def stt_gap_start(self, reason: str) -> None:
        if self._stt_gap_open_at is not None:
            return
        self._stt_gap_open_at = self._audio_written_until or self.elapsed_seconds
        self.record_event(
            CaptureEvent.STT_GAP_START,
            reason=reason,
            audio_seconds=round(self._stt_gap_open_at, 3),
        )
        self.set_worker("stt", WorkerStatus.RECOVERING, detail=reason, failed=True)

    def stt_gap_end(self) -> dict[str, float] | None:
        if self._stt_gap_open_at is None:
            return None
        start = self._stt_gap_open_at
        end = self._audio_written_until or self.elapsed_seconds
        self._stt_gap_open_at = None
        gap = {
            "start_seconds": round(start, 3),
            "end_seconds": round(max(end, start), 3),
            "backfilled": False,
        }
        self._stt_gaps.append(gap)
        self.record_event(CaptureEvent.STT_GAP_END, **gap)
        return gap

    def stt_restarted(self) -> None:
        self._stt_reconnects += 1
        self.record_event(CaptureEvent.STT_RESTART, attempt=self._stt_reconnects)
        self.set_worker("stt", WorkerStatus.RECOVERING, restarted=True)

    def stt_gaps(self) -> tuple[dict[str, float], ...]:
        return tuple(self._stt_gaps)

    @property
    def unrecovered_gap_count(self) -> int:
        return sum(1 for gap in self._stt_gaps if not gap.get("backfilled"))

    # --- journals --------------------------------------------------------

    def record_event(self, event: CaptureEvent | str, **payload: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event": str(getattr(event, "value", event)),
            "at": _utc_now_iso(),
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "session_id": self.session_id,
        }
        record.update(payload)
        try:
            self.session_path.mkdir(parents=True, exist_ok=True)
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str))
                handle.write("\n")
        except OSError:
            # The event journal is diagnostic. Losing a line must never take
            # down a live class.
            pass
        return record

    def health_snapshot(self) -> dict[str, Any]:
        now = self.elapsed_seconds
        integrity = self.audio_integrity()
        return {
            "version": 1,
            "session_id": self.session_id,
            "course": self.course,
            "session_path": str(self.session_path),
            "session_active": not self._finalized,
            "stop_requested": self._stop_requested,
            "stop_reason": self._stop_reason,
            "outcome": self._outcome.value if self._outcome else None,
            "started_at": self.started_at_wall,
            "updated_at": _utc_now_iso(),
            "duration_seconds": round(now, 3),
            "audio_written_until": round(self._audio_written_until, 3),
            "transcription_confirmed_until": round(
                self._transcription_confirmed_until, 3
            ),
            "transcript_lag_seconds": round(self.transcript_lag_seconds, 3),
            "workers": {
                name: worker.as_dict(now_seconds=now)
                for name, worker in sorted(self._workers.items())
            },
            "recovery": {
                "stt_reconnects": self._stt_reconnects,
                "stt_gaps": [dict(gap) for gap in self._stt_gaps],
                "unrecovered_gaps": self.unrecovered_gap_count,
            },
            "audio_integrity": integrity.as_dict(),
            "finalization_errors": list(self._finalization_errors),
        }

    def write_health(self, *, force: bool = False) -> dict[str, Any] | None:
        now = self._clock()
        if not force and (now - self._last_health_write) < self.health_interval_seconds:
            return None
        self._last_health_write = now
        payload = self.health_snapshot()
        try:
            atomic_write_json(self.health_path, payload)
        except OSError:
            return payload
        return payload


def read_health(session_path: Path) -> dict[str, Any] | None:
    path = Path(session_path) / HEALTH_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_events(session_path: Path) -> list[dict[str, Any]]:
    path = Path(session_path) / EVENTS_NAME
    items: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return items
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items
