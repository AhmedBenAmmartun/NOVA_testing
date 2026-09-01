from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from .storage import default_capture_root


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    reason: str
    used: int
    limit: int


class ClassCloudUsageBudget:
    """Independent cloud-request budget for Class Intelligence.

    NOVA's general specialist budget is intentionally kept separate so a
    normal day of NOVA usage cannot silently disable live classroom Q&A or
    post-class note generation. The counter stores only counts/provider names.
    """

    def __init__(self) -> None:
        self.enabled = self._read_bool("NOVA_CLASS_CLOUD_BUDGET_ENABLED", True)
        # Raised from 60 on 2026-08-28: a real 107-minute class exhausted the
        # cap in under two hours and fell back to a local model that was
        # initially offline and then 30-90s behind. The cap exists to protect
        # the shared cloud quota, not to end live answers mid-lecture.
        self.daily_request_limit = self._read_int(
            "NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT",
            200,
        )
        self.path = self._usage_path()
        self._lock = threading.Lock()

    @staticmethod
    def _read_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}

    @staticmethod
    def _read_int(name: str, default: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _usage_path() -> Path:
        custom = os.getenv("NOVA_CLASS_CLOUD_USAGE_FILE", "").strip()
        if custom:
            return Path(custom).expanduser()
        return default_capture_root() / "_control" / "class_cloud_usage.json"

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"date": date.today().isoformat(), "total_requests": 0, "providers": {}}

    def _load_state(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty_state()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty_state()
        if state.get("date") != date.today().isoformat():
            return self._empty_state()
        if not isinstance(state.get("total_requests"), int):
            return self._empty_state()
        if not isinstance(state.get("providers"), dict):
            state["providers"] = {}
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)

    def try_consume(self, provider: str) -> BudgetDecision:
        if not self.enabled:
            return BudgetDecision(True, "class_budget_disabled", 0, self.daily_request_limit)
        if self.daily_request_limit < 0:
            return BudgetDecision(True, "class_budget_unlimited", 0, self.daily_request_limit)

        with self._lock:
            state = self._load_state()
            used = int(state.get("total_requests", 0))
            if used >= self.daily_request_limit:
                return BudgetDecision(
                    False,
                    "daily_class_cloud_limit_reached",
                    used,
                    self.daily_request_limit,
                )
            providers = state.setdefault("providers", {})
            providers[provider] = int(providers.get(provider, 0)) + 1
            state["total_requests"] = used + 1
            self._save_state(state)
            return BudgetDecision(
                True,
                "class_cloud_request_reserved",
                used + 1,
                self.daily_request_limit,
            )

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._load_state()
        used = int(state.get("total_requests", 0))
        remaining = None if self.daily_request_limit < 0 else max(0, self.daily_request_limit - used)
        return {
            "scope": "class_intelligence",
            "enabled": self.enabled,
            "daily_request_limit": self.daily_request_limit,
            "used_today": used,
            "remaining_today": remaining,
            "providers": dict(state.get("providers", {})),
        }


_class_cloud_budget: ClassCloudUsageBudget | None = None


def get_class_cloud_usage_budget() -> ClassCloudUsageBudget:
    global _class_cloud_budget
    if _class_cloud_budget is None:
        _class_cloud_budget = ClassCloudUsageBudget()
    return _class_cloud_budget
