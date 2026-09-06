from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

from nova_lab.evidence import (
    TestEvidenceRecord as EvidenceRecord,
    TestEvidenceStore as EvidenceStore,
    now_iso,
)
from nova_lab.history import LifecycleJournal
from nova_lab.models import FeatureRecord, FeatureState
from nova_lab.registry import FeatureRegistry
from nova_lab.service import DevelopmentService
from nova_lab.testing import TestRunResult as RunResult
from nova_lab.workspace import WorkspaceSafetyError
from nova_runtime import JobState, NovaRuntime

_JOB_ID_RE = re.compile(r"test job '([0-9a-f]+)'")


class FakeWorkspace:
    """A minimal stand-in for GitWorkspace: no real Git process is spawned.

    `head()` returns successive values from `head_sequence`, clamped to the
    last entry once exhausted -- a single-value sequence means "HEAD never
    moves"; a two-value sequence lets a test simulate drift between the
    before/after reads inside one test job.
    """

    def __init__(
        self,
        *,
        worktree: Path,
        branch: str = "lab/example",
        clean: bool = True,
        head_sequence: tuple[str, ...] = ("a" * 40,),
        ancestor: bool = True,
    ) -> None:
        self.worktree = worktree.resolve()
        self.branch = branch
        self.clean = clean
        self.head_sequence = list(head_sequence)
        self.ancestor = ancestor
        self.head_calls = 0

    def verify_existing_lab_worktree(self, worktree, *, expected_branch=None):
        path = Path(worktree).resolve()
        if path != self.worktree:
            raise WorkspaceSafetyError("wrong worktree")
        if expected_branch is not None and expected_branch != self.branch:
            raise WorkspaceSafetyError("wrong branch")
        return path

    def is_clean(self, *, cwd=None) -> bool:
        return self.clean

    def is_ancestor(self, ancestor_ref, *, cwd=None) -> bool:
        return self.ancestor

    def head(self, *, cwd=None) -> str:
        index = min(self.head_calls, len(self.head_sequence) - 1)
        value = self.head_sequence[index]
        self.head_calls += 1
        return value


class FakeTestRunner:
    def __init__(
        self,
        *,
        returncode: int = 0,
        stdout: str = "3 passed",
        sleep_seconds: float = 0.0,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.sleep_seconds = sleep_seconds
        self.calls: list[tuple[str, Path]] = []

    def run(self, *, profile: str, worktree: Path, timeout_seconds: int = 900) -> RunResult:
        self.calls.append((profile, worktree))
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return RunResult(
            profile=profile,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr="",
        )


def _build_service(tmp_path, *, workspace, test_runner, runtime=None):
    registry = FeatureRegistry(
        tmp_path / "features.json",
        journal=LifecycleJournal(tmp_path / "history.jsonl"),
    )
    evidence_store = EvidenceStore(tmp_path / "evidence.jsonl")
    service = DevelopmentService(
        project_root=tmp_path,
        labs_root=tmp_path / "labs",
        registry=registry,
        workspace=workspace,
        runtime=runtime,
        evidence_store=evidence_store,
        test_runner=test_runner,
    )
    return service, registry, evidence_store


def _register(
    registry,
    *,
    feature_id="feat",
    worktree,
    branch="lab/example",
    base_ref="a" * 40,
    test_profile="official",
    capability_id="class_intelligence",
) -> FeatureRecord:
    feature = FeatureRecord(
        feature_id=feature_id,
        capability_id=capability_id,
        name="Feature",
        status=FeatureState.LAB,
        branch=branch,
        worktree=str(worktree),
        base_ref=base_ref,
        test_profile=test_profile,
    )
    registry.register(feature)
    return feature


def _worktree(tmp_path) -> Path:
    path = tmp_path / "labs" / "feat"
    path.mkdir(parents=True)
    return path


def _extract_job_id(result_text: str) -> str:
    match = _JOB_ID_RE.search(result_text)
    assert match is not None, result_text
    return match.group(1)


# --- pre-flight validation, no runtime needed ------------------------------


def test_dispatch_test_job_requires_a_runtime(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    service, registry, _ = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree)

    with pytest.raises(RuntimeError, match="NovaRuntime"):
        asyncio.run(service.dispatch_test_job("feat", "official"))


def test_dispatch_test_job_rejects_unapproved_profile(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    runtime = NovaRuntime()
    service, registry, _ = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner(), runtime=runtime
    )
    _register(registry, worktree=worktree)

    result = asyncio.run(service.dispatch_test_job("feat", "whatever.py"))
    assert "Unknown test profile" in result
    asyncio.run(runtime.shutdown())


def test_dispatch_test_job_rejects_a_feature_that_is_not_lab(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    runtime = NovaRuntime()
    service, registry, _ = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner(), runtime=runtime
    )
    _register(registry, worktree=worktree)
    registry.enter_candidate("feat", candidate_commit="a" * 40, candidate_evidence_id="ev0")

    result = asyncio.run(service.dispatch_test_job("feat", "official"))
    assert "not in LAB" in result
    asyncio.run(runtime.shutdown())


def test_dispatch_test_job_rejects_a_dirty_worktree(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, clean=False)
    runtime = NovaRuntime()
    service, registry, _ = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner(), runtime=runtime
    )
    _register(registry, worktree=worktree)

    result = asyncio.run(service.dispatch_test_job("feat", "official"))
    assert "cannot start a test job" in result
    asyncio.run(runtime.shutdown())


# --- the actual background job ---------------------------------------------


def test_successful_job_is_nonblocking_and_records_passing_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    runner = FakeTestRunner(
        returncode=0, stdout="collecting...\n38 passed in 1.0s", sleep_seconds=0.3
    )
    runtime = NovaRuntime()
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=runner, runtime=runtime
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)

    async def scenario():
        start = time.perf_counter()
        result = await service.dispatch_test_job("feat", "official")
        elapsed = time.perf_counter() - start

        internal_id = service._job_index[_extract_job_id(result)]
        await runtime.jobs.wait(internal_id)
        snapshot = runtime.jobs.snapshot(internal_id)
        await runtime.shutdown()
        return result, elapsed, snapshot

    result, elapsed, snapshot = asyncio.run(scenario())

    assert "Started NOVA Lab test job" in result
    # Returned long before the fake 0.3s test run finished -- proves the
    # model-facing call does not block on the actual test execution.
    assert elapsed < 0.1

    assert snapshot.state is JobState.COMPLETED
    evidence = evidence_store.get(snapshot.result)
    assert evidence is not None
    assert evidence.passed is True
    assert evidence.commit_sha == "a" * 40
    assert evidence.feature_id == "feat"
    assert evidence.test_profile == "official"
    assert "38 passed" in evidence.summary


def test_failing_test_produces_failing_not_passing_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    runner = FakeTestRunner(returncode=1, stdout="1 failed, 2 passed")
    runtime = NovaRuntime()
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=runner, runtime=runtime
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)

    async def scenario():
        result = await service.dispatch_test_job("feat", "official")
        internal_id = service._job_index[_extract_job_id(result)]
        await runtime.jobs.wait(internal_id)
        snapshot = runtime.jobs.snapshot(internal_id)
        await runtime.shutdown()
        return snapshot

    snapshot = asyncio.run(scenario())

    assert snapshot.state is JobState.COMPLETED
    evidence = evidence_store.get(snapshot.result)
    assert evidence is not None
    assert evidence.passed is False
    assert evidence.returncode == 1


def test_head_drift_during_job_discards_untrustworthy_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    # First head() read (before the run) returns commit A; the second read
    # (after the run) returns commit B -- simulating the worktree moving
    # while the test job was executing.
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40, "b" * 40))
    runner = FakeTestRunner(returncode=0, stdout="38 passed")
    runtime = NovaRuntime()
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=runner, runtime=runtime
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)

    async def scenario():
        result = await service.dispatch_test_job("feat", "official")
        internal_id = service._job_index[_extract_job_id(result)]
        await runtime.jobs.wait(internal_id)
        snapshot = runtime.jobs.snapshot(internal_id)
        await runtime.shutdown()
        return snapshot

    snapshot = asyncio.run(scenario())

    assert snapshot.state is JobState.FAILED
    assert "HEAD changed" in (snapshot.error or "")
    # No evidence at all -- a run against an unknown commit is not a fact,
    # not a false pass and not a false fail.
    assert evidence_store.list_for_feature("feat") == ()


def test_interrupted_job_produces_no_evidence(tmp_path) -> None:
    """A job whose runner raises never reaches the evidence-recording line."""

    class ExplodingRunner(FakeTestRunner):
        def run(self, *, profile, worktree, timeout_seconds=900):
            raise RuntimeError("simulated crash mid-run")

    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    runtime = NovaRuntime()
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=ExplodingRunner(), runtime=runtime
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)

    async def scenario():
        result = await service.dispatch_test_job("feat", "official")
        internal_id = service._job_index[_extract_job_id(result)]
        await runtime.jobs.wait(internal_id)
        snapshot = runtime.jobs.snapshot(internal_id)
        await runtime.shutdown()
        return snapshot

    snapshot = asyncio.run(scenario())

    assert snapshot.state is JobState.FAILED
    assert evidence_store.list_for_feature("feat") == ()


# --- candidate gating --------------------------------------------------------


def _manual_evidence(evidence_store: EvidenceStore, **overrides) -> EvidenceRecord:
    base = dict(
        evidence_id="ev-manual",
        feature_id="feat",
        capability_id="class_intelligence",
        commit_sha="a" * 40,
        branch="lab/example",
        test_profile="official",
        passed=True,
        returncode=0,
        started_at=now_iso(),
        completed_at=now_iso(),
        summary="ok",
        job_id="",
    )
    base.update(overrides)
    record = EvidenceRecord(**base)
    evidence_store.record(record)
    return record


def test_candidate_requires_evidence_for_this_feature(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)
    evidence = _manual_evidence(evidence_store, feature_id="some-other-feature")

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "does not belong to this feature" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_rejects_capability_mismatched_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(
        registry,
        worktree=worktree,
        base_ref="a" * 40,
        capability_id="class_intelligence",
    )
    evidence = _manual_evidence(
        evidence_store,
        capability_id="development",
        commit_sha="a" * 40,
    )

    outcome = asyncio.run(
        service.dispatch_prepare_candidate("feat", evidence.evidence_id)
    )

    assert "capability does not match" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_rejects_branch_mismatched_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(
        worktree=worktree,
        branch="lab/example",
        head_sequence=("a" * 40,),
    )
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(
        registry,
        worktree=worktree,
        branch="lab/example",
        base_ref="a" * 40,
    )
    evidence = _manual_evidence(
        evidence_store,
        branch="lab/some-other-branch",
        commit_sha="a" * 40,
    )

    outcome = asyncio.run(
        service.dispatch_prepare_candidate("feat", evidence.evidence_id)
    )

    assert "branch does not match" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_requires_the_required_test_profile(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40, test_profile="official")
    evidence = _manual_evidence(evidence_store, test_profile="nova_lab")

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "requires 'official'" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_rejects_failing_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)
    evidence = _manual_evidence(evidence_store, passed=False, returncode=1)

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "did not pass" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_rejects_stale_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    # Evidence claims commit A, but the worktree's current HEAD is B.
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("b" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)
    evidence = _manual_evidence(evidence_store, commit_sha="a" * 40)

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "stale" in outcome.lower()
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_rejects_dirty_worktree(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,), clean=False)
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)
    evidence = _manual_evidence(evidence_store, commit_sha="a" * 40)

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "cannot prepare a candidate" in outcome
    assert registry.get("feat").status is FeatureState.LAB


def test_candidate_records_exact_immutable_commit_and_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)
    evidence = _manual_evidence(evidence_store, commit_sha="a" * 40)

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", evidence.evidence_id))

    assert "is now a CANDIDATE" in outcome
    updated = registry.get("feat")
    assert updated.status is FeatureState.CANDIDATE
    assert updated.candidate_commit == "a" * 40
    assert updated.candidate_evidence_id == evidence.evidence_id

    # The worktree moving on afterwards must not change what was recorded --
    # a future release supervisor reads the frozen candidate_commit, not
    # "whatever HEAD is now".
    workspace.head_sequence = ["c" * 40]
    workspace.head_calls = 0
    assert registry.get("feat").candidate_commit == "a" * 40


def test_candidate_unknown_feature_is_rejected(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    service, _registry, evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    evidence = _manual_evidence(evidence_store, feature_id="missing")

    outcome = asyncio.run(service.dispatch_prepare_candidate("missing", evidence.evidence_id))
    assert "Unknown NOVA Lab feature" in outcome


def test_candidate_unknown_evidence_is_rejected(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree, head_sequence=("a" * 40,))
    service, registry, _evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )
    _register(registry, worktree=worktree, base_ref="a" * 40)

    outcome = asyncio.run(service.dispatch_prepare_candidate("feat", "no-such-evidence"))
    assert "Unknown NOVA Lab test evidence" in outcome
    assert registry.get("feat").status is FeatureState.LAB


# --- job status / evidence text ---------------------------------------------


def test_job_status_text_requires_a_runtime(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    service, _registry, _evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )

    with pytest.raises(RuntimeError, match="NovaRuntime"):
        asyncio.run(service.job_status_text("anything"))


def test_job_status_text_reports_unknown_job(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    runtime = NovaRuntime()
    service, _registry, _evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner(), runtime=runtime
    )

    result = asyncio.run(service.job_status_text("does-not-exist"))
    assert "Unknown NOVA Lab test job" in result
    asyncio.run(runtime.shutdown())


def test_evidence_text_reports_unknown_evidence(tmp_path) -> None:
    worktree = _worktree(tmp_path)
    workspace = FakeWorkspace(worktree=worktree)
    service, _registry, _evidence_store = _build_service(
        tmp_path, workspace=workspace, test_runner=FakeTestRunner()
    )

    assert "Unknown NOVA Lab test evidence" in service.evidence_text("nope")
