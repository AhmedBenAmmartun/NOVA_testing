"""Human-readable Class Capture status.

Written in Python rather than PowerShell so the same rendering is used by
``Get-NOVA-Class-Status.ps1``, by tests, and by anything else that needs to ask
"is my class still recording?" -- and so the answer comes from the session's own
``health.json`` and ``audio/recorder.json`` rather than from a guess.

The one rule this file exists to enforce: never report a class as healthy
because a process is alive. Report what the recording itself says.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audio_chunks import scan_audio_dir
from .control import read_active_session
from .postprocess import read_postprocess_status
from .recorder_process import read_recorder_state
from .storage import default_capture_root
from .supervisor import read_health


def _clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _age(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        return f"{float(value):.1f} sec ago"
    except (TypeError, ValueError):
        return "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def latest_session_path(root: Path | None = None) -> Path | None:
    base = Path(root) if root is not None else default_capture_root()
    if not base.is_dir():
        return None
    candidates = [
        path
        for path in base.glob("*/*")
        if path.is_dir() and (path / "session.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _elapsed_from_iso(value: str | None) -> float | None:
    if not value:
        return None
    try:
        started = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds())


def render_status(session_path: Path | None = None) -> str:
    """Build the status report for the active class, or the most recent one."""
    active = read_active_session(clean_stale=True)
    if session_path is None:
        session_path = (
            Path(active.session_path) if active is not None else latest_session_path()
        )

    lines = ["=" * 60, "NOVA CLASS CAPTURE", "=" * 60]

    if session_path is None:
        lines.append("No class session has been recorded yet.")
        return "\n".join(lines)

    session = _load_json(session_path / "session.json")
    health = read_health(session_path) or {}
    recorder = read_recorder_state(session_path) or {}
    integrity = scan_audio_dir(
        session_path / "audio",
        recording=recorder.get("status") == "recording",
    )

    course = str(session.get("course") or health.get("course") or "unknown")
    session_id = str(session.get("session_id") or health.get("session_id") or "unknown")

    if active is not None and str(active.session_id) == session_id:
        state = "ACTIVE"
        duration = _elapsed_from_iso(active.started_at)
    else:
        state = str(session.get("status") or "unknown").upper()
        duration = health.get("duration_seconds")
        if duration is None:
            duration = _elapsed_from_iso(str(session.get("started_at") or ""))

    lines.append(f"State:    {state}")
    lines.append(f"Course:   {course}")
    lines.append(f"Session:  {session_id}")
    lines.append(f"Duration: {_clock(float(duration or 0.0))}")
    lines.append(f"Path:     {session_path}")
    lines.append("")

    workers = health.get("workers") if isinstance(health.get("workers"), dict) else {}
    audio_worker = workers.get("audio", {}) if isinstance(workers, dict) else {}

    audio_status = str(
        recorder.get("status") or audio_worker.get("status") or "unknown"
    ).upper()
    lines.append(f"AUDIO:       {audio_status}")
    lines.append(f"Last write:  {_age(recorder.get('last_write_age_seconds'))}")
    lines.append(f"Chunks:      {integrity.chunk_count}")
    lines.append(f"Recorded:    {_clock(integrity.recorded_seconds)}")
    lines.append(
        "Isolation:   "
        + (
            "separate process"
            if recorder.get("mode") == "process" or audio_worker.get("isolated")
            else str(recorder.get("mode") or audio_worker.get("mode") or "unknown")
        )
    )
    if not integrity.healthy:
        lines.append("Integrity:   NEEDS REVIEW")
        if integrity.missing_files:
            lines.append(f"  missing chunks:    {len(integrity.missing_files)}")
        if integrity.incomplete_files:
            lines.append(f"  incomplete chunks: {len(integrity.incomplete_files)}")
        if integrity.sequence_gaps:
            lines.append(f"  sequence gaps:     {len(integrity.sequence_gaps)}")
        if integrity.timestamp_gaps:
            lines.append(f"  timestamp gaps:    {len(integrity.timestamp_gaps)}")
        if integrity.truncated_files:
            lines.append(f"  truncated chunks:  {len(integrity.truncated_files)}")
    else:
        lines.append("Integrity:   OK")
    if integrity.in_progress_files:
        lines.append(f"In progress: {integrity.in_progress_files[0]}")
    if recorder.get("error"):
        lines.append(f"Audio error: {recorder['error']}")
    lines.append("")

    stt = workers.get("stt", {}) if isinstance(workers, dict) else {}
    lines.append(f"STT:         {str(stt.get('status') or 'unknown').upper()}")
    lines.append(
        f"Transcript:  {float(health.get('transcript_lag_seconds') or 0.0):.1f} sec behind audio"
    )
    if stt.get("detail"):
        lines.append(f"STT detail:  {stt['detail']}")
    lines.append("")

    notes = workers.get("notes", {}) if isinstance(workers, dict) else {}
    lines.append(f"NOTES:       {str(notes.get('status') or 'unknown').upper()}")
    if notes.get("last_update_seconds") is not None:
        lines.append(
            f"Covers up to: {_clock(float(notes.get('last_update_seconds') or 0.0))} of lecture"
        )
    notes_state = _load_json(session_path / "live_notes_state.json")
    if notes_state:
        lines.append(f"Folded batches: {notes_state.get('processed_count', 0)}")
        pending = notes_state.get("pending_note_batches")
        if pending:
            lines.append(f"Queued batches: {pending}")
    if notes.get("detail"):
        lines.append(f"Notes detail: {notes['detail']}")
    lines.append("")

    lines.append("SPEAKERS:")
    live = _load_json(session_path / "speaker_roles_live.json")
    assessments = live.get("assessments") if isinstance(live, dict) else None
    if isinstance(assessments, dict) and assessments:
        for speaker_id, item in sorted(assessments.items()):
            lines.append(
                f"  Speaker {speaker_id}: {item.get('label', 'Unknown')} "
                f"({float(item.get('confidence') or 0.0) * 100:.0f}%)"
            )
    else:
        final = _load_json(session_path / "speaker_roles.json")
        speakers = final.get("speakers") if isinstance(final, dict) else None
        if isinstance(speakers, dict) and speakers:
            for speaker_id, item in sorted(speakers.items()):
                lines.append(
                    f"  Speaker {speaker_id}: {item.get('label', 'Unknown')} "
                    f"({float(item.get('confidence') or 0.0) * 100:.0f}%)"
                )
        else:
            lines.append("  No speakers observed yet.")
    lines.append("")

    raw_recovery = health.get("recovery")
    recovery: dict[str, Any] = raw_recovery if isinstance(raw_recovery, dict) else {}
    lines.append("RECOVERY:")
    lines.append(f"  STT reconnects:   {recovery.get('stt_reconnects', 0)}")
    lines.append(f"  Unrecovered gaps: {recovery.get('unrecovered_gaps', 0)}")
    errors = health.get("finalization_errors") or []
    if errors:
        lines.append("  FINALIZATION PROBLEMS:")
        lines.extend(f"    - {item}" for item in errors)
    if health.get("outcome"):
        lines.append(f"  Outcome: {health['outcome']}")
    lines.append("")

    # Resolved against process liveness, never read raw: a post-class job that
    # was killed cannot write its own failure, and reporting its stale
    # "running" as healthy is how a real lecture lost its notes unnoticed.
    post = read_postprocess_status(session_path)
    if post.get("status") != "not_started":
        lines.append(f"POST-CLASS:  {str(post.get('status') or 'unknown').upper()}")
        if post.get("output_folder"):
            lines.append(f"  Notes: {post['output_folder']}")
        if post.get("error"):
            lines.append(f"  Error: {post['error']}")
    else:
        lines.append("POST-CLASS:  not started")

    return "\n".join(lines)


#: Metrics that only become real when finalize() runs. Before that they are
#: dataclass defaults in session.json and must never be reported as fact.
_FINALIZED_ONLY = (
    "audio_chunks",
    "audio_seconds",
    "audio_integrity_ok",
    "recorder_mode",
    "recorder_isolated",
    "transcript_segment_count",
    "stt_restarts",
)


def session_metrics(session_path: Path) -> dict[str, Any]:
    """The trustworthy view of a session's counts.

    ``session.json`` is the session MANIFEST and only carries real measurements
    after finalize(); ``health.json`` is the live truth while recording. Reading
    either one alone produces a confident falsehood -- a live COT3400 lecture
    reported ``recorder_mode: "none"`` and ``audio_integrity_ok: false`` from
    session.json while health.json showed 84 chunks from an isolated, healthy
    recorder.

    So the reader resolves it: finalized sessions answer from session.json,
    live ones from health.json, and anything genuinely unmeasured answers
    ``None`` rather than a placeholder zero. ``None`` means "nobody has
    checked", which is a different claim from "checked, and it is zero".
    """
    session = _load_json(session_path / "session.json")
    if not session:
        return {
            "finalized": False,
            "source": "none",
            **{name: None for name in _FINALIZED_ONLY},
        }

    recorded = session.get("metrics_finalized")
    if recorded is None:
        # Sessions written before this flag existed. A stopped session already
        # holds real finalize() values and must not lose them; one still
        # recording holds placeholders and must not be believed.
        finalized = bool(session.get("stopped_at")) or str(
            session.get("status") or ""
        ) not in {"recording", ""}
    else:
        finalized = bool(recorded)

    if finalized:
        return {
            "finalized": True,
            "source": "session",
            **{name: session.get(name) for name in _FINALIZED_ONLY},
        }

    health = read_health(session_path) or {}
    audio = (health.get("workers") or {}).get("audio") or {}
    return {
        "finalized": False,
        "source": "health" if audio else "none",
        "audio_chunks": audio.get("chunks"),
        "audio_seconds": audio.get("recorded_seconds"),
        # Integrity is only ever established by a real scan at finalization.
        "audio_integrity_ok": None,
        "recorder_mode": audio.get("mode"),
        "recorder_isolated": audio.get("isolated"),
        "transcript_segment_count": health.get("transcript_segment_count"),
        "stt_restarts": audio.get("restarts"),
    }


def status_json(session_path: Path | None = None) -> dict[str, Any]:
    active = read_active_session(clean_stale=True)
    if session_path is None:
        session_path = (
            Path(active.session_path) if active is not None else latest_session_path()
        )
    if session_path is None:
        return {"active": False, "session": None}

    recorder = read_recorder_state(session_path)
    integrity = scan_audio_dir(
        session_path / "audio",
        recording=bool(recorder and recorder.get("status") == "recording"),
    )
    return {
        "active": active is not None,
        "session_path": str(session_path),
        "session": _load_json(session_path / "session.json"),
        # Resolved counts, so a consumer never has to guess whether the raw
        # session.json numbers are measurements or placeholders.
        "metrics": session_metrics(session_path),
        "health": read_health(session_path),
        "recorder": recorder,
        "audio_integrity": integrity.as_dict(),
        "postprocess": read_postprocess_status(session_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nova-class-status")
    parser.add_argument("--session", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    session = Path(args.session) if args.session else None
    if args.json:
        print(json.dumps(status_json(session), ensure_ascii=False, indent=2))
    else:
        print(render_status(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
