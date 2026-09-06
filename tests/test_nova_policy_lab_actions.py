"""NOVA Lab's V1C actions must be real, correctly-scoped policies -- not just
tool-layer conventions.

Two checks live here:

1. Against the REAL global `permission_engine` singleton, read-only: the
   named policies exist with the exact level/worker_invocable NOVA Lab's
   tools rely on. This never calls `.run()` against the singleton, so it
   never writes to the real `audit_logs/nova_actions.jsonl`.
2. Against an isolated, throwaway `PermissionEngine` registered with policies
   of the same shape, exercising the actual authorization behavior (worker
   admitted, Safe Mode blocks it, an unrelated non-opted-in worker action is
   still denied) -- mirroring `tests/test_nova_permission_principal.py`'s own
   pattern so this file never mutates real global/audit state.
"""

from __future__ import annotations

import asyncio

from nova_policy import permission_engine
from nova_policy.engine import ActionPolicy, PermissionEngine, PermissionLevel, Principal


def test_lab_actions_are_registered_reversible_and_worker_invocable() -> None:
    for name in ("nova_lab_run_test_job", "nova_lab_prepare_candidate"):
        policy = permission_engine.get_policy(name)
        assert policy is not None, f"missing ActionPolicy for {name}"
        assert policy.level is PermissionLevel.REVERSIBLE
        assert policy.worker_invocable is True


async def _ok() -> str:
    return "executed"


def _isolated_engine(tmp_path) -> PermissionEngine:
    engine = PermissionEngine(audit_path=tmp_path / "audit.jsonl")
    for name in ("nova_lab_run_test_job", "nova_lab_prepare_candidate"):
        engine.register(
            ActionPolicy(name=name, level=PermissionLevel.REVERSIBLE, worker_invocable=True)
        )
    engine.register(
        ActionPolicy(name="some_other_worker_action", level=PermissionLevel.REVERSIBLE)
    )
    return engine


def test_the_nova_lab_worker_can_run_a_test_job(tmp_path) -> None:
    engine = _isolated_engine(tmp_path)

    result = asyncio.run(
        engine.run(
            "nova_lab_run_test_job",
            "summary",
            _ok,
            principal=Principal.worker(id="nova_lab"),
        )
    )

    assert "executed" in result


def test_the_nova_lab_worker_can_prepare_a_candidate(tmp_path) -> None:
    engine = _isolated_engine(tmp_path)

    result = asyncio.run(
        engine.run(
            "nova_lab_prepare_candidate",
            "summary",
            _ok,
            principal=Principal.worker(id="nova_lab"),
        )
    )

    assert "executed" in result


def test_a_different_worker_action_without_opt_in_is_still_denied(tmp_path) -> None:
    """Being worker-invocable for NOVA Lab's own actions does not blanket-admit
    workers to actions that never opted in."""
    engine = _isolated_engine(tmp_path)

    result = asyncio.run(
        engine.run(
            "some_other_worker_action",
            "summary",
            _ok,
            principal=Principal.worker(id="nova_lab"),
        )
    )

    assert "executed" not in result


def test_safe_mode_blocks_nova_lab_test_execution(tmp_path) -> None:
    engine = _isolated_engine(tmp_path)
    engine.set_safe_mode(True)

    result = asyncio.run(
        engine.run(
            "nova_lab_run_test_job",
            "summary",
            _ok,
            principal=Principal.worker(id="nova_lab"),
        )
    )

    assert "executed" not in result
    assert "Safe Mode" in result


def test_safe_mode_blocks_candidate_preparation(tmp_path) -> None:
    engine = _isolated_engine(tmp_path)
    engine.set_safe_mode(True)

    result = asyncio.run(
        engine.run(
            "nova_lab_prepare_candidate",
            "summary",
            _ok,
            principal=Principal.worker(id="nova_lab"),
        )
    )

    assert "executed" not in result
    assert "Safe Mode" in result
