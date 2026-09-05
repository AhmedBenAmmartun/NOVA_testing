"""Append-only lifecycle journal for NOVA Lab."""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class LifecycleJournal:
    """Write safe lifecycle metadata as JSONL; never store source or secrets."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def build_event(
        self,
        *,
        event: str,
        feature_id: str,
        from_state: str | None = None,
        to_state: str | None = None,
        detail: str = "",
    ) -> dict[str, Any]:
        return {
            "event_id": secrets.token_hex(12),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": str(event)[:80],
            "feature_id": str(feature_id)[:120],
            "from_state": from_state,
            "to_state": to_state,
            "detail": self._safe_detail(detail),
        }

    def append(
        self,
        *,
        event: str,
        feature_id: str,
        from_state: str | None = None,
        to_state: str | None = None,
        detail: str = "",
    ) -> str:
        record = self.build_event(
            event=event,
            feature_id=feature_id,
            from_state=from_state,
            to_state=to_state,
            detail=detail,
        )
        self.append_record(record)
        return str(record["event_id"])

    def append_record(self, record: dict[str, Any]) -> None:
        safe = dict(record)
        safe["detail"] = self._safe_detail(str(safe.get("detail", "")))

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(safe, ensure_ascii=False) + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass

    def contains(self, event_id: str) -> bool:
        if not event_id or not self.path.exists():
            return False

        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False

        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("event_id") == event_id:
                return True
        return False

    @staticmethod
    def _safe_detail(detail: str) -> str:
        cleaned = " ".join(str(detail).replace("\r", " ").replace("\n", " ").split())
        lowered = cleaned.lower()
        blocked = (
            ".env",
            "password",
            "api key",
            "api_key",
            "secret",
            "access token",
            "refresh token",
            ".spotify_cache",
        )
        if any(term in lowered for term in blocked):
            return "[sensitive lifecycle detail redacted]"
        return cleaned[:500]
