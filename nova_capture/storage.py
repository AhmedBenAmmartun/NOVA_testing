from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_slug(value: str, *, fallback: str = "class") -> str:
    cleaned = _SAFE.sub("", value).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or fallback


def default_capture_root() -> Path:
    override = os.getenv("NOVA_CLASS_CAPTURE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"

    return (base / "NOVA" / "ClassCapture").resolve()


class ClassCaptureStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_capture_root()).expanduser().resolve()

    def session_dir(self, course: str, session_id: str) -> Path:
        return (
            self.root
            / safe_slug(course, fallback="Unsorted")
            / safe_slug(session_id, fallback="session")
        )

    def create_session_dir(self, course: str, session_id: str) -> Path:
        path = self.session_dir(course, session_id)
        path.mkdir(parents=True, exist_ok=False)
        return path

    @staticmethod
    def write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
