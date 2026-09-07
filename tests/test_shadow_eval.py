from __future__ import annotations

from pathlib import Path

from nova_intelligence.shadow_eval import (
    ShadowEvaluationRecord,
    ShadowEvaluationStore,
    compute_shadow_metrics,
)


def _good_record() -> ShadowEvaluationRecord:
    return ShadowEvaluationRecord.create(
        project_id="nova",
        evaluable=True,
        packet_injected=True,
        project_correct=True,
    )


def test_graduation_requires_50_evaluable_turns() -> None:
    metrics = compute_shadow_metrics([_good_record() for _ in range(49)])
    assert not metrics.eligible
    assert any("50 evaluable" in reason for reason in metrics.reasons)


def test_graduation_bar_can_pass_exactly() -> None:
    records = [_good_record() for _ in range(50)]
    metrics = compute_shadow_metrics(records)
    assert metrics.eligible
    assert metrics.precision == 1.0
    assert metrics.confident_wrong_rate == 0.0
    assert metrics.wrong_project_protected_count == 0


def test_wrong_project_protected_action_blocks_graduation() -> None:
    records = [_good_record() for _ in range(50)]
    records.append(
        ShadowEvaluationRecord.create(
            project_id="valo",
            evaluable=True,
            packet_injected=True,
            project_correct=False,
            confident_wrong=True,
            wrong_project=True,
            protected_action_would_change=True,
        )
    )
    metrics = compute_shadow_metrics(records)
    assert not metrics.eligible
    assert metrics.wrong_project_protected_count == 1


def test_store_round_trip_is_structured_only(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    store = ShadowEvaluationStore(path)
    record = ShadowEvaluationRecord.create(
        project_id="nova",
        evaluable=False,
        packet_injected=False,
        project_correct=None,
        abstained=True,
        reason_code="unknown_project",
    )
    store.record(record)
    loaded = store.load()
    assert loaded == (record,)
    assert "transcript" not in path.read_text(encoding="utf-8").casefold()


def test_confident_wrong_rate_is_measured_on_injected_turns() -> None:
    records = [_good_record() for _ in range(50)]
    for _ in range(2):
        records.append(
            ShadowEvaluationRecord.create(
                project_id="nova",
                evaluable=True,
                packet_injected=True,
                project_correct=False,
                confident_wrong=True,
                wrong_project=False,
                protected_action_would_change=False,
            )
        )
    metrics = compute_shadow_metrics(records)
    assert metrics.precision > 0.95
    assert metrics.confident_wrong_rate > 0.02
    assert not metrics.eligible


def test_wrong_project_without_injection_does_not_count_as_injection_violation() -> None:
    records = [_good_record() for _ in range(50)]
    records.append(
        ShadowEvaluationRecord.create(
            project_id="valo",
            evaluable=True,
            packet_injected=False,
            project_correct=False,
            confident_wrong=False,
            wrong_project=True,
            protected_action_would_change=True,
        )
    )
    metrics = compute_shadow_metrics(records)
    assert metrics.wrong_project_protected_count == 0
    assert metrics.eligible
