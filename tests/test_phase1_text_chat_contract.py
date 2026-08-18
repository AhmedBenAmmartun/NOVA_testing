"""Static contract for typed chat inside NOVA Vision.

This test opens no camera, microphone, LiveKit room, or network connection.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_text_chat_ui_is_inside_nova_vision() -> None:
    html = text("vision-client/index.html")
    assert 'id="chatPanel"' in html
    assert 'id="chatMessages"' in html
    assert 'id="chatInput"' in html
    assert 'id="sendChatButton"' in html
    assert 'id="speakerButton"' in html
    assert 'maxlength="4000"' in html


def test_frontend_sends_livekit_agent_chat_topic() -> None:
    client = text("vision-client/src/main.js")
    assert ".localParticipant.sendText(text, { topic: 'lk.chat' })" in client
    assert "event.key === 'Enter' && !event.shiftKey" in client
    assert "event.preventDefault()" in client


def test_agent_keeps_livekit_text_io_enabled_by_default() -> None:
    agent = text("agent.py")
    assert "text_input=False" not in agent
    assert "text_output=False" not in agent
    assert "video_input=True" in agent


def test_chat_uses_agent_transcriptions_for_responses() -> None:
    client = text("vision-client/src/main.js")
    assert "registerTextStreamHandler('lk.transcription'" in client
    assert "upsertTranscriptionMessage" in client
    assert "lk.segment_id" in client
    assert "chat-message nova" not in client  # role is created dynamically, not hardcoded HTML


def test_text_chat_is_session_only_and_does_not_auto_enable_media() -> None:
    client = text("vision-client/src/main.js")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in client
    assert "state.cameraEnabled = false" in client
    assert "state.micEnabled = false" in client
    assert "clearChat();" in client


def test_dashboard_detach_did_not_regress() -> None:
    agent = text("agent.py")
    assert "nova_agent_bridge" not in agent
    assert "dashboard_bridge_loop" not in agent
    assert "status.set_phase" not in agent


def test_window_size_accounts_for_chat_panel() -> None:
    client = text("vision-client/src/main.js")
    config = text("vision-client/src-tauri/tauri.conf.json")
    assert "new LogicalSize(420, 560)" in client
    assert '"height": 560' in config


if __name__ == "__main__":
    checks = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for check in checks:
        check()
    print(f"NOVA Vision text chat contract: {len(checks)} checks passed.")
