"""The durable class recorder, and the process boundary that protects it.

This module is both halves of NOVA's audio guarantee:

* run as ``python -m nova_capture.recorder_process --session <path>`` it *is*
  the recorder -- it owns the microphone, writes chunked WAV files, and knows
  nothing about STT, LLM providers, notes, or LiveKit;
* imported, it gives the Class Capture supervisor a handle
  (:class:`DurableRecorderProcess`) that can start, watch, and stop that
  separate process.

The separation is the whole point. On 2026-08-27 the microphone lived inside
the same asyncio process as the LiveKit AgentSession, so anything that ended
that session also closed ``audio.wav``. A crash, an unrecoverable STT error, or
a job shutdown in the intelligence process now cannot reach the recorder: it is
a different OS process, and it stops only when it is explicitly told to, when
the audio device dies, or when its supervisor has been gone long enough that
continuing would just be holding the microphone hostage.

:class:`InlineDurableRecorder` is the honest fallback for machines where a
second process cannot open the input device. It gives the identical chunked,
manifest-backed storage but *no* process isolation, and it says so in its
health payload rather than pretending otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_chunks import (
    DEFAULT_CHUNK_SECONDS,
    RECORDER_STATE_NAME,
    ChunkedAudioRecorder,
    atomic_write_json,
)
from .microphone import LocalMicrophoneCapture


STOP_FILE_NAME = "recorder.stop"
SUPERVISOR_FILE_NAME = "supervisor.json"

#: How long the recorder tolerates zero audio callbacks before treating the
#: capture device as stalled. Raised from 15s on 2026-08-28: a real CEN4934
#: class lost 33.7 minutes because a 17-second stall (network drop + a CPU
#: saturated by local inference) was read as permanent device death.
DEFAULT_DEVICE_TIMEOUT_SECONDS = 25.0

#: How many times a stalled device is reopened before the recording really is
#: declared dead. A stall is now recoverable; only a device that will not come
#: back ends the recording.
DEFAULT_DEVICE_RECOVERY_ATTEMPTS = 5

#: How long the recording outlives a vanished supervisor. Long enough that the
#: intelligence process can crash and be restarted without losing the class,
#: short enough that a forgotten orphan does not hold the microphone all day.
DEFAULT_ORPHAN_SECONDS = 3600.0


def audio_dir_for(session_path: Path) -> Path:
    return Path(session_path) / "audio"


def stop_file(session_path: Path) -> Path:
    return audio_dir_for(session_path) / STOP_FILE_NAME


def supervisor_file(session_path: Path) -> Path:
    return audio_dir_for(session_path) / SUPERVISOR_FILE_NAME


def request_recorder_stop(session_path: Path, *, reason: str = "user_requested") -> Path:
    """Ask the durable recorder to finalize. Safe to call more than once."""
    path = stop_file(session_path)
    atomic_write_json(
        path,
        {
            "reason": reason,
            "requested_at": time.time(),
            "requested_by_pid": os.getpid(),
        },
    )
    return path


def write_supervisor_heartbeat(session_path: Path, *, pid: int | None = None) -> None:
    atomic_write_json(
        supervisor_file(session_path),
        {"pid": int(pid if pid is not None else os.getpid()), "at": time.time()},
    )


def read_recorder_state(session_path: Path) -> dict[str, Any] | None:
    path = audio_dir_for(session_path) / RECORDER_STATE_NAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


# --- the recorder itself ---------------------------------------------------


@dataclass(slots=True)
class RecorderOptions:
    session_path: Path
    sample_rate: int = 16_000
    channels: int = 1
    sample_width: int = 2
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS
    heartbeat_seconds: float = 2.0
    device_timeout_seconds: float = DEFAULT_DEVICE_TIMEOUT_SECONDS
    device_recovery_attempts: int = DEFAULT_DEVICE_RECOVERY_ATTEMPTS
    orphan_seconds: float = DEFAULT_ORPHAN_SECONDS
    max_seconds: float = 0.0
    fsync: bool = True


def run_recorder(
    options: RecorderOptions,
    *,
    microphone_factory=None,
    sleep=time.sleep,
    clock=time.monotonic,
) -> str:
    """Record until explicitly stopped. Returns the final recorder status.

    ``microphone_factory`` exists so the supervision loop -- stop files,
    device-death detection, orphan handling, heartbeats -- can be tested
    without microphone hardware.
    """

    session_path = Path(options.session_path)
    audio_dir = audio_dir_for(session_path)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # A stop request left over from a previous sitting must never stop this one.
    stop_file(session_path).unlink(missing_ok=True)

    recorder = ChunkedAudioRecorder(
        audio_dir,
        sample_rate=options.sample_rate,
        channels=options.channels,
        sample_width=options.sample_width,
        chunk_seconds=options.chunk_seconds,
        fsync=options.fsync,
        clock=clock,
    )

    if microphone_factory is None:
        microphone = LocalMicrophoneCapture(recorder)
    else:
        microphone = microphone_factory(recorder)

    stopping = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame) -> None:
        stopping["flag"] = True
        stopping["reason"] = f"signal_{signum}"

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        handler = getattr(signal, name, None)
        if handler is not None:
            try:
                signal.signal(handler, _handle_signal)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    try:
        microphone.start()
    except Exception as error:
        recorder.write_state(
            status="failed",
            error=f"{type(error).__name__}: {error}",
            stopped_reason="microphone_start_failed",
        )
        return "failed"

    recorder.write_state(status="recording", stopped_reason=None)

    started = clock()
    last_supervisor_seen = clock()
    recovery_attempts = 0
    status = "stopped"
    stopped_reason = "stop_requested"

    try:
        while True:
            sleep(max(0.05, float(options.heartbeat_seconds)))

            if stopping["flag"]:
                stopped_reason = stopping["reason"] or "signal"
                break

            if stop_file(session_path).exists():
                stopped_reason = _stop_reason(session_path)
                break

            age = recorder.last_write_age_seconds
            if age is not None and age > options.device_timeout_seconds:
                # A stall is not death. Close the stream, record the silent
                # stretch in the manifest so the timeline stays honest, and
                # reopen the device. Only give up once reopening keeps failing.
                if recovery_attempts < options.device_recovery_attempts:
                    recovery_attempts += 1
                    recorder.write_state(
                        status="recovering",
                        stopped_reason=None,
                        recovery_attempt=recovery_attempts,
                        detail=f"device silent for {age:.0f}s; reopening",
                    )
                    try:
                        microphone.stop()
                    except Exception:  # pragma: no cover - teardown best effort
                        pass
                    recorder.note_gap(age, reason=f"audio_device_stall_{age:.0f}s")
                    try:
                        microphone.start()
                    except Exception as error:
                        status = "failed"
                        stopped_reason = (
                            f"audio_device_reopen_failed on attempt "
                            f"{recovery_attempts}: {type(error).__name__}: {error}"
                        )
                        break
                    recorder.write_state(
                        status="recording",
                        recovery_attempt=recovery_attempts,
                        detail="device reopened; recording resumed",
                    )
                    continue

                status = "failed"
                stopped_reason = (
                    f"audio_device_silent_for_{age:.0f}s after "
                    f"{recovery_attempts} reopen attempt(s) "
                    "(unrecoverable capture device failure)"
                )
                break

            if options.max_seconds > 0 and (clock() - started) > options.max_seconds:
                stopped_reason = "max_recording_duration_reached"
                break

            supervisor_age = _supervisor_age(session_path)
            if supervisor_age is None or supervisor_age < options.orphan_seconds:
                if supervisor_age is not None:
                    last_supervisor_seen = clock()
                orphaned = False
            else:
                orphaned = True

            if orphaned and options.orphan_seconds > 0:
                status = "stopped"
                stopped_reason = "supervisor_lost"
                break

            recorder.write_state(
                status="recording",
                recovery_attempts=recovery_attempts,
                supervisor_age_seconds=supervisor_age,
                orphan_grace_remaining_seconds=(
                    None
                    if options.orphan_seconds <= 0
                    else round(
                        max(
                            0.0,
                            options.orphan_seconds - (clock() - last_supervisor_seen),
                        ),
                        1,
                    )
                ),
            )
    finally:
        teardown_error: str | None = None
        try:
            microphone.stop()
        except Exception as error:  # pragma: no cover - device teardown
            teardown_error = f"{type(error).__name__}: {error}"
            recorder.close_safely()
        recorder.write_state(
            status=status,
            error=teardown_error,
            stopped_reason=stopped_reason,
        )

    return status


def _stop_reason(session_path: Path) -> str:
    try:
        payload = json.loads(stop_file(session_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "stop_requested"
    return str(payload.get("reason") or "stop_requested")


def _supervisor_age(session_path: Path) -> float | None:
    try:
        payload = json.loads(supervisor_file(session_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return max(0.0, time.time() - float(payload["at"]))
    except (KeyError, TypeError, ValueError):
        return None


# --- parent-side handles ---------------------------------------------------


class InlineDurableRecorder:
    """Chunked durable recording inside the intelligence process.

    Storage durability is identical to the separate-process recorder; process
    isolation is not. ``isolated`` is False so status output and the final
    report can state plainly which guarantee is in force.
    """

    isolated = False
    mode = "inline"

    def __init__(
        self,
        session_path: Path,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
        fsync: bool = True,
        microphone_factory=None,
    ) -> None:
        self.session_path = Path(session_path)
        self.recorder = ChunkedAudioRecorder(
            audio_dir_for(self.session_path),
            sample_rate=sample_rate,
            channels=channels,
            chunk_seconds=chunk_seconds,
            fsync=fsync,
        )
        factory = microphone_factory or LocalMicrophoneCapture
        self.microphone = factory(self.recorder)
        self.error: str | None = None

    @property
    def active(self) -> bool:
        return bool(self.recorder.active)

    def start(self) -> bool:
        try:
            self.microphone.start()
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            self.recorder.write_state(status="failed", error=self.error)
            return False
        self.recorder.write_state(status="recording")
        return True

    def health(self) -> dict[str, Any]:
        payload = self.recorder.state(
            status="recording" if self.recorder.active else "stopped"
        )
        payload["mode"] = self.mode
        payload["isolated"] = self.isolated
        if self.error:
            payload["error"] = self.error
        self.recorder.write_state(status=payload["status"], mode=self.mode)
        return payload

    def stop(self, *, reason: str = "user_requested") -> dict[str, Any]:
        try:
            self.microphone.stop()
        except Exception as error:  # pragma: no cover - device teardown
            self.error = f"{type(error).__name__}: {error}"
            self.recorder.close_safely()
        payload = self.recorder.state(status="stopped")
        payload["mode"] = self.mode
        payload["isolated"] = self.isolated
        payload["stopped_reason"] = reason
        self.recorder.write_state(
            status="stopped", mode=self.mode, stopped_reason=reason
        )
        return payload


class DurableRecorderProcess:
    """Handle to the recorder running as its own OS process."""

    isolated = True
    mode = "process"

    def __init__(
        self,
        session_path: Path,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
        orphan_seconds: float = DEFAULT_ORPHAN_SECONDS,
        max_seconds: float = 0.0,
        python_executable: str | None = None,
        startup_timeout_seconds: float = 12.0,
    ) -> None:
        self.session_path = Path(session_path)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_seconds = float(chunk_seconds)
        self.orphan_seconds = float(orphan_seconds)
        self.max_seconds = float(max_seconds)
        self.python_executable = python_executable or sys.executable
        self.startup_timeout_seconds = max(2.0, float(startup_timeout_seconds))
        self.process: subprocess.Popen | None = None
        self.error: str | None = None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> bool:
        audio_dir_for(self.session_path).mkdir(parents=True, exist_ok=True)
        write_supervisor_heartbeat(self.session_path)
        stop_file(self.session_path).unlink(missing_ok=True)

        command = [
            self.python_executable,
            "-m",
            "nova_capture.recorder_process",
            "--session",
            str(self.session_path),
            "--sample-rate",
            str(self.sample_rate),
            "--channels",
            str(self.channels),
            "--chunk-seconds",
            str(self.chunk_seconds),
            "--orphan-seconds",
            str(self.orphan_seconds),
            "--max-seconds",
            str(self.max_seconds),
        ]
        kwargs: dict[str, Any] = {
            "cwd": str(Path(__file__).resolve().parents[1]),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            # A new process group keeps the recorder from inheriting the
            # console Ctrl+C / Ctrl+Break that ends the intelligence process.
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        try:
            self.process = subprocess.Popen(command, **kwargs)
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            return False

        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            state = read_recorder_state(self.session_path)
            if state is not None and state.get("status") == "recording":
                return True
            if state is not None and state.get("status") == "failed":
                self.error = str(state.get("error") or "recorder reported failure")
                return False
            if not self.alive:
                self.error = "recorder process exited during startup"
                return False
            time.sleep(0.2)

        self.error = "recorder process did not report healthy in time"
        return False

    def health(self) -> dict[str, Any]:
        write_supervisor_heartbeat(self.session_path)
        state = read_recorder_state(self.session_path) or {}
        payload = dict(state)
        payload["mode"] = self.mode
        payload["isolated"] = self.isolated
        payload["process_alive"] = self.alive
        payload["recorder_pid"] = self.pid
        if self.error and "error" not in payload:
            payload["error"] = self.error
        if not self.alive and payload.get("status") == "recording":
            payload["status"] = "failed"
            payload["error"] = "recorder process exited without finalizing"
        return payload

    def stop(
        self,
        *,
        reason: str = "user_requested",
        timeout_seconds: float = 20.0,
    ) -> dict[str, Any]:
        request_recorder_stop(self.session_path, reason=reason)
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if not self.alive:
                break
            state = read_recorder_state(self.session_path)
            if state is not None and state.get("status") in {"stopped", "failed"}:
                break
            time.sleep(0.2)

        if self.alive and self.process is not None:
            # The recorder ignored a clean stop. Terminate it rather than leave
            # the microphone held, then report that this happened.
            try:
                self.process.terminate()
                self.process.wait(timeout=5.0)
            except Exception:  # pragma: no cover - platform dependent
                pass
            self.error = "recorder process required termination after stop request"

        payload = self.health()
        payload["stopped_reason"] = reason
        return payload


def create_durable_recorder(
    session_path: Path,
    *,
    mode: str = "process",
    sample_rate: int = 16_000,
    channels: int = 1,
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
    orphan_seconds: float = DEFAULT_ORPHAN_SECONDS,
    max_seconds: float = 0.0,
    microphone_factory=None,
):
    """Start the strongest recorder this machine actually supports.

    ``process`` is tried first and falls back to ``inline`` when a second
    process cannot open the capture device, because a recording without process
    isolation is still infinitely better than no recording.
    """

    if mode == "inline":
        inline = InlineDurableRecorder(
            session_path,
            sample_rate=sample_rate,
            channels=channels,
            chunk_seconds=chunk_seconds,
            microphone_factory=microphone_factory,
        )
        return inline, inline.start(), None

    handle = DurableRecorderProcess(
        session_path,
        sample_rate=sample_rate,
        channels=channels,
        chunk_seconds=chunk_seconds,
        orphan_seconds=orphan_seconds,
        max_seconds=max_seconds,
    )
    if handle.start():
        return handle, True, None

    fallback_reason = handle.error or "recorder process unavailable"
    try:
        handle.stop(reason="fallback_to_inline", timeout_seconds=5.0)
    except Exception:  # pragma: no cover - best effort
        pass

    inline = InlineDurableRecorder(
        session_path,
        sample_rate=sample_rate,
        channels=channels,
        chunk_seconds=chunk_seconds,
        microphone_factory=microphone_factory,
    )
    return inline, inline.start(), fallback_reason


# --- CLI -------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova-class-recorder")
    parser.add_argument("--session", required=True)
    parser.add_argument("--sample-rate", type=int, default=16_000)
    parser.add_argument("--channels", type=int, default=1)
    parser.add_argument("--chunk-seconds", type=float, default=DEFAULT_CHUNK_SECONDS)
    parser.add_argument(
        "--device-timeout-seconds",
        type=float,
        default=DEFAULT_DEVICE_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--device-recovery-attempts",
        type=int,
        default=DEFAULT_DEVICE_RECOVERY_ATTEMPTS,
    )
    parser.add_argument("--orphan-seconds", type=float, default=DEFAULT_ORPHAN_SECONDS)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    status = run_recorder(
        RecorderOptions(
            session_path=Path(args.session),
            sample_rate=args.sample_rate,
            channels=args.channels,
            chunk_seconds=args.chunk_seconds,
            heartbeat_seconds=args.heartbeat_seconds,
            device_timeout_seconds=args.device_timeout_seconds,
            device_recovery_attempts=args.device_recovery_attempts,
            orphan_seconds=args.orphan_seconds,
            max_seconds=args.max_seconds,
        )
    )
    return 0 if status == "stopped" else 1


if __name__ == "__main__":
    raise SystemExit(main())
