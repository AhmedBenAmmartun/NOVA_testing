from __future__ import annotations

from pathlib import Path

import pytest

from nova_lab.history import LifecycleJournal
from nova_lab.models import FeatureState
from nova_lab.registry import FeatureRegistry
from nova_lab.service import DevelopmentService, default_labs_root
from nova_lab.workspace import WorkspaceSafetyError


class FakeWorkspace:
    def __init__(self, *, worktree: Path, clean: bool = True) -> None:
        self.worktree = worktree.resolve()
        self.clean = clean
        self.resolved_refs: list[str] = []

    @staticmethod
    def validate_lab_branch_name(branch: str) -> str:
        if not branch.startswith("lab/"):
            raise WorkspaceSafetyError("bad branch")
        return branch

    @staticmethod
    def validate_base_ref(base_ref: str) -> str:
        if not base_ref or base_ref.startswith("-"):
            raise WorkspaceSafetyError("bad ref")
        return base_ref

    def verify_existing_lab_worktree(self, worktree, *, expected_branch=None):
        path = Path(worktree).resolve()
        if path != self.worktree:
            raise WorkspaceSafetyError("wrong worktree")
        if expected_branch != "lab/example":
            raise WorkspaceSafetyError("wrong branch")
        return path

    def is_clean(self, *, cwd=None) -> bool:
        return self.clean

    def resolve_commit(self, base_ref: str) -> str:
        self.resolved_refs.append(base_ref)
        return "a" * 40

    def is_ancestor(self, ancestor_ref: str, *, cwd=None) -> bool:
        return True


def _service(tmp_path: Path, *, clean: bool = True):
    worktree = tmp_path / "labs" / "example"
    worktree.mkdir(parents=True)
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    workspace = FakeWorkspace(worktree=worktree, clean=clean)
    service = DevelopmentService(
        project_root=tmp_path,
        labs_root=tmp_path / "labs",
        registry=registry,
        workspace=workspace,
    )
    return service, registry, workspace, worktree


def test_default_labs_root_uses_existing_nova_labs_parent(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NOVA_LABS_ROOT", raising=False)
    project = tmp_path / "NOVA-Labs" / "feature"
    project.mkdir(parents=True)

    assert default_labs_root(project) == project.parent.resolve()


def test_empty_status_is_truthful(tmp_path) -> None:
    service, _registry, _workspace, _worktree = _service(tmp_path)
    text = service.status_text()

    assert "registered features: 0" in text
    assert "test execution" in text
    assert "promote" in text


def test_register_existing_feature_enters_lab_only(tmp_path) -> None:
    service, registry, workspace, worktree = _service(tmp_path)

    result = service.register_existing_feature(
        feature_id="example-feature",
        capability_id="class_intelligence",
        name="Example Feature",
        branch="lab/example",
        worktree=str(worktree),
        base_ref="26adfda",
        test_profile="official",
    )

    feature = registry.get("example-feature")
    assert feature is not None
    assert feature.status is FeatureState.LAB
    assert feature.branch == "lab/example"
    assert feature.worktree == str(worktree.resolve())
    assert feature.base_ref == "a" * 40
    assert workspace.resolved_refs == ["26adfda"]
    assert "did not promote" in result


def test_register_rejects_dirty_worktree(tmp_path) -> None:
    service, _registry, _workspace, worktree = _service(tmp_path, clean=False)

    with pytest.raises(WorkspaceSafetyError, match="clean Lab worktree"):
        service.register_existing_feature(
            feature_id="dirty",
            capability_id="class_intelligence",
            name="Dirty",
            branch="lab/example",
            worktree=str(worktree),
            base_ref="HEAD",
        )


def test_register_rejects_unknown_capability_id(tmp_path) -> None:
    service, _registry, _workspace, worktree = _service(tmp_path)

    with pytest.raises(ValueError, match="Unknown capability_id"):
        service.register_existing_feature(
            feature_id="bad-capability",
            capability_id="not_a_real_capability",
            name="Bad Capability",
            branch="lab/example",
            worktree=str(worktree),
            base_ref="HEAD",
        )


def test_register_rejects_unknown_test_profile(tmp_path) -> None:
    service, _registry, _workspace, worktree = _service(tmp_path)

    with pytest.raises(ValueError, match="Unknown test profile"):
        service.register_existing_feature(
            feature_id="bad-profile",
            capability_id="class_intelligence",
            name="Bad Profile",
            branch="lab/example",
            worktree=str(worktree),
            base_ref="HEAD",
            test_profile="whatever.py",
        )


def test_feature_info_and_listing_use_registry_truth(tmp_path) -> None:
    service, _registry, _workspace, worktree = _service(tmp_path)
    service.register_existing_feature(
        feature_id="example-feature",
        capability_id="class_intelligence",
        name="Example Feature",
        branch="lab/example",
        worktree=str(worktree),
        base_ref="HEAD",
    )

    assert "example-feature" in service.list_features_text()
    info = service.feature_info_text("example-feature")
    assert "Status: lab" in info
    assert "Branch: lab/example" in info


def test_v1b_service_has_no_transition_or_execution_surface() -> None:
    names = set(dir(DevelopmentService))
    forbidden = {
        "transition",
        "promote",
        "retire",
        "restart",
        "rollback",
        "delete",
        "run_tests",
        "run_command",
    }
    assert names.isdisjoint(forbidden)


def test_register_rejects_base_that_is_not_ancestor(tmp_path) -> None:
    service, _registry, workspace, worktree = _service(tmp_path)

    workspace.is_ancestor = lambda ancestor_ref, cwd=None: False

    with pytest.raises(WorkspaceSafetyError, match="ancestor"):
        service.register_existing_feature(
            feature_id="wrong-base",
            capability_id="class_intelligence",
            name="Wrong Base",
            branch="lab/example",
            worktree=str(worktree),
            base_ref="HEAD",
        )
