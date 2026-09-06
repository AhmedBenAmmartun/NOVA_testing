from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_memory_capability_is_default_active_second_brain() -> None:
    # Metadata (default_active) lives in nova_os.capability_definitions; tool
    # wiring lives in nova_os.catalog. Both must agree for this to be true.
    definitions_text = (ROOT / "nova_os" / "capability_definitions.py").read_text(
        encoding="utf-8-sig"
    )
    start = definitions_text.index('capability_id="memory"')
    end = definitions_text.find("CapabilityDefinition(", start + 1)
    metadata_block = definitions_text[start : end if end >= 0 else None]
    assert "default_active=True" in metadata_block

    catalog_text = (ROOT / "nova_os" / "catalog.py").read_text(encoding="utf-8-sig")
    wiring_start = catalog_text.index('"memory": (')
    wiring_end = catalog_text.find("),", wiring_start)
    wiring_block = catalog_text[wiring_start : wiring_end if wiring_end >= 0 else None]
    for name in (
        "second_brain_status",
        "list_vault_files",
        "read_vault_file",
        "save_vault_file",
        "search_memory",
        "read_memory_note",
        "save_memory_note",
    ):
        assert name in wiring_block


def test_second_brain_prompt_is_retrieval_first() -> None:
    text = (ROOT / "prompts.py").read_text(encoding="utf-8-sig")
    assert "# MEMORY — NOVA VAULT SECOND BRAIN" in text
    assert "canonical persistent second brain" in text
    assert "Do NOT inject or read the entire vault on every turn" in text
    assert "Never access .obsidian configuration files" in text
    assert "Do not create another duplicate" in text
    assert "Pending Review" in text
    assert "Scripts" in text


def test_vault_file_tools_are_bounded() -> None:
    text = (ROOT / "tools" / "obsidian.py").read_text(encoding="utf-8-sig")
    assert "SAFE_VAULT_TEXT_EXTENSIONS" in text
    assert "MAX_VAULT_FILE_READ_CHARS" in text
    assert "MAX_VAULT_FILE_WRITE_CHARS" in text
    assert "SECOND_BRAIN_WRITABLE_FOLDERS" in text
    assert "SECOND_BRAIN_READ_ONLY_FOLDERS" in text
    assert '"archive"' in text
    assert '"scripts"' in text
    assert '".obsidian"' in text
    assert "_looks_like_secret" in text
    assert "if path.exists() and not overwrite" in text


def test_second_brain_tools_exist() -> None:
    text = (ROOT / "tools" / "obsidian.py").read_text(encoding="utf-8-sig")
    for name in (
        "second_brain_status",
        "list_vault_files",
        "read_vault_file",
        "save_vault_file",
    ):
        assert f"async def {name}" in text
