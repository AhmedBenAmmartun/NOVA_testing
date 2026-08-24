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
