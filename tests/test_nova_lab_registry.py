from __future__ import annotations

import json

import pytest

from nova_lab.history import LifecycleJournal
from nova_lab.models import FeatureRecord, FeatureState, InvalidTransitionError
from nova_lab.registry import FeatureRegistry, RegistryConflictError


def _record(feature_id: str, *, capability_id: str = "class_capture") -> FeatureRecord:
    return FeatureRecord(
        feature_id=feature_id,
        capability_id=capability_id,
        name=feature_id,
        branch=f"lab/{feature_id}",
        base_ref="cd6e8d0",
        test_profile="official",
    )


def test_registry_persists_and_reloads(tmp_path) -> None:
    path = tmp_path / "features.json"
    journal = LifecycleJournal(tmp_path / "lifecycle.jsonl")
    registry = FeatureRegistry(path, journal=journal)

    registry.register(_record("granola"))
    reloaded = FeatureRegistry(path, journal=journal)

    assert reloaded.get("granola") is not None
    assert reloaded.get("granola").status is FeatureState.LAB


def test_duplicate_registration_is_rejected(tmp_path) -> None:
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    registry.register(_record("granola"))

    with pytest.raises(RegistryConflictError):
        registry.register(_record("granola"))


def test_only_one_active_feature_per_capability(tmp_path) -> None:
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    registry.register(_record("native"))
    registry.register(_record("granola"))

    registry.transition("native", FeatureState.CANDIDATE)
    registry.transition("native", FeatureState.ACTIVE)
    registry.transition("granola", FeatureState.CANDIDATE)

    with pytest.raises(RegistryConflictError):
        registry.transition("granola", FeatureState.ACTIVE)


def test_registry_write_is_valid_json_and_temp_is_gone(tmp_path) -> None:
    path = tmp_path / "features.json"
    registry = FeatureRegistry(
        path,
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    registry.register(_record("native"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert not path.with_suffix(".json.tmp").exists()


def test_journal_redacts_obvious_secret_language(tmp_path) -> None:
    history = tmp_path / "history.jsonl"
    journal = LifecycleJournal(history)
    journal.append(
        event="test",
        feature_id="x",
        detail="copied .env API key secret",
    )

    record = json.loads(history.read_text(encoding="utf-8"))
    assert record["detail"] == "[sensitive lifecycle detail redacted]"


def test_enter_candidate_transitions_and_stamps_immutable_commit(tmp_path) -> None:
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    registry.register(_record("granola"))

    updated = registry.enter_candidate(
        "granola", candidate_commit="a" * 40, candidate_evidence_id="ev1"
    )

    assert updated.status is FeatureState.CANDIDATE
    assert updated.candidate_commit == "a" * 40
    assert updated.candidate_evidence_id == "ev1"
    assert registry.get("granola").candidate_commit == "a" * 40


def test_enter_candidate_rejects_a_feature_that_is_not_lab(tmp_path) -> None:
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    registry.register(_record("granola"))
    registry.enter_candidate(
        "granola", candidate_commit="a" * 40, candidate_evidence_id="ev1"
    )

    with pytest.raises(InvalidTransitionError):
        registry.enter_candidate(
            "granola", candidate_commit="b" * 40, candidate_evidence_id="ev2"
        )


def test_enter_candidate_unknown_feature_raises(tmp_path) -> None:
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )

    with pytest.raises(KeyError):
        registry.enter_candidate(
            "missing", candidate_commit="a" * 40, candidate_evidence_id="ev1"
        )


def test_missing_journal_event_is_reconciled_from_authoritative_state(tmp_path) -> None:
    class FailingJournal(LifecycleJournal):
        def append_record(self, record):
            raise OSError("audit sink unavailable")

    path = tmp_path / "features.json"
    failing_path = tmp_path / "missing-history.jsonl"
    registry = FeatureRegistry(path, journal=FailingJournal(failing_path))

    registry.register(_record("native"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    event_id = payload["last_event"]["event_id"]

    assert not failing_path.exists()

    repaired_history = tmp_path / "history.jsonl"
    repaired = LifecycleJournal(repaired_history)
    FeatureRegistry(path, journal=repaired)

    assert repaired.contains(event_id)
