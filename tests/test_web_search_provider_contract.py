from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_web_search_uses_current_ddgs_metasearch() -> None:
    text = (ROOT / "tools" / "web.py").read_text(encoding="utf-8-sig")
    assert "from ddgs import DDGS" in text
    assert "from duckduckgo_search import DDGS" not in text
    assert '"auto"' in text
    assert '"bing, brave, duckduckgo, google"' in text
    assert "backend=backend" in text


def test_requirements_use_ddgs() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8-sig")
    assert "ddgs>=9.10,<10" in text
    assert "duckduckgo-search" not in text.lower()
