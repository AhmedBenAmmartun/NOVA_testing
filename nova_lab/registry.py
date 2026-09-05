"""Persistent feature registry for NOVA Lab."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .history import LifecycleJournal
from .models import FeatureRecord, FeatureState


class RegistryConflictError(ValueError):
    """Raised when registry invariants would be violated."""


def default_state_root() -> Path:
    local = os.getenv("LOCALAPPDATA")
    if local:
        return Path(local) / "NOVA" / "Lab"
    return Path.home() / ".nova" / "lab"


class FeatureRegistry:
    """Local lifecycle state.

    V1A is intentionally single-writer. The future out-of-process release
    supervisor will own mutations before promotion/restart becomes available.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        journal: LifecycleJournal | None = None,
    ) -> None:
        root = default_state_root()
        self.path = Path(path) if path is not None else root / "features.json"
        self.journal = journal or LifecycleJournal(root / "lifecycle.jsonl")
        self._lock = threading.RLock()
        self._reconcile_journal()

    def list(self) -> tuple[FeatureRecord, ...]:
        with self._lock:
            records = self._load()
        return tuple(sorted(records.values(), key=lambda item: item.feature_id))

    def get(self, feature_id: str) -> FeatureRecord | None:
        with self._lock:
            return self._load().get(feature_id)

    def register(self, feature: FeatureRecord) -> FeatureRecord:
        if feature.status is not FeatureState.LAB:
            raise RegistryConflictError("New features must enter NOVA Lab in LAB state.")

        with self._lock:
            records = self._load()
            if feature.feature_id in records:
                raise RegistryConflictError(
                    f"Feature already registered: {feature.feature_id}"
                )

            event = self.journal.build_event(
                event="registered",
                feature_id=feature.feature_id,
                to_state=FeatureState.LAB.value,
            )
            records[feature.feature_id] = feature
            self._save(records, last_event=event)
            self._append_journal_best_effort(event)

        return feature

    def transition(self, feature_id: str, target: FeatureState) -> FeatureRecord:
        """Record a lifecycle transition.

        This is a state store, not an authorization boundary. No model-callable
        tool may expose ACTIVE/RETIRED transitions directly. The later release
        manager must obtain trusted user approval through nova_policy first.
        """
        with self._lock:
            records = self._load()
            current = records.get(feature_id)
            if current is None:
                raise KeyError(feature_id)

            target = FeatureState(target)
            if target is FeatureState.ACTIVE:
                conflicting = [
                    item.feature_id
                    for item in records.values()
                    if item.feature_id != feature_id
                    and item.capability_id == current.capability_id
                    and item.status is FeatureState.ACTIVE
                ]
                if conflicting:
                    raise RegistryConflictError(
                        "Only one ACTIVE feature is allowed per capability: "
                        + ", ".join(conflicting)
                    )

            updated = current.transition(target)
            event = self.journal.build_event(
                event="transition",
                feature_id=feature_id,
                from_state=current.status.value,
                to_state=updated.status.value,
            )
            records[feature_id] = updated
            self._save(records, last_event=event)
            self._append_journal_best_effort(event)

        return updated

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": self.SCHEMA_VERSION,
                "features": [],
                "last_event": None,
            }

        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise RuntimeError("Unsupported NOVA Lab registry schema version.")
        return data

    def _load(self) -> dict[str, FeatureRecord]:
        data = self._load_payload()
        return {
            item["feature_id"]: FeatureRecord.from_dict(item)
            for item in data.get("features", [])
        }

    def _save(
        self,
        records: dict[str, FeatureRecord],
        *,
        last_event: dict[str, Any] | None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "features": [records[key].to_dict() for key in sorted(records)],
            "last_event": last_event,
        }

        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, self.path)

    def _append_journal_best_effort(self, event: dict[str, Any]) -> None:
        try:
            self.journal.append_record(event)
        except OSError:
            # The authoritative registry stores the same event atomically.
            # A later registry instance reconciles the missing JSONL record.
            pass

    def _reconcile_journal(self) -> None:
        if not self.path.exists():
            return

        try:
            payload = self._load_payload()
        except (OSError, json.JSONDecodeError, RuntimeError):
            return

        event = payload.get("last_event")
        if not isinstance(event, dict):
            return

        event_id = str(event.get("event_id") or "")
        if not event_id or self.journal.contains(event_id):
            return

        try:
            self.journal.append_record(event)
        except OSError:
            # State remains truthful even when the audit sink is temporarily
            # unavailable; reconciliation will retry on the next instance.
            pass
