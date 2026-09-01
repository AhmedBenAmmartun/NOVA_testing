"""The permission engine must know WHO is asking.

Today it does not. `run()` takes no actor, all four live call sites pass the
literal string `"voice"`, and the audit record has no actor field. Session
grants are keyed `(session_id, action_name)` -- so the moment NOVA can spawn
internal workers that call tools, three things break at once:

1. A worker's request is byte-for-byte indistinguishable from Ahmed's.
2. One user approval with `scope="session"` would silently authorize unlimited
   *worker* invocations of that action for the rest of the session.
3. After an incident, nothing in `audit_logs/` could attribute the action.

The governing principle in this project is CAPABILITY != PERMISSION: the model
may request, trusted code decides. A principal is what makes that decidable.
It is minted by trusted code and can never be set from model output or tool
arguments -- otherwise the model would simply claim to be the user.

These tests are behavioral, not source-string matching. The existing security
contract tests assert on source text, which would keep passing even if the
engine were behaviorally broken.
"""

from __future__ import annotations

import asyncio

import pytest

from nova_policy.engine import (
    ActionPolicy,
    PermissionEngine,
    PermissionLevel,
    Principal,
)


@pytest.fixture
def engine(tmp_path) -> PermissionEngine:
    built = PermissionEngine(audit_path=tmp_path / "audit.jsonl")
    built.register(
        ActionPolicy(
            name="reversible_thing",
            level=PermissionLevel.REVERSIBLE,
            confirmation_message="",
        )
    )
    built.register(
        ActionPolicy(
            name="sensitive_thing",
            level=PermissionLevel.SENSITIVE,
            confirmation_message="Do the sensitive thing?",
            allow_session_approval=True,
        )
    )
    return built


async def _ok() -> str:
    return "executed"


def _audit_text(tmp_path) -> str:
    path = tmp_path / "audit.jsonl"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --- the principal itself ----------------------------------------------------


def test_a_user_principal_and_a_worker_principal_are_not_equal() -> None:
    assert Principal.user() != Principal.worker("research-1")


def test_a_worker_records_who_spawned_it() -> None:
    """Attribution needs the chain, not just the leaf."""
    worker = Principal.worker("research-1", parent="user")

    assert worker.parent == "user"
    assert not worker.is_user


def test_only_a_user_principal_reports_as_user() -> None:
    assert Principal.user().is_user
    assert not Principal.worker("w").is_user
    assert not Principal.system("scheduler").is_user


# --- authority --------------------------------------------------------------


def test_a_worker_cannot_invoke_a_policy_it_is_not_granted(engine) -> None:
    """Default is user-only. A policy must opt in to worker invocation."""
    result = asyncio.run(
        engine.run(
            "reversible_thing",
            "summary",
            _ok,
            principal=Principal.worker("research-1"),
        )
    )

    assert "executed" not in result


def test_a_user_can_invoke_the_same_policy(engine) -> None:
    result = asyncio.run(
        engine.run("reversible_thing", "summary", _ok, principal=Principal.user())
    )

    assert "executed" in result


def test_a_policy_can_explicitly_admit_workers(engine) -> None:
    engine.register(
        ActionPolicy(
            name="worker_safe",
            level=PermissionLevel.REVERSIBLE,
            worker_invocable=True,
        )
    )

    result = asyncio.run(
        engine.run("worker_safe", "summary", _ok, principal=Principal.worker("w"))
    )

    assert "executed" in result


# --- the session-grant leak (the load-bearing test) -------------------------


def test_a_user_session_grant_does_not_authorize_a_worker(engine) -> None:
    """The single most important property in this file.

    Ahmed approving something "for this session" must not hand that authority
    to every worker NOVA spawns afterwards.
    """
    user = Principal.user()
    pending = asyncio.run(
        engine.run("sensitive_thing", "summary", _ok, principal=user)
    )
    assert "executed" not in pending

    asyncio.run(engine.approve(scope="session", principal=user))

    # The user now has a standing grant. A worker must not inherit it.
    worker_result = asyncio.run(
        engine.run(
            "sensitive_thing",
            "summary",
            _ok,
            principal=Principal.worker("research-1"),
        )
    )

    assert "executed" not in worker_result


def test_a_user_session_grant_still_works_for_the_user(engine) -> None:
    """The fix must not break the feature it protects."""
    user = Principal.user()
    asyncio.run(engine.run("sensitive_thing", "summary", _ok, principal=user))
    asyncio.run(engine.approve(scope="session", principal=user))

    again = asyncio.run(
        engine.run("sensitive_thing", "summary", _ok, principal=user)
    )

    assert "executed" in again


# --- self-authorization ------------------------------------------------------


def test_a_worker_cannot_approve_a_pending_action(engine) -> None:
    """Enforced in the engine, not by omitting a @function_tool decorator.

    A worker that could approve its own request would make every confirmation
    tier decorative.
    """
    user = Principal.user()
    asyncio.run(engine.run("sensitive_thing", "summary", _ok, principal=user))

    result = asyncio.run(engine.approve(principal=Principal.worker("research-1")))

    assert "executed" not in result


def test_a_worker_approval_attempt_is_audited(engine, tmp_path) -> None:
    """An attempt to self-authorize is exactly what an incident review needs."""
    user = Principal.user()
    asyncio.run(engine.run("sensitive_thing", "summary", _ok, principal=user))
    asyncio.run(engine.approve(principal=Principal.worker("sneaky")))

    assert "sneaky" in _audit_text(tmp_path)


# --- attribution -------------------------------------------------------------


def test_the_audit_record_names_the_principal(engine, tmp_path) -> None:
    asyncio.run(
        engine.run("reversible_thing", "summary", _ok, principal=Principal.user())
    )

    assert "principal" in _audit_text(tmp_path)


def test_the_audit_record_preserves_the_delegation_chain(engine, tmp_path) -> None:
    engine.register(
        ActionPolicy(
            name="worker_safe",
            level=PermissionLevel.REVERSIBLE,
            worker_invocable=True,
        )
    )

    asyncio.run(
        engine.run(
            "worker_safe",
            "summary",
            _ok,
            principal=Principal.worker("research-1", parent="user"),
        )
    )

    assert "research-1" in _audit_text(tmp_path)


# --- the model must not be able to claim identity ---------------------------


def test_a_principal_rejects_an_unknown_kind() -> None:
    """Principals are minted by trusted constructors, not parsed from input.

    If the model could hand over an arbitrary kind as a tool argument, the
    whole boundary would be decorative.
    """
    with pytest.raises((TypeError, ValueError)):
        Principal(kind="administrator", id="forged")


def test_the_default_principal_is_not_silently_the_user(engine) -> None:
    """`run()` must not let a caller omit the principal and be treated as Ahmed."""
    with pytest.raises(TypeError):
        asyncio.run(engine.run("reversible_thing", "summary", _ok))
