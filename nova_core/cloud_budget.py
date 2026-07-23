"""Local cloud-request budget for NOVA."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    """Result of a cloud-budget check."""

    allowed: bool
    reason: str
    used: int
    limit: int


class CloudUsageBudget:
    """
    Restrict how many specialist cloud requests NOVA may make daily.

    The counter is stored locally and contains no prompts, answers,
    API keys, or other private content.
    """

    def __init__(self) -> None:
        self.enabled = self._read_bool(
            "NOVA_CLOUD_BUDGET_ENABLED",
            True,
        )

        self.daily_request_limit = self._read_int(
            "NOVA_CLOUD_DAILY_REQUEST_LIMIT",
            10,
        )

        self.path = self._usage_path()
        self._lock = threading.Lock()

    @staticmethod
    def _read_bool(
        name: str,
        default: bool,
    ) -> bool:
        raw_value = os.getenv(name)

        if raw_value is None:
            return default

        return raw_value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "enabled",
        }

    @staticmethod
    def _read_int(
        name: str,
        default: int,
    ) -> int:
        raw_value = os.getenv(name)

        if raw_value is None:
            return default

        try:
            return int(raw_value)

        except ValueError:
            return default

    @staticmethod
    def _usage_path() -> Path:
        custom_path = os.getenv(
            "NOVA_CLOUD_USAGE_FILE",
            "",
        ).strip()

        if custom_path:
            return Path(custom_path).expanduser()

        local_app_data = os.getenv(
            "LOCALAPPDATA",
            "",
        ).strip()

        if local_app_data:
            return (
                Path(local_app_data)
                / "NOVA"
                / "cloud_usage.json"
            )

        return (
            Path.home()
            / ".nova"
            / "cloud_usage.json"
        )

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "date": date.today().isoformat(),
            "total_requests": 0,
            "providers": {},
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty_state()

        try:
            state = json.loads(
                self.path.read_text(
                    encoding="utf-8",
                )
            )

        except (
            OSError,
            json.JSONDecodeError,
        ):
            return self._empty_state()

        if state.get("date") != date.today().isoformat():
            return self._empty_state()

        if not isinstance(
            state.get("total_requests"),
            int,
        ):
            return self._empty_state()

        if not isinstance(
            state.get("providers"),
            dict,
        ):
            state["providers"] = {}

        return state

    def _save_state(
        self,
        state: dict[str, Any],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.path.with_suffix(
            ".tmp"
        )

        temporary_path.write_text(
            json.dumps(
                state,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(self.path)

    def try_consume(
        self,
        provider: str,
    ) -> BudgetDecision:
        """
        Reserve one cloud request.

        A limit of:
        - 0 blocks cloud specialists completely.
        - A positive number allows that many requests each day.
        - A negative number means unlimited.
        """

        if not self.enabled:
            return BudgetDecision(
                allowed=True,
                reason="budget_disabled",
                used=0,
                limit=self.daily_request_limit,
            )

        if self.daily_request_limit < 0:
            return BudgetDecision(
                allowed=True,
                reason="unlimited",
                used=0,
                limit=self.daily_request_limit,
            )

        with self._lock:
            state = self._load_state()

            used = int(
                state.get(
                    "total_requests",
                    0,
                )
            )

            if used >= self.daily_request_limit:
                return BudgetDecision(
                    allowed=False,
                    reason="daily_cloud_limit_reached",
                    used=used,
                    limit=self.daily_request_limit,
                )

            provider_counts = state.setdefault(
                "providers",
                {},
            )

            provider_counts[provider] = (
                int(
                    provider_counts.get(
                        provider,
                        0,
                    )
                )
                + 1
            )

            state["total_requests"] = used + 1

            self._save_state(state)

            return BudgetDecision(
                allowed=True,
                reason="cloud_request_reserved",
                used=used + 1,
                limit=self.daily_request_limit,
            )

    def status(self) -> dict[str, Any]:
        """Return safe usage information."""

        with self._lock:
            state = self._load_state()

        return {
            "enabled": self.enabled,
            "daily_request_limit": self.daily_request_limit,
            "used_today": state["total_requests"],
            "remaining_today": (
                max(
                    0,
                    self.daily_request_limit
                    - state["total_requests"],
                )
                if self.daily_request_limit >= 0
                else None
            ),
            "providers": dict(
                state.get(
                    "providers",
                    {},
                )
            ),
        }


_cloud_usage_budget: CloudUsageBudget | None = None


def get_cloud_usage_budget() -> CloudUsageBudget:
    """Create or return NOVA's shared cloud budget."""

    global _cloud_usage_budget

    if _cloud_usage_budget is None:
        _cloud_usage_budget = CloudUsageBudget()

    return _cloud_usage_budget