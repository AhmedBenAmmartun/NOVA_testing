from __future__ import annotations

import pytest

from nova_lab.models import FeatureRecord, FeatureState, InvalidTransitionError


def _feature(status: FeatureState = FeatureState.LAB) -> FeatureRecord:
    return FeatureRecord(
        feature_id="granola-class-provider",
        capability_id="class_capture",
        name="Granola Class Provider",
        status=status,
        branch="lab/granola-class-provider",
    )


def test_lifecycle_requires_candidate_before_active() -> None:
    with pytest.raises(InvalidTransitionError):
        _feature().transition(FeatureState.ACTIVE)


def test_normal_lifecycle_is_supported() -> None:
    candidate = _feature().transition(FeatureState.CANDIDATE)
    active = candidate.transition(FeatureState.ACTIVE)
    retired = active.transition(FeatureState.RETIRED)

    assert candidate.status is FeatureState.CANDIDATE
    assert active.status is FeatureState.ACTIVE
    assert active.promoted_at
    assert retired.status is FeatureState.RETIRED
    assert retired.retired_at


def test_candidate_can_return_to_lab() -> None:
    candidate = _feature().transition(FeatureState.CANDIDATE)
    assert candidate.transition(FeatureState.LAB).status is FeatureState.LAB


def test_retired_feature_can_be_reopened_in_lab() -> None:
    feature = (
        _feature()
        .transition(FeatureState.CANDIDATE)
        .transition(FeatureState.ACTIVE)
        .transition(FeatureState.RETIRED)
    )
    reopened = feature.transition(FeatureState.LAB)
    assert reopened.status is FeatureState.LAB
    assert reopened.retired_at is None
