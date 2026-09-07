from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable


def _default_state_root() -> Path:
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "NOVA" / "CoreIntelligence"
    return Path.home() / ".nova" / "core-intelligence"


@dataclass(frozen=True, slots=True)
class ShadowEvaluationRecord:
    project_id: str
    evaluable: bool
    packet_injected: bool
    project_correct: bool | None
    confident_wrong: bool
    wrong_project: bool
    protected_action_would_change: bool
    abstained: bool
    reason_code: str
    recorded_at: str

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        evaluable: bool,
        packet_injected: bool,
        project_correct: bool | None,
        confident_wrong: bool = False,
        wrong_project: bool = False,
        protected_action_would_change: bool = False,
        abstained: bool = False,
        reason_code: str = "manual_eval",
    ) -> "ShadowEvaluationRecord":
        return cls(
            project_id=str(project_id),
            evaluable=bool(evaluable),
            packet_injected=bool(packet_injected),
            project_correct=project_correct if project_correct is None else bool(project_correct),
            confident_wrong=bool(confident_wrong),
            wrong_project=bool(wrong_project),
            protected_action_would_change=bool(protected_action_would_change),
            abstained=bool(abstained),
            reason_code=str(reason_code)[:80],
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "evaluable": self.evaluable,
            "packet_injected": self.packet_injected,
            "project_correct": self.project_correct,
            "confident_wrong": self.confident_wrong,
            "wrong_project": self.wrong_project,
            "protected_action_would_change": self.protected_action_would_change,
            "abstained": self.abstained,
            "reason_code": self.reason_code,
            "recorded_at": self.recorded_at,
        }


@dataclass(frozen=True, slots=True)
class ShadowMetrics:
    total: int
    evaluable: int
    injected_evaluable: int
    correct_injected: int
    precision: float
    confident_wrong_count: int
    confident_wrong_rate: float
    wrong_project_protected_count: int
    abstentions: int
    eligible: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "evaluable": self.evaluable,
            "injected_evaluable": self.injected_evaluable,
            "correct_injected": self.correct_injected,
            "precision": round(self.precision, 4),
            "confident_wrong_count": self.confident_wrong_count,
            "confident_wrong_rate": round(self.confident_wrong_rate, 4),
            "wrong_project_protected_count": self.wrong_project_protected_count,
            "abstentions": self.abstentions,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
        }


def compute_shadow_metrics(records: Iterable[ShadowEvaluationRecord]) -> ShadowMetrics:
    items = tuple(records)
    evaluable_items = tuple(item for item in items if item.evaluable)
    injected = tuple(item for item in evaluable_items if item.packet_injected)
    correct = sum(1 for item in injected if item.project_correct is True)
    precision = correct / len(injected) if injected else 0.0
    confident_wrong = sum(1 for item in injected if item.confident_wrong)
    confident_wrong_rate = (
        confident_wrong / len(injected) if injected else 0.0
    )
    wrong_project_protected = sum(
        1
        for item in injected
        if item.wrong_project and item.protected_action_would_change
    )
    abstentions = sum(1 for item in items if item.abstained)

    reasons: list[str] = []
    if len(evaluable_items) < 50:
        reasons.append(f"need at least 50 evaluable turns; have {len(evaluable_items)}")
    if precision < 0.95:
        reasons.append(f"precision must be >= 0.95; observed {precision:.4f}")
    if confident_wrong_rate > 0.02:
        reasons.append(
            "confident-wrong rate must be <= 0.02; "
            f"observed {confident_wrong_rate:.4f}"
        )
    if wrong_project_protected:
        reasons.append(
            "wrong-project context would have changed a protected action "
            f"{wrong_project_protected} time(s)"
        )

    return ShadowMetrics(
        total=len(items),
        evaluable=len(evaluable_items),
        injected_evaluable=len(injected),
        correct_injected=correct,
        precision=precision,
        confident_wrong_count=confident_wrong,
        confident_wrong_rate=confident_wrong_rate,
        wrong_project_protected_count=wrong_project_protected,
        abstentions=abstentions,
        eligible=not reasons,
        reasons=tuple(reasons),
    )


class ShadowEvaluationStore:
    """Local-only structured shadow-evaluation journal.

    It stores no user transcript/task text. It never changes runtime authority;
    it only reports whether the observed metrics meet the agreed graduation bar.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_state_root() / "shadow-eval.jsonl"

    def record(self, record: ShadowEvaluationRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.as_dict(), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                return

    def load(self) -> tuple[ShadowEvaluationRecord, ...]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

        output: list[ShadowEvaluationRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                output.append(
                    ShadowEvaluationRecord(
                        project_id=str(raw.get("project_id", "")),
                        evaluable=bool(raw.get("evaluable", False)),
                        packet_injected=bool(raw.get("packet_injected", False)),
                        project_correct=(
                            None
                            if raw.get("project_correct") is None
                            else bool(raw.get("project_correct"))
                        ),
                        confident_wrong=bool(raw.get("confident_wrong", False)),
                        wrong_project=bool(raw.get("wrong_project", False)),
                        protected_action_would_change=bool(
                            raw.get("protected_action_would_change", False)
                        ),
                        abstained=bool(raw.get("abstained", False)),
                        reason_code=str(raw.get("reason_code", ""))[:80],
                        recorded_at=str(raw.get("recorded_at", "")),
                    )
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return tuple(output)

    def metrics(self) -> ShadowMetrics:
        return compute_shadow_metrics(self.load())
