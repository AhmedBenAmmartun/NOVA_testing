"""Inactive model-callable NOVA Lab inspection/registration/test-gate tools."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool

from nova_lab.service import DevelopmentService
from nova_policy import Principal, permission_engine


def _service() -> DevelopmentService:
    # Construct lazily so merely importing the capability has no registry or
    # Git side effects during normal NOVA startup. Stateless: these tools
    # never touch a background job, so a fresh instance per call is safe.
    return DevelopmentService()


def _session_service(context: RunContext) -> DevelopmentService:
    """The one shared, per-session DevelopmentService (holds the injected
    NovaRuntime and in-memory job index) -- required for job/candidate tools,
    which cannot use a fresh-per-call instance the way the stateless
    inspection tools above do.
    """
    session = getattr(context, "session", None)
    if session is None:
        raise RuntimeError("NOVA Lab tools could not access the active LiveKit session.")

    try:
        agent = session.current_agent
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeError("NOVA Lab tools could not access the active agent.") from exc

    service = getattr(agent, "nova_lab_service", None)
    if service is None:
        raise RuntimeError("NOVA Lab background-job service is not attached to the active agent.")
    return service


@function_tool()
async def lab_status() -> str:
    """Summarize NOVA Lab lifecycle state and the authority available in V1B."""
    return _service().status_text()


@function_tool()
async def list_lab_features() -> str:
    """List NOVA Lab features already registered in the local lifecycle registry."""
    return _service().list_features_text()


@function_tool()
async def get_lab_feature(feature_id: str) -> str:
    """Inspect one registered NOVA Lab feature by its feature id."""
    return _service().feature_info_text(feature_id)


@function_tool()
async def list_lab_test_profiles() -> str:
    """List approved NOVA Lab test profiles without executing any tests."""
    return _service().test_profiles_text()


@function_tool()
async def register_lab_feature(
    feature_id: str,
    capability_id: str,
    name: str,
    branch: str,
    worktree: str,
    base_ref: str,
    test_profile: str = "official",
) -> str:
    """Register an existing clean isolated lab/* worktree as a LAB feature.

    This records metadata only. It cannot create or edit source code, run tests,
    transition lifecycle state, promote a feature, restart NOVA, roll back a
    release, delete files, or execute shell commands.
    """
    return _service().register_existing_feature(
        feature_id=feature_id,
        capability_id=capability_id,
        name=name,
        branch=branch,
        worktree=worktree,
        base_ref=base_ref,
        test_profile=test_profile,
    )


@function_tool()
async def start_lab_test_job(
    context: RunContext,
    feature_id: str,
    test_profile: str = "official",
) -> str:
    """Start an approved NOVA Lab test profile for a registered LAB feature as
    a non-blocking background job.

    Only named, pre-approved test profiles may run, and only inside a
    re-verified, clean, isolated lab/* worktree under the approved NOVA Labs
    root. This does not edit source, run arbitrary commands, transition
    lifecycle state, or grant any production authority. Returns immediately
    with a job id; use get_lab_test_job_status to check progress.
    """
    service = _session_service(context)
    return await permission_engine.run(
        action_name="nova_lab_run_test_job",
        summary=f"Run NOVA Lab test profile '{test_profile}' for feature '{feature_id}'",
        session_id="nova_lab",
        # NOVA Lab test execution is the agent's own internal development
        # automation, not a direct command from Ahmed's conversation --
        # minted here in trusted code, never accepted from a tool argument.
        principal=Principal.worker(id="nova_lab"),
        executor=lambda: service.dispatch_test_job(feature_id, test_profile),
    )


@function_tool()
async def get_lab_test_job_status(context: RunContext, job_id: str) -> str:
    """Check the status of a previously started NOVA Lab test job."""
    service = _session_service(context)
    return await service.job_status_text(job_id)


@function_tool()
async def get_lab_test_evidence(context: RunContext, evidence_id: str) -> str:
    """Inspect durable NOVA Lab test evidence by its evidence id."""
    service = _session_service(context)
    return service.evidence_text(evidence_id)


@function_tool()
async def prepare_lab_candidate(
    context: RunContext,
    feature_id: str,
    evidence_id: str,
) -> str:
    """Prepare a LAB feature as a CANDIDATE after its required test evidence
    has passed for the exact current commit.

    This records that one exact commit passed NOVA's trusted gates and is
    eligible to be presented to Ahmed for a future release decision. It does
    not activate, restart, or roll back production, and NOVA can never
    approve that step itself -- only Ahmed can.
    """
    service = _session_service(context)
    return await permission_engine.run(
        action_name="nova_lab_prepare_candidate",
        summary=f"Prepare NOVA Lab feature '{feature_id}' as a CANDIDATE",
        session_id="nova_lab",
        # Same reasoning as start_lab_test_job: this is NOVA's own gated
        # development automation, principaled as a worker, never the model
        # claiming to be Ahmed.
        principal=Principal.worker(id="nova_lab"),
        executor=lambda: service.dispatch_prepare_candidate(feature_id, evidence_id),
    )


DEVELOPMENT_TOOLS = (
    lab_status,
    list_lab_features,
    get_lab_feature,
    list_lab_test_profiles,
    register_lab_feature,
    start_lab_test_job,
    get_lab_test_job_status,
    get_lab_test_evidence,
    prepare_lab_candidate,
)
