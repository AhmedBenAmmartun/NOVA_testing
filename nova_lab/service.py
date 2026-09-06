"""Model-facing-safe service layer for NOVA Lab V1B.

This layer exposes inspection and registration of existing isolated Lab
worktrees. It deliberately does not expose lifecycle transitions, production
activation, restart, rollback, deletion, arbitrary shell, or test execution.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from nova_os.capabilities import CANONICAL_CAPABILITY_IDS

from .models import FeatureRecord, FeatureState
from .registry import FeatureRegistry
from .testing import APPROVED_TEST_PROFILES
from .workspace import GitWorkspace, WorkspaceSafetyError


_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def default_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_labs_root(project_root: Path | str | None = None) -> Path:
    override = os.getenv("NOVA_LABS_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    root = Path(project_root or default_project_root()).resolve()
    if root.parent.name.lower() == "nova-labs":
        return root.parent
    return root.parent / "NOVA-Labs"


def _identifier(value: str, *, field: str) -> str:
    cleaned = str(value).strip().lower().replace(" ", "-")
    if not _SAFE_ID.fullmatch(cleaned):
        raise ValueError(
            f"{field} must use only lowercase letters, numbers, '-' or '_', "
            "start with a letter/number, and be at most 80 characters."
        )
    return cleaned


def _display_name(value: str) -> str:
    cleaned = " ".join(str(value).replace("\r", " ").replace("\n", " ").split())
    if not cleaned:
        raise ValueError("name cannot be empty")
    return cleaned[:120]


class DevelopmentService:
    """Safe V1B bridge between model tools and NOVA Lab state."""

    def __init__(
        self,
        *,
        project_root: Path | str | None = None,
        labs_root: Path | str | None = None,
        registry: FeatureRegistry | None = None,
        workspace: GitWorkspace | None = None,
    ) -> None:
        self.project_root = Path(project_root or default_project_root()).resolve()
        self.labs_root = Path(labs_root or default_labs_root(self.project_root)).resolve()
        self.registry = registry or FeatureRegistry()
        self.workspace = workspace or GitWorkspace(
            repo_root=self.project_root,
            labs_root=self.labs_root,
        )

    def status_text(self) -> str:
        features = self.registry.list()
        counts = Counter(feature.status.value for feature in features)
        return (
            "NOVA Lab V1B status:\n"
            f"- registered features: {len(features)}\n"
            f"- LAB: {counts.get(FeatureState.LAB.value, 0)}\n"
            f"- CANDIDATE: {counts.get(FeatureState.CANDIDATE.value, 0)}\n"
            f"- ACTIVE: {counts.get(FeatureState.ACTIVE.value, 0)}\n"
            f"- RETIRED: {counts.get(FeatureState.RETIRED.value, 0)}\n"
            "- model-facing V1B authority: inspect/register metadata only\n"
            "- unavailable here: promote, retire, restart, rollback, delete, shell, test execution"
        )

    def list_features_text(self) -> str:
        features = self.registry.list()
        if not features:
            return "No NOVA Lab features are registered yet."

        lines = ["Registered NOVA Lab features:"]
        for feature in features:
            lines.append(
                f"- {feature.feature_id}: {feature.name} "
                f"[{feature.status.value}; capability={feature.capability_id}; "
                f"branch={feature.branch}; tests={feature.test_profile}]"
            )
        return "\n".join(lines)

    def feature_info_text(self, feature_id: str) -> str:
        cleaned_id = _identifier(feature_id, field="feature_id")
        feature = self.registry.get(cleaned_id)
        if feature is None:
            return f"Unknown NOVA Lab feature '{cleaned_id}'."

        return (
            f"Feature: {feature.feature_id}\n"
            f"Name: {feature.name}\n"
            f"Capability: {feature.capability_id}\n"
            f"Status: {feature.status.value}\n"
            f"Branch: {feature.branch or 'not recorded'}\n"
            f"Worktree: {feature.worktree or 'not recorded'}\n"
            f"Base ref: {feature.base_ref or 'not recorded'}\n"
            f"Test profile: {feature.test_profile}\n"
            f"Version: {feature.version or 'not recorded'}"
        )

    def test_profiles_text(self) -> str:
        names = ", ".join(sorted(APPROVED_TEST_PROFILES))
        return (
            "Approved NOVA Lab test profiles: "
            f"{names}. V1B can describe these profiles but cannot execute tests."
        )

    def register_existing_feature(
        self,
        *,
        feature_id: str,
        capability_id: str,
        name: str,
        branch: str,
        worktree: str,
        base_ref: str,
        test_profile: str = "official",
    ) -> str:
        feature_id = _identifier(feature_id, field="feature_id")
        capability_id = _identifier(capability_id, field="capability_id")
        name = _display_name(name)

        if capability_id not in CANONICAL_CAPABILITY_IDS:
            raise ValueError(
                f"Unknown capability_id '{capability_id}'. It must match a "
                "capability already registered in NOVA's capability catalog."
            )

        if self.registry.get(feature_id) is not None:
            return f"NOVA Lab feature '{feature_id}' is already registered."

        branch = self.workspace.validate_lab_branch_name(branch)
        base_ref = self.workspace.validate_base_ref(base_ref)

        profile = str(test_profile).strip().lower()
        if profile not in APPROVED_TEST_PROFILES:
            allowed = ", ".join(sorted(APPROVED_TEST_PROFILES))
            raise ValueError(f"Unknown test profile '{profile}'. Allowed: {allowed}")

        worktree_path = self.workspace.verify_existing_lab_worktree(
            worktree,
            expected_branch=branch,
        )
        if not self.workspace.is_clean(cwd=worktree_path):
            raise WorkspaceSafetyError(
                "A feature must be registered from a clean Lab worktree. "
                "Checkpoint or revert its experiment changes first."
            )

        resolved_base = self.workspace.resolve_commit(base_ref)
        if not self.workspace.is_ancestor(resolved_base, cwd=worktree_path):
            raise WorkspaceSafetyError(
                "The recorded base commit must be an ancestor of the Lab worktree HEAD."
            )

        feature = FeatureRecord(
            feature_id=feature_id,
            capability_id=capability_id,
            name=name,
            status=FeatureState.LAB,
            branch=branch,
            worktree=str(worktree_path),
            base_ref=resolved_base,
            test_profile=profile,
        )
        self.registry.register(feature)

        return (
            f"Registered NOVA Lab feature '{feature_id}' in LAB state. "
            "This changed Lab metadata only; it did not promote, restart, "
            "modify production, or run tests."
        )
