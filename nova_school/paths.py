from __future__ import annotations

import os
from pathlib import Path


def obsidian_vault_path() -> Path:
    configured = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "NOVA Vault").resolve()


def course_materials_root(course_code: str) -> Path:
    return obsidian_vault_path() / "Knowledge" / "Classes" / course_code / "Materials"


def school_runtime_root() -> Path:
    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    path = base / "NOVA" / "School"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def course_sessions_root(course_code: str) -> Path:
    return obsidian_vault_path() / "Knowledge" / "Classes" / course_code / "Sessions"
