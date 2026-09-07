from __future__ import annotations

import json
import os
from pathlib import Path
import re
import time
from typing import Any

from .models import ContextPacket, FactStatus, ProjectState, utc_now_iso
from .project_state import ProjectStateBuilder
from .shadow_eval import ShadowEvaluationStore


_TECHNICAL_TERMS = frozenset(
    {
        "nova project",
        "project",
        "repo",
        "repository",
        "git",
        "branch",
        "commit",
        "code",
        "test",
        "bug",
        "architecture",
        "implementation",
        "class intelligence",
        "capability",
        "runtime",
        "lab",
        "development",
        "core intelligence",
        "a0",
        "a1",
        "a2",
    }
)


def _fact_value(state: ProjectState, group: str, key: str) -> Any:
    mapping = getattr(state, group)
    fact = mapping.get(key)
    return None if fact is None else fact.value


def _status_value(state: ProjectState, group: str, key: str) -> str:
    mapping = getattr(state, group)
    fact = mapping.get(key)
    return FactStatus.UNKNOWN.value if fact is None else fact.status.value


class ContextBroker:
    """Build NOVA's tiny base packet and bounded project packet.

    A1 never silently grants project context authority. Project influence
    requires BOTH the agreed shadow-evaluation graduation bar and an explicit
    trusted environment opt-in. Without both, the packet is SHADOW_ONLY.
    """

    def __init__(
        self,
        project_root: Path | str | None = None,
        *,
        cache_ttl_seconds: float = 5.0,
        shadow_store: ShadowEvaluationStore | None = None,
    ) -> None:
        self.project_root = Path(
            project_root or Path(__file__).resolve().parents[1]
        ).expanduser().resolve()
        self.cache_ttl_seconds = max(0.0, float(cache_ttl_seconds))
        self.shadow_store = shadow_store or ShadowEvaluationStore()
        self._cached_state: ProjectState | None = None
        self._cached_at = 0.0

    def get_state(self, *, force: bool = False) -> ProjectState:
        now = time.monotonic()
        if (
            not force
            and self._cached_state is not None
            and (now - self._cached_at) <= self.cache_ttl_seconds
        ):
            return self._cached_state
        state = ProjectStateBuilder(self.project_root).build()
        self._cached_state = state
        self._cached_at = now
        return state

    @staticmethod
    def task_needs_project_packet(task: str) -> bool:
        cleaned = " ".join(str(task or "").casefold().split())
        if not cleaned:
            return False
        tokens = frozenset(re.findall(r"[a-z0-9]+", cleaned))
        for term in _TECHNICAL_TERMS:
            if " " in term:
                if term in cleaned:
                    return True
            elif term in tokens:
                return True
        return False

    def project_influence_allowed(self) -> bool:
        trusted_opt_in = os.getenv(
            "NOVA_CORE_PROJECT_INFLUENCE",
            "",
        ).strip().casefold() in {"1", "true", "enabled", "yes"}
        return trusted_opt_in and self.shadow_store.metrics().eligible

    def _base(self, state: ProjectState) -> dict[str, Any]:
        return {
            "agent": "NOVA",
            "project_id": state.project_id,
            "branch": _fact_value(state, "repository", "branch"),
            "head": _fact_value(state, "repository", "head"),
            "dirty": _fact_value(state, "repository", "dirty"),
            "branch_status": _status_value(state, "repository", "branch"),
            "head_status": _status_value(state, "repository", "head"),
            "dirty_status": _status_value(state, "repository", "dirty"),
        }

    def _project(self, state: ProjectState) -> dict[str, Any]:
        capabilities = _fact_value(state, "systems", "capabilities") or []
        capability_ids = [
            item.get("capability_id")
            for item in capabilities
            if isinstance(item, dict) and item.get("capability_id")
        ]
        return {
            "root": _fact_value(state, "identity", "root"),
            "milestone": _fact_value(state, "active_work", "milestone"),
            "changed_files": _fact_value(state, "repository", "changed_files"),
            "capability_ids": capability_ids,
            "issues": list(state.issues[:8]),
            "decisions": list(state.decisions[:8]),
            "failed_approaches": list(state.failed_approaches[:8]),
            "test_evidence": (
                None
                if state.tests.get("latest") is None
                else {
                    "value": state.tests["latest"].value,
                    "status": state.tests["latest"].status.value,
                    "freshness": state.tests["latest"].freshness,
                    "note": state.tests["latest"].note,
                }
            ),
            "conflicts": list(state.conflicts[:8]),
        }

    def build_packet(self, task: str = "") -> ContextPacket:
        state = self.get_state()
        needs_project = self.task_needs_project_packet(task)
        allowed = self.project_influence_allowed()
        project = self._project(state) if needs_project else None
        project_status = (
            "INFLUENCE_ALLOWED"
            if project is not None and allowed
            else "SHADOW_ONLY"
            if project is not None
            else "NOT_NEEDED"
        )
        provenance_count = 0
        for group_name in (
            "identity",
            "repository",
            "active_work",
            "systems",
            "tests",
            "continuity",
        ):
            for fact in getattr(state, group_name).values():
                provenance_count += len(fact.provenance)
        reason = (
            "technical/project-bearing task"
            if needs_project
            else "task did not materially require project context"
        )
        return ContextPacket(
            generated_at=utc_now_iso(),
            base=self._base(state),
            project=project,
            project_status=project_status,
            influence_allowed=bool(project is not None and allowed),
            reason=reason,
            provenance_count=provenance_count,
        )

    def render_for_model(self, task: str = "") -> str:
        packet = self.build_packet(task)
        header = (
            "NOVA Core Intelligence A1\n"
            f"Project packet status: {packet.project_status}\n"
            f"Influence allowed: {str(packet.influence_allowed).lower()}\n"
        )
        rules = (
            "Rules: VERIFIED current repository/Git/runtime/test evidence outranks "
            "documentation. UNKNOWN means do not guess. SHADOW_ONLY project context "
            "is advisory and cannot authorize protected technical actions, releases, "
            "Git writes, production changes, or approval.\n"
        )
        body = json.dumps(packet.as_dict(), ensure_ascii=False, sort_keys=True)
        return (header + rules + body)[:6000]

    def shadow_status_text(self) -> str:
        metrics = self.shadow_store.metrics()
        return json.dumps(metrics.as_dict(), ensure_ascii=False, sort_keys=True)
