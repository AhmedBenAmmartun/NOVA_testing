from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vision_token_allows_text_data_but_limits_media_sources() -> None:
    text = (ROOT / "vision_token.py").read_text(encoding="utf-8-sig")
    assert "can_publish_data=True" in text
    assert "can_publish_data=False" not in text
    assert 'can_publish_sources=["camera", "microphone"]' in text
    assert "can_update_own_metadata=False" in text


def test_frontend_checks_data_permission_before_lk_chat() -> None:
    text = (ROOT / "vision-client" / "src" / "main.js").read_text(encoding="utf-8-sig")
    assert "permissions?.canPublishData" in text
    assert "sendText(text, { topic: 'lk.chat' })" in text
    assert "This NOVA Vision token does not allow LiveKit data publishing" in text
