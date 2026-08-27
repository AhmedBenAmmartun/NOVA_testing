from __future__ import annotations

import asyncio
from pathlib import Path

from nova_capture import control


def test_stop_signal_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(control, "control_root", lambda: tmp_path)

    state = control.claim_active_session(
        session_id="session-1",
        course="CEN4065",
        session_path=tmp_path / "session-1",
    )
    assert state.session_id == "session-1"

    active = control.request_stop()
    assert active is not None
    assert control.stop_request_path().exists()

    payload = asyncio.run(
        control.wait_for_stop_request(
            "session-1",
            poll_seconds=0.01,
        )
    )
    assert payload["reason"] == "user_requested"
    assert payload["target_session_id"] == "session-1"
    assert not control.stop_request_path().exists()

    assert control.release_active_session("session-1")


def test_class_capture_uses_clean_stop_signal() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "class_capture.py").read_text(
        encoding="utf-8-sig"
    )

    assert "wait_for_stop_request(capture.session_id)" in source
    assert "live_session.shutdown(drain=True)" in source
    assert 'ctx.shutdown(reason="class capture stop requested")' in source
    assert "Press Ctrl+C to end the class." not in source
    assert "Stop-NOVA-Class.ps1" in source



def test_close_after_save_delegates_to_capture_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(control, "control_root", lambda: tmp_path)

    state = control.claim_active_session(
        session_id="session-tree",
        course="CEN4065",
        session_path=tmp_path / "session-tree",
    )

    calls: list[tuple[int, float | None, float]] = []

    def fake_close(
        launcher_pid: int,
        *,
        launcher_created_at: float | None = None,
        grace_seconds: float = 0.0,
        wait_seconds: float = 5.0,
    ) -> str:
        calls.append((launcher_pid, launcher_created_at, grace_seconds))
        return "class capture process tree closed (2 process(es))"

    monkeypatch.setattr(control, "close_capture_launcher_tree", fake_close)

    result = control.close_legacy_launcher_after_save(
        state,
        grace_seconds=0.0,
    )

    assert calls == [
        (
            state.launcher_pid,
            state.launcher_created_at,
            0.0,
        )
    ]
    assert "process tree closed" in result
    control.release_active_session("session-tree")


def test_capture_console_tree_excludes_unrelated_descendants(monkeypatch) -> None:
    class FakeProcess:
        def __init__(
            self,
            pid: int,
            command: list[str],
            children: list["FakeProcess"] | None = None,
        ) -> None:
            self.pid = pid
            self._command = command
            self._children = children or []

        def name(self) -> str:
            return "python.exe"

        def cmdline(self) -> list[str]:
            return self._command

        def children(self, recursive: bool = False):
            assert recursive is True
            return list(self._children)

    worker = FakeProcess(
        200,
        ["python.exe", "class_capture.py", "console"],
    )
    postprocess = FakeProcess(
        300,
        ["python.exe", "-m", "nova_capture.postprocess"],
    )
    launcher = FakeProcess(
        100,
        ["python.exe", "class_capture.py", "console"],
        [worker, postprocess],
    )

    monkeypatch.setattr(
        control.psutil,
        "Process",
        lambda pid: launcher,
    )

    processes = control._capture_console_tree(100)

    assert [process.pid for process in processes] == [200, 100]
