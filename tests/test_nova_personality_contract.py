from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_personality_config_exists_and_is_safe() -> None:
    config = json.loads((ROOT / "config" / "nova_personality.json").read_text(encoding="utf-8"))
    assert config["mode"] in {"best_friend", "chill", "focus", "professional"}
    assert config["profanity"] in {"off", "light", "natural", "unfiltered"}
    assert isinstance(config["teasing"], bool)
    assert isinstance(config["auto_tone_down_serious"], bool)


def test_personality_layer_keeps_security_higher_priority() -> None:
    text = (ROOT / "prompts.py").read_text(encoding="utf-8-sig")
    assert "# === NOVA PERSONALITY LAYER V1 BEGIN ===" in text
    assert "PERSONALITY & SOCIAL STYLE" in text
    assert "NEVER overrides safety, privacy, permissions" in text
    assert "hateful slurs" in text
    assert "Do not invent human memories" in text


def test_personality_runtime_prompt_contains_config() -> None:
    import prompts
    assert "PERSONALITY & SOCIAL STYLE" in prompts.SYSTEM_PROMPT
    assert "Mode: best_friend" in prompts.SYSTEM_PROMPT
    assert "Profanity: natural" in prompts.SYSTEM_PROMPT
    assert "close friend" in prompts.SYSTEM_PROMPT
