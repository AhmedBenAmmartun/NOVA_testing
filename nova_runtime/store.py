"""Durable task state, so a NOVA restart does not erase work in flight.

Two files under the runtime root:

``tasks.ndjson``
    Append-only transition log. Every state change is one line, history is
    never rewritten, and a single corrupt line costs only itself.

``tasks.json``
    Atomically replaced index of the newest state per task, so a restart does
    not have to replay the whole log to answer "what was running?".

Recovery is the point of the design. A process that is killed -- by the OS, a
crash, or the machine sleeping -- never gets to write its own ending, so the
log's last word on a task can be ``running`` forever. This repository has now
been bitten by that twice: post-class processing left ``{"status": "running"}``
for eight hours while producing nothing, and a live capture session reported
``audio_integrity_ok: false`` when it meant "nobody has checked yet". Both were
records asserting something they had no basis for.

So the store writes the owning process's identity next to the task and
reinterprets on load: a task left RUNNING by a process that is gone becomes
``INTERRUPTED``. That is deliberately **not** ``FAILED``. Nothing observed a
failure; the observer disappeared. Recording a failure would invent an outcome
that was never measured.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from .task_state import TERMINAL_STATES, JobState, TaskSnapshot

LOG_NAME = "tasks.ndjson"
INDEX_NAME = "tasks.json"


def runtime_root() -> Path:
    """Local-only runtime state root, outside the vault and outside Git.

    Deliberately duplicates ``nova_school.paths.runtime_root`` rather than
    importing it. ``nova_school`` is a domain package whose ``__init__`` eagerly
    loads all of course intelligence (~372ms), and infrastructure must not
    depend on a domain package to know where to write a file.

    The duplication is held together by a test asserting the two resolvers
    return the same path, so the split-brain ``nova_school/paths.py`` warns
    about is caught mechanically instead of by discipline.
    """
    override = os.getenv("NOVA_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NOVA").resolve()


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_record(snapshot: TaskSnapshot) -> dict[str, Any]:
    """Serialize a snapshot. ``result`` is deliberately omitted.

    A result may be any Python object -- unserializable, huge, or holding
    private content. Durable state carries ``result_ref`` instead, so what
    survives a restart is a pointer, never an accidental copy of the payload.
    """
    return {
        "job_id": snapshot.job_id,
        "name": snapshot.name,
        "state": str(snapshot.state),
        "created_at": _isoformat(snapshot.created_at),
        "started_at": _isoformat(snapshot.started_at),
        "finished_at": _isoformat(snapshot.finished_at),
        "error": snapshot.error,
        "parent_id": snapshot.parent_id,
        "children": list(snapshot.children),
        "depends_on": list(snapshot.depends_on),
        "priority": snapshot.priority,
        "progress": snapshot.progress,
        "owner": snapshot.owner,
        "attempt": snapshot.attempt,
        "max_attempts": snapshot.max_attempts,
        "result_ref": snapshot.result_ref,
        "required_permissions": list(snapshot.required_permissions),
        "updated_at": _isoformat(snapshot.updated_at),
    }


def _from_record(record: dict[str, Any]) -> TaskSnapshot | None:
    job_id = record.get("job_id")
    if not job_id:
        return None
    try:
        state = JobState(str(record.get("state")))
    except ValueError:
        return None

    created = _parse_datetime(record.get("created_at")) or TaskSnapshot.now()
    return TaskSnapshot(
        job_id=str(job_id),
        name=str(record.get("name") or ""),
        state=state,
        created_at=created,
        started_at=_parse_datetime(record.get("started_at")),
        finished_at=_parse_datetime(record.get("finished_at")),
        error=record.get("error"),
        parent_id=record.get("parent_id"),
        children=tuple(record.get("children") or ()),
        depends_on=tuple(record.get("depends_on") or ()),
        priority=int(record.get("priority") or 0),
        progress=record.get("progress"),
        owner=record.get("owner"),
        attempt=int(record.get("attempt") or 0),
        max_attempts=int(record.get("max_attempts") or 1),
        result_ref=record.get("result_ref"),
        required_permissions=tuple(record.get("required_permissions") or ()),
        updated_at=_parse_datetime(record.get("updated_at")),
    )


class TaskStore:
    """Append-only task log plus an atomically replaced index."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else runtime_root() / "runtime"
        self.root = self.root.expanduser().resolve()
        self._lock = threading.Lock()

    @property
    def log_path(self) -> Path:
        return self.root / LOG_NAME

    @property
    def index_path(self) -> Path:
        return self.root / INDEX_NAME

    # -- writing -------------------------------------------------------------

    def record(
        self,
        snapshot: TaskSnapshot,
        *,
        pid: int | None = None,
        pid_created_at: float | None = None,
    ) -> None:
        """Append one transition, then refresh the index.

        The owning process identity is stored so that recovery can tell a task
        that is still running from one whose owner died. A bare PID is not
        enough -- the OS recycles them -- so the process creation time is
        recorded alongside it and both must match.
        """
        if pid is None:
            process = psutil.Process(os.getpid())
            pid, pid_created_at = process.pid, process.create_time()

        record = _as_record(snapshot)
        record["pid"] = pid
        record["pid_created_at"] = pid_created_at

        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._write_index_unlocked()

    def _write_index_unlocked(self) -> None:
        index = {job_id: _as_record(task) for job_id, task in self._replay().items()}
        temporary = self.index_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.index_path)

    # -- reading -------------------------------------------------------------

    def _replay(self) -> dict[str, TaskSnapshot]:
        """Fold the append-only log into the newest state per task."""
        tasks: dict[str, TaskSnapshot] = {}
        self._owners: dict[str, tuple[Any, Any]] = {}
        if not self.log_path.exists():
            return tasks

        text = self.log_path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # One bad write must not cost every other task's state.
                continue
            if not isinstance(record, dict):
                continue
            snapshot = _from_record(record)
            if snapshot is None:
                continue
            tasks[snapshot.job_id] = snapshot
            self._owners[snapshot.job_id] = (
                record.get("pid"),
                record.get("pid_created_at"),
            )
        return tasks

    def load(self) -> dict[str, TaskSnapshot]:
        """Every task's newest recorded state, exactly as written."""
        return self._replay()

    # -- recovery ------------------------------------------------------------

    def recover(self) -> dict[str, TaskSnapshot]:
        """Load, then reinterpret tasks whose owning process is gone.

        Only ``RUNNING`` is ambiguous. A task that reported a terminal state
        told us something the OS cannot contradict, so terminal states are
        never rewritten.
        """
        tasks = self._replay()
        owners = getattr(self, "_owners", {})
        changed: list[TaskSnapshot] = []

        for job_id, task in tasks.items():
            if task.state in TERMINAL_STATES or task.state is not JobState.RUNNING:
                continue
            pid, pid_created_at = owners.get(job_id, (None, None))
            if _process_identity_matches(pid, pid_created_at):
                continue
            tasks[job_id] = replace(
                task,
                state=JobState.INTERRUPTED,
                error=(
                    task.error
                    or "The process running this task exited without reporting a "
                    "result. Nothing observed a failure; the observer went away."
                ),
                finished_at=task.finished_at or TaskSnapshot.now(),
                updated_at=TaskSnapshot.now(),
            )
            changed.append(tasks[job_id])

        # Persist the conclusion so a second restart does not re-derive it.
        for task in changed:
            self.record(task)

        return tasks


def _process_identity_matches(pid: Any, created_at: Any) -> bool:
    """True only when ``pid`` is alive AND is the process born at ``created_at``."""
    if pid is None or created_at is None:
        return False
    try:
        process = psutil.Process(int(pid))
        return abs(float(process.create_time()) - float(created_at)) < 2.0
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False
