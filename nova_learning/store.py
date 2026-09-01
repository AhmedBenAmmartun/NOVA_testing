from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import os
import threading
import time

from .redaction import redact
from .schema import Experience


def default_experience_root() -> Path:
    """Return a local-only data directory outside the NOVA Git repository."""
    override = os.getenv("NOVA_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve() / "experience"

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "NOVA" / "learning" / "experience"

    return Path.home() / ".nova" / "learning" / "experience"


@dataclass(slots=True)
class StoreWrite:
    path: Path
    bytes_written: int


class NDJSONExperienceStore:
    """Crash-tolerant append-only store: one NDJSON file per local day."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else default_experience_root()
        self.root = self.root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _daily_path(self, ts: float | None = None) -> Path:
        day = datetime.fromtimestamp(ts or time.time()).strftime("%Y-%m-%d")
        return self.root / f"{day}.ndjson"

    def _append(self, record: dict[str, Any], *, ts: float | None = None) -> StoreWrite:
        path = self._daily_path(ts)
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = payload.encode("utf-8")
        with self._lock:
            with path.open("ab") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        return StoreWrite(path=path, bytes_written=len(encoded))

    def append_experience(self, experience: Experience) -> StoreWrite:
        """Persist a fully redacted Experience event."""
        raw = experience.to_dict()
        record = {
            "record_type": "experience",
            "schema_version": 1,
            "experience": redact(raw),
        }
        return self._append(record, ts=experience.ts)

    def append_patch(self, experience_id: str, changes: dict[str, Any]) -> StoreWrite:
        """Append a correction/evaluation patch without rewriting history."""
        safe_id = str(experience_id).strip()
        if not safe_id:
            raise ValueError("experience_id cannot be empty")
        record = {
            "record_type": "patch",
            "schema_version": 1,
            "experience_id": safe_id,
            "patch_ts": time.time(),
            "changes": redact(changes),
        }
        return self._append(record)
