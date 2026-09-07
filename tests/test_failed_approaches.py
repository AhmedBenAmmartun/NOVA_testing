from __future__ import annotations

from pathlib import Path

from nova_intelligence.failed_approaches import FailedApproachIndex


def test_extracts_only_explicit_failure_signals(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text(
        "# Notes\n"
        "- Working feature is stable.\n"
        "- Root cause: the old global singleton mixed sessions.\n"
        "- Use the normal pipeline.\n"
        "- Do not assume same-turn dynamic activation works.\n",
        encoding="utf-8",
    )

    items = FailedApproachIndex(tmp_path).scan()

    texts = [item.text for item in items]
    assert any("Root cause" in text for text in texts)
    assert any("Do not assume" in text for text in texts)
    assert not any("Working feature is stable" in text for text in texts)


def test_deduplicates_repeated_lines(tmp_path: Path) -> None:
    (tmp_path / "DEVELOPMENT.md").write_text(
        "Failed: old approach.\nFailed: old approach.\n",
        encoding="utf-8",
    )
    items = FailedApproachIndex(tmp_path).scan()
    assert len(items) == 1


def test_ignores_failure_words_inside_code_fence(tmp_path: Path) -> None:
    (tmp_path / "ROADMAP.md").write_text(
        "```\nfailed = True\n```\n- Regression: visible behavior changed.\n",
        encoding="utf-8",
    )
    items = FailedApproachIndex(tmp_path).scan()
    assert len(items) == 1
    assert "Regression" in items[0].text


def test_redacts_token_like_material_from_failed_approach(tmp_path: Path) -> None:
    token = "sk-" + ("A" * 28)
    (tmp_path / "AGENTS.md").write_text(
        f"Root cause: accidental token {token} was logged and failed security review.\n",
        encoding="utf-8",
    )
    items = FailedApproachIndex(tmp_path).scan()
    assert len(items) == 1
    assert token not in items[0].text
    assert "[REDACTED_TOKEN]" in items[0].text
