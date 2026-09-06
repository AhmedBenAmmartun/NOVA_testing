"""Inactive model-callable NOVA Lab V1B inspection/registration tools."""

from __future__ import annotations

from livekit.agents import function_tool

from nova_lab.service import DevelopmentService


def _service() -> DevelopmentService:
    # Construct lazily so merely importing the capability has no registry or
    # Git side effects during normal NOVA startup.
    return DevelopmentService()


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


DEVELOPMENT_TOOLS = (
    lab_status,
    list_lab_features,
    get_lab_feature,
    list_lab_test_profiles,
    register_lab_feature,
)
