from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import psutil

from .storage import default_capture_root


CONTROL_VERSION = 3
DEFAULT_STALE_SECONDS = 45.0


class ActiveClassCaptureError(RuntimeError):
    pass


@dataclass(slots=True)
class ActiveCapture:
    version: int
    session_id: str
    course: str
    session_path: str
    pid: int
    process_created_at: float
    launcher_pid: int
    launcher_created_at: float
    started_at: str
    heartbeat_at: str

    @classmethod
    def from_dict(cls, payload: dict) -> "ActiveCapture":
        return cls(
            version=int(payload.get("version", CONTROL_VERSION)),
            session_id=str(payload["session_id"]),
            course=str(payload["course"]),
            session_path=str(payload["session_path"]),
            pid=int(payload["pid"]),
            process_created_at=float(payload["process_created_at"]),
            launcher_pid=int(payload.get("launcher_pid", payload["pid"])),
            launcher_created_at=float(
                payload.get("launcher_created_at", payload["process_created_at"])
            ),
            started_at=str(payload["started_at"]),
            heartbeat_at=str(payload.get("heartbeat_at", payload["started_at"])),
        )

    def as_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def control_root() -> Path:
    """Control/lock directory, always beside the active capture root."""
    root = default_capture_root() / "_control"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def active_state_path() -> Path:
    return control_root() / "active.json"


def active_lock_path() -> Path:
    return control_root() / "active.lock"


def stop_request_path() -> Path:
    return control_root() / "stop.request.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def clear_stop_request() -> None:
    _safe_unlink(stop_request_path())
    _safe_unlink(stop_request_path().with_suffix(".json.tmp"))


def _same_process(pid: int, created_at: float) -> bool:
    try:
        process = psutil.Process(int(pid))
        return abs(float(process.create_time()) - float(created_at)) < 2.0
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False


def _process_created_at(process: psutil.Process) -> float:
    try:
        return float(process.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0


def _discover_launcher_process() -> psutil.Process:
    current = psutil.Process(os.getpid())
    candidates = [current]
    try:
        candidates.extend(current.parents())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    matches: list[psutil.Process] = []
    for process in candidates:
        try:
            name = process.name().casefold()
            command = " ".join(process.cmdline()).replace("\\", "/").casefold()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "python" in name and "class_capture.py" in command and "console" in command:
            matches.append(process)

    # Prefer the outermost matching Python process. In the legacy LiveKit console
    # the class job may run in a child/thread while the outer Python process owns
    # the terminal UI.
    return matches[-1] if matches else current


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _heartbeat_is_fresh(state: ActiveCapture, stale_seconds: float) -> bool:
    heartbeat = _parse_iso(state.heartbeat_at)
    if heartbeat is None:
        return False
    age = (datetime.now(timezone.utc) - heartbeat).total_seconds()
    return age <= max(5.0, float(stale_seconds))


def _cleanup_control_files() -> None:
    _safe_unlink(active_state_path())
    _safe_unlink(active_lock_path())
    clear_stop_request()


def read_active_session(
    *,
    clean_stale: bool = True,
    stale_seconds: float = DEFAULT_STALE_SECONDS,
) -> ActiveCapture | None:
    path = active_state_path()
    if not path.exists():
        if clean_stale and active_lock_path().exists():
            # A lock without state is only safe to remove when its owner is gone.
            try:
                payload = json.loads(active_lock_path().read_text(encoding="utf-8"))
                owner_alive = _same_process(
                    int(payload.get("pid", -1)),
                    float(payload.get("process_created_at", -1)),
                )
            except Exception:
                owner_alive = False
            if not owner_alive:
                _cleanup_control_files()
        return None

    try:
        state = ActiveCapture.from_dict(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception:
        if clean_stale:
            _cleanup_control_files()
        return None

    owner_alive = _same_process(state.pid, state.process_created_at)
    heartbeat_fresh = _heartbeat_is_fresh(state, stale_seconds)
    if owner_alive and heartbeat_fresh:
        return state

    if clean_stale:
        _cleanup_control_files()
    return None


def _create_lock_exclusive(pid: int, created_at: float) -> None:
    path = active_lock_path()
    payload = {
        "pid": pid,
        "process_created_at": created_at,
        "created_at": _now_iso(),
    }
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for _ in range(2):
        try:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            )
        except FileExistsError:
            active = read_active_session(clean_stale=True)
            if active is not None:
                raise ActiveClassCaptureError(
                    f"A class capture is already active for {active.course} "
                    f"(session {active.session_id})."
                )
            # read_active_session() removes a stale orphaned lock.
            continue
        else:
            try:
                os.write(descriptor, encoded)
            finally:
                os.close(descriptor)
            return

    raise ActiveClassCaptureError(
        "Class Capture could not acquire its lifecycle lock. "
        "Run `python -m nova_capture.control status` and retry."
    )


def claim_active_session(
    *,
    session_id: str,
    course: str,
    session_path: str | Path,
) -> ActiveCapture:
    existing = read_active_session(clean_stale=True)
    if existing is not None:
        raise ActiveClassCaptureError(
            f"A class capture is already active for {existing.course} "
            f"(session {existing.session_id})."
        )

    current = psutil.Process(os.getpid())
    current_created = _process_created_at(current)
    launcher = _discover_launcher_process()
    launcher_created = _process_created_at(launcher)

    _create_lock_exclusive(current.pid, current_created)
    clear_stop_request()

    now = _now_iso()
    state = ActiveCapture(
        version=CONTROL_VERSION,
        session_id=session_id,
        course=course,
        session_path=str(Path(session_path).expanduser().resolve()),
        pid=current.pid,
        process_created_at=current_created,
        launcher_pid=launcher.pid,
        launcher_created_at=launcher_created,
        started_at=now,
        heartbeat_at=now,
    )

    try:
        _atomic_write_json(active_state_path(), state.as_dict())
    except Exception:
        _cleanup_control_files()
        raise

    return state


def heartbeat_active_session(session_id: str) -> bool:
    state = read_active_session(clean_stale=False)
    if state is None or state.session_id != session_id:
        return False
    state.heartbeat_at = _now_iso()
    _atomic_write_json(active_state_path(), state.as_dict())
    return True


def release_active_session(session_id: str) -> bool:
    state = read_active_session(clean_stale=False)
    if state is not None and state.session_id != session_id:
        return False
    _safe_unlink(active_state_path())
    _safe_unlink(active_lock_path())

    try:
        payload = json.loads(stop_request_path().read_text(encoding="utf-8"))
        if payload.get("target_session_id") == session_id:
            clear_stop_request()
    except FileNotFoundError:
        pass
    except Exception:
        clear_stop_request()
    return True


def request_stop() -> ActiveCapture | None:
    active = read_active_session(clean_stale=True)
    if active is None:
        clear_stop_request()
        return None

    payload = {
        "version": CONTROL_VERSION,
        "requested_at": _now_iso(),
        "reason": "user_requested",
        "target_session_id": active.session_id,
    }
    _atomic_write_json(stop_request_path(), payload)
    return active


async def wait_for_stop_request(
    session_id: str,
    *,
    poll_seconds: float = 0.20,
) -> dict:
    path = stop_request_path()
    while True:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                clear_stop_request()
                await asyncio.sleep(max(0.05, float(poll_seconds)))
                continue

            target = payload.get("target_session_id")
            if target == session_id:
                clear_stop_request()
                return payload

            # A request for a different/old session must never stop this class.
            clear_stop_request()

        await asyncio.sleep(max(0.05, float(poll_seconds)))


def wait_until_inactive(
    session_id: str,
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.20,
) -> bool:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    while time.monotonic() < deadline:
        active = read_active_session(clean_stale=True)
        if active is None or active.session_id != session_id:
            return True
        time.sleep(max(0.05, float(poll_seconds)))
    return False


def _is_capture_console_process(process: psutil.Process) -> bool:
    try:
        name = process.name().casefold()
        command = " ".join(process.cmdline()).replace("\\", "/").casefold()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return (
        "python" in name
        and "class_capture.py" in command
        and "console" in command
    )


def _capture_console_tree(
    launcher_pid: int,
    *,
    launcher_created_at: float | None = None,
) -> list[psutil.Process]:
    if launcher_created_at is not None and not _same_process(
        launcher_pid,
        launcher_created_at,
    ):
        return []

    try:
        launcher = psutil.Process(int(launcher_pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return []

    if not _is_capture_console_process(launcher):
        return []

    matching: list[psutil.Process] = []
    try:
        descendants = launcher.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        descendants = []

    # Only stop descendants that are themselves Class Capture console
    # processes. Post-processing or other unrelated children must survive.
    for process in descendants:
        if _is_capture_console_process(process):
            matching.append(process)

    matching.append(launcher)
    return matching


def close_capture_launcher_tree(
    launcher_pid: int,
    *,
    launcher_created_at: float | None = None,
    grace_seconds: float = 0.0,
    wait_seconds: float = 5.0,
) -> str:
    time.sleep(max(0.0, float(grace_seconds)))

    processes = _capture_console_tree(
        launcher_pid,
        launcher_created_at=launcher_created_at,
    )
    if not processes:
        return "launcher already exited or could not be safely identified"

    # Descendants are listed before the outer launcher, so the LiveKit worker
    # is asked to exit before its console owner.
    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _gone, alive = psutil.wait_procs(
        processes,
        timeout=max(0.1, float(wait_seconds)),
    )

    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    if alive:
        _gone_after_kill, still_alive = psutil.wait_procs(
            alive,
            timeout=max(0.1, float(wait_seconds)),
        )
    else:
        still_alive = []

    if still_alive:
        pids = ", ".join(str(process.pid) for process in still_alive)
        return f"class saved, but capture process(es) remain: {pids}"

    return f"class capture process tree closed ({len(processes)} process(es))"


def close_legacy_launcher_after_save(
    state: ActiveCapture,
    *,
    grace_seconds: float = 1.0,
) -> str:
    # active.json is removed only after transcript/audio/session finalization.
    # Close every matching Class Capture console process in the launcher's tree,
    # but preserve unrelated descendants such as post-processing workers.
    return close_capture_launcher_tree(
        state.launcher_pid,
        launcher_created_at=state.launcher_created_at,
        grace_seconds=grace_seconds,
    )


def status_payload() -> dict:
    state = read_active_session(clean_stale=True)
    if state is None:
        return {"active": False}
    return {"active": True, **state.as_dict()}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova-class-control")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")

    commands.add_parser("clear")
    commands.add_parser("guard-start")

    stop = commands.add_parser("stop")
    stop.add_argument("--wait", action="store_true")
    stop.add_argument("--timeout", type=float, default=30.0)
    stop.add_argument("--close-launcher", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    if args.command == "clear":
        _cleanup_control_files()
        print("NOVA Class Capture control state cleared.")
        return 0

    if args.command == "status":
        payload = status_payload()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return 0

        if not payload["active"]:
            print("No active NOVA class session.")
            return 0

        print(f"ACTIVE: {payload['course']}")
        print(f"Session: {payload['session_id']}")
        print(f"Started: {payload['started_at']}")
        print(f"Path: {payload['session_path']}")
        return 0

    if args.command == "guard-start":
        active = read_active_session(clean_stale=True)
        if active is None:
            print("Class Capture lifecycle check: READY")
            return 0
        print(
            f"Class Capture is already active for {active.course} "
            f"(session {active.session_id})."
        )
        print("Use Stop-NOVA-Class.ps1 before starting another class.")
        return 3

    if args.command == "stop":
        active = request_stop()
        if active is None:
            print("No active NOVA class session.")
            return 0

        print("NOVA Class Capture stop requested.")
        print(f"Course: {active.course}")
        print(f"Session: {active.session_id}")

        if not args.wait:
            return 0

        print("Waiting for transcript/audio finalization...")
        if not wait_until_inactive(
            active.session_id,
            timeout_seconds=args.timeout,
        ):
            print(
                "Timed out waiting for Class Capture to finish. "
                "The stop signal was sent; do not start another class yet."
            )
            return 4

        print("Class Capture finalized.")

        if args.close_launcher:
            print(close_legacy_launcher_after_save(active))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
