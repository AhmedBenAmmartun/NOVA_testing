"""A post-class job that dies must never keep reporting itself as running.

On 2026-08-31 a real COT3400 lecture lost its notes this way. The job was
launched at 13:01:11, the process died without raising, and `postprocess.json`
still read `{"status": "running", "error": null}` eight hours later while the
vault had no session folder at all. Nothing in the evidence said the job was
dead, so the failure was invisible until someone went looking for the notes.

A dying process cannot be relied on to write its own epitaph -- it may be
killed, lose power, or be reaped by the OS. So liveness is resolved by the
READER, exactly as `control.py` already resolves an orphaned recorder: the
status file carries the process identity, and anyone reading it re-checks
whether that identity is still alive.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import psutil
import pytest

from nova_capture.postprocess import (
    postprocess_status_payload,
    read_postprocess_status,
    write_running_status,
)


def _status(session: Path, payload: dict) -> Path:
    session.mkdir(parents=True, exist_ok=True)
    path = session / "postprocess.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_a_running_status_whose_process_is_gone_reports_interrupted(
    tmp_path: Path,
) -> None:
    """The exact COT3400 failure: status says running, the PID is long gone."""
    dead_pid = 999_999
    assert not psutil.pid_exists(dead_pid)
    _status(
        tmp_path,
        {
            "status": "running",
            "error": None,
            "pid": dead_pid,
            "pid_created_at": 1.0,
        },
    )

    resolved = read_postprocess_status(tmp_path)

    assert resolved["status"] == "interrupted"
    assert resolved["recorded_status"] == "running"
    assert resolved["error"]


def test_a_running_status_for_a_live_process_is_still_running(
    tmp_path: Path,
) -> None:
    process = psutil.Process(os.getpid())
    _status(
        tmp_path,
        {
            "status": "running",
            "error": None,
            "pid": os.getpid(),
            "pid_created_at": process.create_time(),
        },
    )

    resolved = read_postprocess_status(tmp_path)

    assert resolved["status"] == "running"
    assert resolved["error"] is None


def test_a_recycled_pid_does_not_count_as_the_original_job(
    tmp_path: Path,
) -> None:
    """A reused PID belongs to a different process, so the job is still dead."""
    _status(
        tmp_path,
        {
            "status": "running",
            "error": None,
            "pid": os.getpid(),
            # This process did not start in 1970; the identity does not match.
            "pid_created_at": 1.0,
        },
    )

    assert read_postprocess_status(tmp_path)["status"] == "interrupted"


@pytest.mark.parametrize("terminal", ["completed", "completed_with_warnings", "failed"])
def test_a_finished_job_is_reported_as_finished(tmp_path: Path, terminal: str) -> None:
    """Liveness only ever reinterprets 'running'. Terminal states are facts."""
    _status(
        tmp_path,
        {"status": terminal, "error": None, "pid": 999_999, "pid_created_at": 1.0},
    )

    assert read_postprocess_status(tmp_path)["status"] == terminal


def test_a_status_without_process_identity_is_not_silently_trusted(
    tmp_path: Path,
) -> None:
    """Older sessions predate the identity fields and must not read as healthy."""
    _status(tmp_path, {"status": "running", "error": None})

    assert read_postprocess_status(tmp_path)["status"] == "interrupted"


def test_a_missing_status_file_is_reported_as_not_started(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)

    assert read_postprocess_status(tmp_path)["status"] == "not_started"


def test_writing_the_running_status_records_this_process(tmp_path: Path) -> None:
    """A manual rerun must claim the job, not inherit the dead launcher's PID.

    The COT3400 status file still carried `pid: 18064` -- the process that died
    hours earlier -- after a rerun had already started, because only the
    subprocess launcher ever wrote the PID.
    """
    _status(
        tmp_path,
        {"status": "running", "error": None, "pid": 18064, "pid_created_at": 1.0},
    )

    write_running_status(tmp_path / "postprocess.json")

    payload = json.loads((tmp_path / "postprocess.json").read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["pid_created_at"] == pytest.approx(
        psutil.Process(os.getpid()).create_time()
    )
    assert read_postprocess_status(tmp_path)["status"] == "running"


def test_the_payload_helper_reports_liveness_without_reading_disk_twice(
    tmp_path: Path,
) -> None:
    payload = {"status": "running", "pid": 999_999, "pid_created_at": 1.0}

    assert postprocess_status_payload(payload)["status"] == "interrupted"


# --- the launcher path -------------------------------------------------------


def test_a_launched_job_whose_process_died_is_also_interrupted(tmp_path: Path) -> None:
    """`launch_postprocess` writes "launched" before the child writes "running".

    If the child dies in between -- an import error, a missing dependency, an
    immediate crash -- nothing ever overwrites that status. "launched" is
    neither terminal nor, originally, liveness-checked, so it would sit there
    forever claiming a job was on its way. Exactly F-001 again, one code path
    over.
    """
    _status(
        tmp_path,
        {
            "status": "launched",
            "error": None,
            "pid": 999_999,
            "pid_created_at": 1.0,
        },
    )

    resolved = read_postprocess_status(tmp_path)

    assert resolved["status"] == "interrupted"
    assert resolved["recorded_status"] == "launched"


def test_a_launched_job_with_a_live_process_is_left_alone(tmp_path: Path) -> None:
    process = psutil.Process(os.getpid())
    _status(
        tmp_path,
        {
            "status": "launched",
            "error": None,
            "pid": os.getpid(),
            "pid_created_at": process.create_time(),
        },
    )

    assert read_postprocess_status(tmp_path)["status"] == "launched"


def test_the_launcher_records_process_identity_not_just_a_pid() -> None:
    """A bare PID cannot prove identity -- the OS recycles them.

    Regression guard on the source: `launch_postprocess` must persist
    `pid_created_at` alongside the pid it reports.
    """
    source = Path("nova_capture/postprocess.py").read_text(encoding="utf-8")
    launch_at = source.index("def launch_postprocess")

    assert "pid_created_at" in source[launch_at:]
