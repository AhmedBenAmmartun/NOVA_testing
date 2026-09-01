from __future__ import annotations

from pathlib import Path
import json
import threading

from .models import MaterialRecord


class MaterialCatalog:
    """Append-only JSONL material catalog with deterministic dedup lookup."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        output: list[dict] = []
        for raw in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                output.append(value)
        return output

    def find_by_hash(self, sha256: str) -> dict | None:
        target = sha256.strip().lower()
        for record in reversed(self.records()):
            if str(record.get("sha256", "")).lower() == target:
                return record
        return None

    def append(self, record: MaterialRecord) -> None:
        payload = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
