from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")

def test_video_input_stays_enabled() -> None:
    assert "video_input=True" in read("agent.py")

def test_agent_monitors_real_video_subscription() -> None:
    agent = read("agent.py")
    assert '@ctx.room.on("track_published")' in agent
    assert '@ctx.room.on("track_subscribed")' in agent
    assert '@ctx.room.on("track_subscription_failed")' in agent
    assert '"AGENT_RECEIVING_VIDEO"' in agent
    assert '"nova.vision-status"' in agent

def test_job_context_explicitly_connects() -> None:
    agent = read("agent.py")
    assert "await ctx.connect()" in agent or "await ctx.connect(" in agent

def test_start_nova_control_is_visible() -> None:
    html = read("vision-client/index.html")
    assert 'id="novaSessionBar"' in html
    assert 'id="novaSessionButton"' in html
    assert "Start NOVA" in html

def test_ui_uses_truthful_vision_status() -> None:
    js = read("vision-client/src/main.js")
    assert "AI SEES: CAMERA" not in js
    assert "CAMERA SHARED" in js
    assert "AGENT RECEIVING VIDEO" in js
    assert "nova.vision-status" in js

def test_media_permissions_are_still_restricted() -> None:
    token = read("vision_token.py")
    assert 'can_publish_sources=["camera", "microphone"]' in token
    assert "can_update_own_metadata=False" in token
