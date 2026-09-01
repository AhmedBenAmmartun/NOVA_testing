"""ONE-NOVA adapter for Class Intelligence."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from livekit.agents import function_tool

from nova_capture.control import (
    close_capture_launcher_tree,
    close_legacy_launcher_after_save,
    read_active_session,
    request_stop,
    wait_until_inactive,
)
from nova_capture.markers import MarkerJournal
from nova_capture.models import MarkerKind
from nova_school import CourseRegistry, resolve_current_course
from nova_school.resolver import resolve_requested_course

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CLASS_CAPTURE_ENTRYPOINT = _PROJECT_ROOT / "class_capture.py"


def _launcher_log_path() -> Path:
    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    root = base / "NOVA" / "ClassCapture" / "_control"
    root.mkdir(parents=True, exist_ok=True)
    return root / "background-launch.log"


def _launcher_log_tail(max_lines: int = 30) -> str:
    path = _launcher_log_path()
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max(1, int(max_lines)):])


def _python_executable() -> Path:
    configured = os.getenv("NOVA_PYTHON", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if candidate.exists():
            return candidate
    venv_python = _PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable).resolve()


def _normalize_course(course: str | None) -> str:
    return " ".join((course or "").split()).strip()



def _resolve_course_for_start(course: str | None):
    """Return a canonical course before starting any subprocess.

    Explicit user choice wins regardless of schedule. If no explicit course is
    supplied, the current schedule is a convenience for automatic resolution.
    """

    registry = CourseRegistry()
    requested = _normalize_course(course)
    if requested:
        resolved = resolve_requested_course(requested, registry=registry)
        return resolved, "explicit user request"

    scheduled = resolve_current_course(registry=registry)
    if scheduled is not None:
        return scheduled, "verified schedule"

    return None, "course required"
def _launch_capture_worker(course: str | None = None) -> int:
    """Launch the existing Class Capture worker and preserve startup diagnostics."""

    active = read_active_session(clean_stale=True)
    if active is not None:
        raise RuntimeError(
            f"Class capture is already active for {active.course} "
            f"(session {active.session_id})."
        )

    if not _CLASS_CAPTURE_ENTRYPOINT.exists():
        raise RuntimeError(
            f"Class Capture entrypoint was not found: {_CLASS_CAPTURE_ENTRYPOINT}"
        )

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    normalized_course = _normalize_course(course)
    if normalized_course:
        env["NOVA_CLASS_COURSE"] = normalized_course
    else:
        env.pop("NOVA_CLASS_COURSE", None)

    creationflags = 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)

    log_path = _launcher_log_path()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(
            f"NOVA background class launch\n"
            f"course={normalized_course or '(schedule)'}\n"
            f"python={_python_executable()}\n"
            f"entrypoint={_CLASS_CAPTURE_ENTRYPOINT}\n\n"
        )
        log.flush()

        process = subprocess.Popen(
            [str(_python_executable()), str(_CLASS_CAPTURE_ENTRYPOINT), "console"],
            cwd=str(_PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            close_fds=(os.name != "nt"),
        )

    return int(process.pid)


def _wait_for_active_capture(
    worker_pid: int | None = None,
    timeout_seconds: float = 12.0,
    poll_seconds: float = 0.20,
):
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    while time.monotonic() < deadline:
        active = read_active_session(clean_stale=True)
        if active is not None:
            return active

        if worker_pid:
            try:
                import psutil
                process = psutil.Process(int(worker_pid))
                if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
                    return None
            except psutil.NoSuchProcess:
                return None
            except (psutil.AccessDenied, ValueError, TypeError):
                pass

        time.sleep(max(0.05, float(poll_seconds)))
    return None


def _elapsed_seconds(started_at: str) -> float:
    try:
        started = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return 0.0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds())


def _read_recent_transcript(session_path: str | Path, max_lines: int = 30) -> str:
    root = Path(session_path).expanduser().resolve()
    readable = root / "transcript.txt"
    if readable.exists():
        lines = readable.read_text(encoding="utf-8", errors="replace").splitlines()
        selected = [line for line in lines if line.strip()][-max(1, int(max_lines)):]
        return "\n".join(selected)

    jsonl = root / "transcript.jsonl"
    if not jsonl.exists():
        return ""

    output: list[str] = []
    for raw in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        text = " ".join(str(payload.get("text", "")).split())
        if not text:
            continue
        speaker = payload.get("speaker") or payload.get("speaker_id") or "speaker"
        output.append(f"[{speaker}] {text}")
    return "\n".join(output[-max(1, int(max_lines)):])


def _verify_saved_audio(session_path: Path) -> tuple[bool, str]:
    """Confirm a real recording exists, chunked or legacy single-file.

    Chunked sessions are the current format; ``audio.wav`` is still accepted so
    sessions captured before the durable recorder verify correctly.
    """
    from nova_capture.audio_chunks import scan_audio_dir

    report = scan_audio_dir(session_path / "audio")
    if report.chunk_count:
        minutes = report.recorded_seconds / 60.0
        detail = f"{report.chunk_count} chunks, {minutes:.1f} min"
        if not report.healthy:
            return True, detail + ", integrity NEEDS REVIEW"
        return True, detail

    legacy = session_path / "audio.wav"
    if legacy.exists() and legacy.stat().st_size > 44:
        return True, "legacy audio.wav"
    return False, "no audio chunks or audio.wav found"


@function_tool()
async def start_class_capture(course: str = "") -> str:
    """Begin class recording as a background capability of this same NOVA.

    Use ONLY when the user asks to begin/start recording a class or lecture.
    Do not call this for ordinary lecture speech, transcript questions, marks,
    status checks, or corrections unrelated to starting capture.

    An explicit known course is allowed at ANY time; meeting time is never a
    permission gate. If no course is supplied, NOVA may use the current
    schedule as a convenience. If neither resolves, ask the user which class.
    """

    existing = read_active_session(clean_stale=True)
    if existing is not None:
        return (
            f"Class recording is already active for {existing.course}. "
            f"Session: {existing.session_id}. Do not start another recorder."
        )

    resolved, reason = _resolve_course_for_start(course)
    if resolved is None:
        registry = CourseRegistry()
        known = ", ".join(c.code for c in registry.load() if c.active)
        if course and course.strip():
            return (
                f"I can record at any time, but I couldn't safely match '{course}' "
                f"to a known class. Known classes: {known}. Ask the user which one "
                "they mean instead of guessing."
            )
        return (
            "I can record class at any time. There isn't one scheduled right now, "
            f"so tell me which class this is. Known classes: {known}."
        )

    canonical_course = resolved.code
    worker_pid: int | None = None
    try:
        worker_pid = await asyncio.to_thread(
            _launch_capture_worker,
            canonical_course,
        )
        active = await asyncio.to_thread(
            _wait_for_active_capture,
            worker_pid,
        )
    except Exception as exc:
        cleanup = ""
        if worker_pid is not None:
            cleanup = await asyncio.to_thread(
                close_capture_launcher_tree,
                worker_pid,
            )
        suffix = f" Launch cleanup: {cleanup}." if cleanup else ""
        return (
            f"I couldn't start class recording: {type(exc).__name__}: {exc}"
            + suffix
        )

    if active is None:
        cleanup = await asyncio.to_thread(
            close_capture_launcher_tree,
            worker_pid,
        )
        tail = _launcher_log_tail() if "_launcher_log_tail" in globals() else ""
        detail = f"\nStartup log:\n{tail}" if tail else ""
        return (
            f"I resolved this as {canonical_course} ({reason}) and launched the "
            "recorder, but it did not become healthy. I am not claiming recording "
            f"succeeded. Worker PID: {worker_pid}. Launch cleanup: {cleanup}."
            + detail
        )

    return (
        f"Class recording is active for {active.course} ({reason}). "
        f"Session: {active.session_id}. I can keep talking with you and use my "
        "other capabilities while it records."
    )

@function_tool()
async def get_class_capture_status() -> str:
    """Check whether a class recording is active."""
    active = read_active_session(clean_stale=True)
    if active is None:
        return "No class recording is active."
    elapsed = _elapsed_seconds(active.started_at)
    return (
        f"Class recording is active for {active.course}. Session: {active.session_id}. "
        f"Elapsed: {elapsed / 60.0:.1f} minutes. Session path: {active.session_path}"
    )


@function_tool()
async def get_recent_class_context(max_lines: int = 30) -> str:
    """Read recent finalized lecture transcript so NOVA can answer about what was just said."""
    active = read_active_session(clean_stale=True)
    if active is None:
        return "No active class recording exists, so there is no live class transcript to read."
    text = await asyncio.to_thread(
        _read_recent_transcript,
        active.session_path,
        max_lines=max(5, min(int(max_lines), 80)),
    )
    if not text:
        return f"{active.course} is recording, but no finalized transcript lines are available yet."
    return (
        f"Recent finalized transcript for {active.course}:\n\n{text}\n\n"
        "Treat this as transcript evidence. If wording is unclear or fragmented, "
        "say so rather than inventing missing speech."
    )


@function_tool()
async def mark_class_moment(label: str = "Important") -> str:
    """Mark the current point in the active lecture as important."""
    active = read_active_session(clean_stale=True)
    if active is None:
        return "No class recording is active, so there is nothing to mark."

    marker_path = Path(active.session_path) / "markers.jsonl"
    elapsed = _elapsed_seconds(active.started_at)
    cleaned = " ".join((label or "Important").split()).strip() or "Important"

    try:
        journal = MarkerJournal(marker_path)
        marker = await asyncio.to_thread(journal.add, elapsed, MarkerKind.IMPORTANT, cleaned)
    except Exception as exc:
        return f"I couldn't mark the class moment: {type(exc).__name__}: {exc}"

    return (
        f"Marked {active.course} at {marker.timestamp_seconds:.1f} seconds "
        f"as important: {marker.label}"
    )


@function_tool()
async def end_class_capture() -> str:
    """Gracefully finish the active class recording without shutting down NOVA."""
    active = request_stop()
    if active is None:
        return "No class recording is active."

    completed = await asyncio.to_thread(
        wait_until_inactive,
        active.session_id,
        timeout_seconds=35.0,
        poll_seconds=0.20,
    )
    if not completed:
        return (
            f"I sent the stop request for {active.course}, but finalization has not "
            "completed yet. I am not claiming the class is saved yet."
        )

    session_path = Path(active.session_path)
    transcript_ok = (session_path / "transcript.jsonl").exists()
    audio_ok, audio_detail = _verify_saved_audio(session_path)
    session_json = session_path / "session.json"

    status = "unknown"
    if session_json.exists():
        try:
            status = str(json.loads(session_json.read_text(encoding="utf-8")).get("status", "unknown"))
        except Exception:
            pass

    launcher_cleanup = await asyncio.to_thread(
        close_legacy_launcher_after_save,
        active,
    )

    verification = [
        "transcript saved" if transcript_ok else "transcript needs verification",
        (
            f"audio saved ({audio_detail})"
            if audio_ok
            else f"audio unavailable/needs verification ({audio_detail})"
        ),
    ]
    return (
        f"{active.course} class recording finalized with status {status}. "
        + ", ".join(verification)
        + f". Capture cleanup: {launcher_cleanup}. "
        + f"Session: {active.session_path}. NOVA is still running normally."
    )


CLASS_CAPTURE_TOOLS = (
    start_class_capture,
    get_class_capture_status,
    get_recent_class_context,
    mark_class_moment,
    end_class_capture,
)
