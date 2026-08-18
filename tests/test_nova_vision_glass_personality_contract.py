from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_glass_widget_is_compact_and_settings_are_overlay() -> None:
    js = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    css = (ROOT / "vision-client" / "src" / "styles.css").read_text(encoding="utf-8-sig")
    html = (ROOT / "vision-client" / "index.html").read_text(encoding="utf-8-sig")

    assert "new LogicalSize(420, 560)" in js
    assert "new LogicalSize(420, 150)" in js
    assert 'id="personalityOverlay"' in html
    assert 'id="settingsButton"' in html
    assert ".shell.settings-open .personality-overlay" in css
    assert "backdrop-filter: blur(30px)" in css


def test_personality_controls_are_session_only_and_sync_over_custom_topic() -> None:
    js = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    assert "{ topic: 'nova.personality' }" in js
    assert "localStorage" not in js
    assert "sessionStorage" not in js
    assert "indexedDB" not in js
    assert "syncPersonalityToAgent" in js


def test_agent_personality_updates_are_whitelisted_not_raw_prompt_injection() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    assert "_PERSONALITY_MODES" in agent
    assert "_PROFANITY_LEVELS" in agent
    assert "_normalize_personality" in agent
    assert "await assistant.update_instructions(" in agent
    assert 'register_text_stream_handler("nova.personality"' in agent
    assert "NEVER overrides safety, privacy, permissions" in agent


def test_personality_does_not_expand_media_permissions() -> None:
    token = (ROOT / "vision_token.py").read_text(encoding="utf-8-sig")
    assert "can_publish_data=True" in token
    assert 'can_publish_sources=["camera", "microphone"]' in token
    assert "can_update_own_metadata=False" in token


def test_mic_camera_remain_in_main_composer() -> None:
    html = (ROOT / "vision-client" / "index.html").read_text(encoding="utf-8-sig")
    assert 'id="micButton"' in html
    assert 'id="cameraSourceButton"' in html
    assert 'class="chat-composer"' in html
