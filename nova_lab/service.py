"""Model-facing-safe service layer for NOVA Lab V1B/V1C.

This layer exposes inspection and registration of existing isolated Lab
worktrees, running their approved test profile as a non-blocking background
job, inspecting durable test evidence, and preparing an exact passing commit
as a CANDIDATE. It deliberately does not expose a generic lifecycle
transition, production activation, restart, rollback, deletion, or arbitrary
shell/subprocess arguments. It never mints or accepts a `nova_policy`
Principal -- that stays in the trusted tool layer (`tools/development.py`),
exactly like every other NOVA tool module.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from nova_os.capabilities import CANONICAL_CAPABILITY_IDS
from nova_runtime import JobState

from .evidence import TestEvidenceRecord, TestEvidenceStore, now_iso, summarize_test_output
from .models import FeatureRecord, FeatureState
from .registry import FeatureRegistry, default_state_root
from .testing import APPROVED_TEST_PROFILES, ApprovedTestRunner
from .workspace import GitWorkspace, WorkspaceSafetyError

if TYPE_CHECKING:
    from nova_runtime import NovaRuntime


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
        runtime: "NovaRuntime | None" = None,
        evidence_store: TestEvidenceStore | None = None,
        test_runner: ApprovedTestRunner | None = None,
    ) -> None:
        self.project_root = Path(project_root or default_project_root()).resolve()
        self.labs_root = Path(labs_root or default_labs_root(self.project_root)).resolve()
        self.registry = registry or FeatureRegistry()
        self.workspace = workspace or GitWorkspace(
            repo_root=self.project_root,
            labs_root=self.labs_root,
        )
        # Runtime is per-session, injected by trusted code (agent.py), never a
        # process-global singleton -- see DevelopmentController wiring notes
        # in docs/NOVA-LAB-LIFECYCLE.md. None is valid for the stateless V1B
        # inspection/registration tools, which never touch background jobs.
        self.runtime = runtime
        self._evidence = evidence_store or TestEvidenceStore(
            default_state_root() / "evidence.jsonl"
        )
        self._runner = test_runner or ApprovedTestRunner(labs_root=self.labs_root)
        # Maps a public NOVA Lab job id (handed to the model) to the
        # BackgroundJobManager's own internal snapshot id. In-memory and
        # per-instance: jobs are inherently scoped to one NovaRuntime/session.
        self._job_index: dict[str, str] = {}

    def status_text(self) -> str:
        features = self.registry.list()
        counts = Counter(feature.status.value for feature in features)
        return (
            "NOVA Lab status:\n"
            f"- registered features: {len(features)}\n"
            f"- LAB: {counts.get(FeatureState.LAB.value, 0)}\n"
            f"- CANDIDATE: {counts.get(FeatureState.CANDIDATE.value, 0)}\n"
            f"- ACTIVE: {counts.get(FeatureState.ACTIVE.value, 0)}\n"
            f"- RETIRED: {counts.get(FeatureState.RETIRED.value, 0)}\n"
            "- model-facing authority: inspect/register metadata, run an "
            "approved test profile as a background job, inspect durable test "
            "evidence, and prepare an exact passing commit as a CANDIDATE\n"
            "- unavailable here: ACTIVE promotion, retirement, restart, "
            "rollback, deletion, arbitrary shell/subprocess, self-approval"
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

    async def dispatch_test_job(self, feature_id: str, test_profile: str) -> str:
        """Re-verify everything and start an approved test profile as a
        non-blocking NovaRuntime background job.

        Trusted-code entry point only -- the caller (a `tools/development.py`
        function_tool) is responsible for the `nova_policy` gate before this
        runs. This method never accepts or mints a Principal.
        """
        if self.runtime is None:
            raise RuntimeError(
                "NOVA Lab background jobs are not available in this context "
                "(no NovaRuntime was injected)."
            )

        feature_id = _identifier(feature_id, field="feature_id")
        feature = self.registry.get(feature_id)
        if feature is None:
            return f"Unknown NOVA Lab feature '{feature_id}'."
        if feature.status is not FeatureState.LAB:
            return (
                f"NOVA Lab feature '{feature_id}' is not in LAB "
                f"(current status: {feature.status.value}); only a LAB "
                "feature can start a new test job."
            )

        profile = str(test_profile).strip().lower()
        if profile not in APPROVED_TEST_PROFILES:
            allowed = ", ".join(sorted(APPROVED_TEST_PROFILES))
            return f"Unknown test profile '{profile}'. Allowed: {allowed}"

        try:
            worktree_path = self.workspace.verify_existing_lab_worktree(
                feature.worktree,
                expected_branch=feature.branch,
            )
            if not self.workspace.is_clean(cwd=worktree_path):
                raise WorkspaceSafetyError(
                    "The Lab worktree has uncommitted changes."
                )
            if not self.workspace.is_ancestor(feature.base_ref, cwd=worktree_path):
                raise WorkspaceSafetyError(
                    "The feature's recorded base commit is no longer an "
                    "ancestor of Lab HEAD."
                )
            head_before = self.workspace.head(cwd=worktree_path)
        except WorkspaceSafetyError as error:
            return f"NOVA Lab cannot start a test job: {error}"

        public_job_id = secrets.token_hex(8)
        started_at = now_iso()

        async def _run() -> str:
            result = await asyncio.to_thread(
                self._runner.run,
                profile=profile,
                worktree=worktree_path,
            )

            # TOCTOU guard: if the worktree moved while the job was running,
            # the commit that was actually tested is no longer knowable with
            # confidence, so this run cannot become trusted candidate
            # evidence. Fail loudly instead of recording it as either a pass
            # or a fail for the wrong commit.
            head_after = self.workspace.head(cwd=worktree_path)
            if head_after != head_before:
                raise WorkspaceSafetyError(
                    "Lab worktree HEAD changed while the test job was "
                    "running; discarding this run instead of recording "
                    "untrustworthy evidence."
                )

            evidence = TestEvidenceRecord(
                evidence_id=secrets.token_hex(12),
                feature_id=feature_id,
                capability_id=feature.capability_id,
                commit_sha=head_before,
                branch=feature.branch,
                test_profile=profile,
                passed=result.passed,
                returncode=result.returncode,
                started_at=started_at,
                completed_at=now_iso(),
                summary=summarize_test_output(
                    returncode=result.returncode, stdout=result.stdout
                ),
                job_id=public_job_id,
            )
            self._evidence.record(evidence)
            return evidence.evidence_id

        runtime_job_id = await self.runtime.jobs.start(
            name=f"nova_lab_test:{public_job_id}",
            awaitable=_run(),
        )
        self._job_index[public_job_id] = runtime_job_id

        return (
            f"Started NOVA Lab test job '{public_job_id}' for feature "
            f"'{feature_id}' (profile '{profile}', commit "
            f"{head_before[:12]}). This runs in the background and does not "
            "block this conversation. Check "
            f"get_lab_test_job_status('{public_job_id}') for progress."
        )

    async def job_status_text(self, job_id: str) -> str:
        if self.runtime is None:
            raise RuntimeError(
                "NOVA Lab background jobs are not available in this context "
                "(no NovaRuntime was injected)."
            )

        cleaned_id = str(job_id).strip()
        runtime_job_id = self._job_index.get(cleaned_id)
        snapshot = (
            self.runtime.jobs.snapshot(runtime_job_id)
            if runtime_job_id is not None
            else None
        )
        if snapshot is None:
            return f"Unknown NOVA Lab test job '{cleaned_id}'."

        lines = [
            f"Job: {cleaned_id}",
            f"State: {snapshot.state.value}",
        ]
        if snapshot.error:
            lines.append(f"Error: {snapshot.error}")
        if snapshot.state is JobState.COMPLETED and isinstance(snapshot.result, str):
            lines.append(f"Evidence id: {snapshot.result}")
        return "\n".join(lines)

    def evidence_text(self, evidence_id: str) -> str:
        evidence = self._evidence.get(str(evidence_id).strip())
        if evidence is None:
            return f"Unknown NOVA Lab test evidence '{evidence_id}'."
        return (
            f"Evidence: {evidence.evidence_id}\n"
            f"Feature: {evidence.feature_id}\n"
            f"Capability: {evidence.capability_id}\n"
            f"Commit: {evidence.commit_sha}\n"
            f"Branch: {evidence.branch}\n"
            f"Test profile: {evidence.test_profile}\n"
            f"Passed: {evidence.passed}\n"
            f"Return code: {evidence.returncode}\n"
            f"Started: {evidence.started_at}\n"
            f"Completed: {evidence.completed_at}\n"
            f"Job id: {evidence.job_id or 'not recorded'}\n"
            f"Summary: {evidence.summary or '(none)'}"
        )

    async def dispatch_prepare_candidate(self, feature_id: str, evidence_id: str) -> str:
        """Re-verify every candidate gate and, only if all pass, transition
        the feature LAB -> CANDIDATE with the exact commit and evidence that
        justified it.

        Trusted-code entry point only -- the caller is responsible for the
        `nova_policy` gate before this runs. This is not production approval:
        it records that one exact commit passed NOVA's trusted gates and is
        eligible to be presented to Ahmed for a future release decision.
        """
        feature_id = _identifier(feature_id, field="feature_id")
        feature = self.registry.get(feature_id)
        if feature is None:
            return f"Unknown NOVA Lab feature '{feature_id}'."
        if feature.status is not FeatureState.LAB:
            return (
                f"NOVA Lab feature '{feature_id}' is not in LAB "
                f"(current status: {feature.status.value}); only a LAB "
                "feature can become a CANDIDATE."
            )

        evidence = self._evidence.get(str(evidence_id).strip())
        if evidence is None:
            return f"Unknown NOVA Lab test evidence '{evidence_id}'."
        if evidence.feature_id != feature_id:
            return "That test evidence does not belong to this feature."
        if evidence.capability_id != feature.capability_id:
            return (
                "That test evidence capability does not match this feature."
            )
        if evidence.branch != feature.branch:
            return "That test evidence branch does not match this feature."
        if evidence.test_profile != feature.test_profile:
            return (
                f"That test evidence used profile '{evidence.test_profile}', "
                f"but this feature requires '{feature.test_profile}'."
            )
        if not evidence.passed:
            return (
                "That test evidence did not pass; a feature cannot become a "
                "CANDIDATE from failing evidence."
            )

        try:
            worktree_path = self.workspace.verify_existing_lab_worktree(
                feature.worktree,
                expected_branch=feature.branch,
            )
            if not self.workspace.is_clean(cwd=worktree_path):
                raise WorkspaceSafetyError(
                    "The Lab worktree has uncommitted changes."
                )
            current_head = self.workspace.head(cwd=worktree_path)
        except WorkspaceSafetyError as error:
            return f"NOVA Lab cannot prepare a candidate: {error}"

        if evidence.commit_sha != current_head:
            return (
                "That test evidence is stale: it was recorded for commit "
                f"{evidence.commit_sha[:12]}, but the Lab worktree is now at "
                f"{current_head[:12]}. Run the tests again at the current "
                "commit before preparing a candidate."
            )

        self.registry.enter_candidate(
            feature_id,
            candidate_commit=current_head,
            candidate_evidence_id=evidence.evidence_id,
        )

        return (
            f"Feature '{feature_id}' is now a CANDIDATE at commit "
            f"{current_head[:12]} (evidence {evidence.evidence_id}). This "
            "makes it eligible to be presented to Ahmed for a future release "
            "decision; it does not activate, restart, or roll back "
            "production, and NOVA cannot approve that step itself."
        )
