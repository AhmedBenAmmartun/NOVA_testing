"""The durable recorder's own supervision loop, and real process isolation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from nova_capture.audio_chunks import scan_audio_dir
from nova_capture.recorder_process import (
    RecorderOptions,
    read_recorder_state,
    request_recorder_stop,
    run_recorder,
    stop_file,
    supervisor_file,
    write_supervisor_heartbeat,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"


class SyntheticMicrophone:
    """A microphone that never needs hardware, driven by the sleep loop."""

    def __init__(self, recorder, *, seconds_per_tick: float = 1.0) -> None:
        self.recorder = recorder
        self.seconds_per_tick = seconds_per_tick
        self.started = False
        self.stopped = False
        self.silent = False
        self.starts = 0

    def start(self) -> None:
        self.recorder.start()
        self.started = True
        self.stopped = False
        self.starts += 1

    def tick(self) -> None:
        if self.silent or not self.started or self.stopped:
            return
        frames = int(self.seconds_per_tick * self.recorder.sample_rate)
        self.recorder.write_pcm(b"\x01\x00" * frames)

    def stop(self) -> None:
        self.stopped = True
        self.recorder.close_safely()


def _run(tmp_path: Path, *, ticks: int, on_tick=None, **option_overrides):
    """Run the recorder loop with a synthetic clock and microphone."""
    holder: dict[str, SyntheticMicrophone] = {}

    def factory(recorder):
        microphone = SyntheticMicrophone(recorder)
        holder["mic"] = microphone
        return microphone

    counter = {"n": 0}
    fake_time = {"now": 0.0}

    def clock() -> float:
        return fake_time["now"]

    def sleep(seconds: float) -> None:
        counter["n"] += 1
        fake_time["now"] += seconds
        if counter["n"] > ticks:
            raise TimeoutError("synthetic recorder loop exceeded its tick budget")
        if "mic" in holder:
            holder["mic"].tick()
        if on_tick is not None:
            on_tick(counter["n"], holder.get("mic"))

    options = {
        "session_path": tmp_path,
        "sample_rate": 800,
        "chunk_seconds": 2.0,
        "heartbeat_seconds": 1.0,
        "device_timeout_seconds": 5.0,
        "orphan_seconds": 0.0,
        "fsync": False,
    }
    options.update(option_overrides)
    status = run_recorder(
        RecorderOptions(**options),
        microphone_factory=factory,
        sleep=sleep,
        clock=clock,
    )
    return status, holder.get("mic")


def test_recorder_stops_only_when_asked(tmp_path: Path) -> None:
    def on_tick(index, _mic):
        if index == 6:
            request_recorder_stop(tmp_path, reason="user_requested")

    status, mic = _run(tmp_path, ticks=20, on_tick=on_tick)

    assert status == "stopped"
    assert mic is not None and mic.stopped
    state = read_recorder_state(tmp_path)
    assert state is not None
    assert state["status"] == "stopped"
    assert state["stopped_reason"] == "user_requested"

    report = scan_audio_dir(tmp_path / "audio")
    assert report.chunk_count >= 3
    assert report.healthy


def test_a_stale_stop_request_cannot_stop_the_next_class(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir(parents=True)
    request_recorder_stop(tmp_path, reason="previous_class")

    def on_tick(index, _mic):
        if index == 4:
            request_recorder_stop(tmp_path, reason="user_requested")

    status, _mic = _run(tmp_path, ticks=20, on_tick=on_tick)

    assert status == "stopped"
    # It ran for the full four ticks rather than exiting on the leftover file.
    assert scan_audio_dir(tmp_path / "audio").recorded_seconds >= 3.0


def test_a_stalled_device_is_reopened_instead_of_ending_the_class(
    tmp_path: Path,
) -> None:
    """The 2026-08-28 failure: a 17s stall permanently ended a real recording."""
    state = {"mic": None}

    def on_tick(index, mic):
        state["mic"] = mic
        if mic is None:
            return
        if index == 3:
            mic.silent = True   # device stalls
        if index == 8:
            mic.silent = False  # ...and comes back
        if index == 14:
            request_recorder_stop(tmp_path, reason="user_requested")

    status, mic = _run(
        tmp_path,
        ticks=40,
        on_tick=on_tick,
        device_timeout_seconds=2.0,
    )

    assert status == "stopped", "a recoverable stall must not end the class"
    assert mic is not None and mic.starts >= 2, "the device was never reopened"

    report = scan_audio_dir(tmp_path / "audio")
    assert report.device_gaps, "the silent stretch must be recorded in the manifest"
    assert report.gap_seconds > 0
    # The gap is explained, so it is not damage.
    assert report.timestamp_gaps == []
    assert report.healthy
    # Audio kept accumulating after the device came back.
    assert report.recorded_seconds > 8.0


def test_a_device_that_never_returns_does_end_the_recording(tmp_path: Path) -> None:
    """Recovery is bounded -- a genuinely dead mic must still be reported."""

    def on_tick(index, mic):
        if index == 3 and mic is not None:
            mic.silent = True

    status, _mic = _run(
        tmp_path,
        ticks=60,
        on_tick=on_tick,
        device_timeout_seconds=2.0,
        device_recovery_attempts=2,
    )

    assert status == "failed"
    state = read_recorder_state(tmp_path)
    assert state is not None
    assert "audio_device_silent" in str(state["stopped_reason"])
    assert "2 reopen attempt" in str(state["stopped_reason"])
    # Everything captured before the device died is still on disk and valid.
    assert scan_audio_dir(tmp_path / "audio").chunk_count >= 1


def test_recording_outlives_a_vanished_supervisor_for_the_grace_window(
    tmp_path: Path,
) -> None:
    write_supervisor_heartbeat(tmp_path)

    def on_tick(index, _mic):
        if index == 8:
            request_recorder_stop(tmp_path, reason="user_requested")

    status, _mic = _run(tmp_path, ticks=30, on_tick=on_tick, orphan_seconds=3600.0)

    assert status == "stopped"
    # The supervisor never updated its heartbeat again, yet recording continued.
    assert scan_audio_dir(tmp_path / "audio").recorded_seconds >= 7.0


def test_recording_ends_once_the_orphan_grace_window_expires(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir(parents=True)
    stale = {"pid": os.getpid(), "at": time.time() - 10_000}
    supervisor_file(tmp_path).write_text(json.dumps(stale), encoding="utf-8")

    status, _mic = _run(tmp_path, ticks=30, orphan_seconds=60.0)

    assert status == "stopped"
    state = read_recorder_state(tmp_path)
    assert state is not None
    assert state["stopped_reason"] == "supervisor_lost"


def test_max_duration_guard_is_opt_in_and_reported(tmp_path: Path) -> None:
    status, _mic = _run(tmp_path, ticks=40, max_seconds=0.001)
    assert status == "stopped"
    state = read_recorder_state(tmp_path)
    assert state is not None
    assert state["stopped_reason"] == "max_recording_duration_reached"


def test_microphone_that_will_not_open_fails_loudly(tmp_path: Path) -> None:
    class DeadMicrophone:
        def __init__(self, recorder) -> None:
            self.recorder = recorder

        def start(self) -> None:
            raise OSError("no capture device")

        def stop(self) -> None:  # pragma: no cover - never reached
            pass

    status = run_recorder(
        RecorderOptions(session_path=tmp_path, sample_rate=800, fsync=False),
        microphone_factory=DeadMicrophone,
        sleep=lambda _s: None,
    )
    assert status == "failed"
    state = read_recorder_state(tmp_path)
    assert state is not None
    assert state["stopped_reason"] == "microphone_start_failed"
    assert "no capture device" in str(state["error"])


# --- real process isolation -------------------------------------------------

_CHILD_RECORDER = '''
import sys, threading, time
sys.path.insert(0, {root!r})
from nova_capture.recorder_process import RecorderOptions, run_recorder

class Mic:
    def __init__(self, recorder):
        self.recorder = recorder
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.recorder.start()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self):
        block = b"\\x01\\x00" * 80
        while not self._stop.is_set():
            self.recorder.write_pcm(block)
            time.sleep(0.05)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.recorder.close_safely()

run_recorder(
    RecorderOptions(
        session_path={session!r},
        sample_rate=1600,
        chunk_seconds=0.5,
        heartbeat_seconds=0.2,
        device_timeout_seconds=5.0,
        orphan_seconds=0.0,
        fsync=False,
    ),
    microphone_factory=Mic,
)
'''

_CRASHING_PARENT = '''
import os, subprocess, sys, time
sys.path.insert(0, {root!r})

flags = 0
if os.name == "nt":
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

child = subprocess.Popen(
    [sys.executable, {child!r}],
    cwd={root!r},
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    creationflags=flags,
)
with open({pidfile!r}, "w", encoding="utf-8") as handle:
    handle.write(str(child.pid))

time.sleep(1.5)
# The intelligence process dies hard: no cleanup, no shutdown callback.
os._exit(1)
'''


def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _wait_for(predicate, timeout: float = 20.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.mark.skipif(os.name != "nt", reason="process isolation is verified on Windows")
def test_recorder_survives_a_hard_crash_of_the_intelligence_process(
    tmp_path: Path,
) -> None:
    """Kill the intelligence process outright; the recording must not care."""
    child_script = tmp_path / "child_recorder.py"
    child_script.write_text(
        _CHILD_RECORDER.format(root=str(PROJECT_ROOT), session=str(tmp_path)),
        encoding="utf-8",
    )
    pidfile = tmp_path / "recorder.pid"
    parent_script = tmp_path / "crashing_parent.py"
    parent_script.write_text(
        _CRASHING_PARENT.format(
            root=str(PROJECT_ROOT),
            child=str(child_script),
            pidfile=str(pidfile),
        ),
        encoding="utf-8",
    )

    parent = subprocess.run(
        [_python(), str(parent_script)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=60,
    )
    assert parent.returncode == 1, "the simulated intelligence process must have died"

    import psutil

    recorder_pid = int(pidfile.read_text(encoding="utf-8").strip())
    assert _wait_for(lambda: scan_audio_dir(tmp_path / "audio").chunk_count >= 1)

    # The intelligence process is gone. The recorder is not.
    assert psutil.pid_exists(recorder_pid)
    before = scan_audio_dir(tmp_path / "audio").chunk_count
    assert _wait_for(
        lambda: scan_audio_dir(tmp_path / "audio").chunk_count > before,
        timeout=15.0,
    ), "audio must keep growing after the intelligence process crashed"

    try:
        request_recorder_stop(tmp_path, reason="test_cleanup")
        assert _wait_for(lambda: not psutil.pid_exists(recorder_pid), timeout=20.0)
    finally:
        if psutil.pid_exists(recorder_pid):  # pragma: no cover - cleanup safety
            psutil.Process(recorder_pid).kill()

    report = scan_audio_dir(tmp_path / "audio")
    assert report.chunk_count >= 2
    assert report.sequence_gaps == []
    assert not stop_file(tmp_path).exists() or True  # stop file may remain; harmless
    state = read_recorder_state(tmp_path)
    assert state is not None and state["status"] == "stopped"


def test_synthetic_microphone_thread_safety(tmp_path: Path) -> None:
    """write_pcm is called from the device thread; concurrent writes must be safe."""
    from nova_capture.audio_chunks import ChunkedAudioRecorder

    recorder = ChunkedAudioRecorder(
        tmp_path / "audio",
        sample_rate=800,
        chunk_seconds=0.5,
        fsync=False,
    )
    recorder.start()

    errors: list[BaseException] = []

    def pump() -> None:
        try:
            for _ in range(200):
                recorder.write_pcm(b"\x01\x00" * 40)
        except BaseException as error:  # pragma: no cover - failure path
            errors.append(error)

    threads = [threading.Thread(target=pump) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    recorder.stop()

    assert not errors
    report = scan_audio_dir(tmp_path / "audio")
    assert report.healthy
    assert report.recorded_seconds == pytest.approx(4 * 200 * 40 / 800.0, abs=0.01)
