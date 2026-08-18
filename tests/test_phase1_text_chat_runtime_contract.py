from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_livekit_builtin_text_input_is_used() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    assert "text_input=True" in agent
    assert "_handle_nova_text_input" not in agent
    assert "text_input_cb=_handle_nova_text_input" not in agent
    assert "text_output=room_io.TextOutputOptions(" in agent
    assert "sync_transcription=False" in agent


def test_frontend_chat_autoconnects_and_waits_for_agent() -> None:
    js = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    assert "async function waitForNOVAAgent(" in js
    assert "RoomEvent.ParticipantConnected" in js
    assert "await connectSession();" in js
    assert "await waitForNOVAAgent(state.room, 10000)" in js
    assert "sendText(text, { topic: 'lk.chat' })" in js
    assert "'TEXT DELIVERED'" in js
    assert "'TEXT FAILED'" in js


def test_chat_can_be_typed_before_connection() -> None:
    js = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    assert "el.chatInput.disabled = state.connecting;" in js
    assert (
        "el.sendChatButton.disabled = state.connecting || "
        "state.chatSending || !el.chatInput.value.trim();"
    ) in js


def test_frontend_keeps_v22_text_output_rendering() -> None:
    js = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    assert "registerTextStreamHandler('lk.transcription'" in js
    assert "if (!attributes['lk.transcribed_track_id']) return;" not in js
    assert "upsertChatMessage(" in js
