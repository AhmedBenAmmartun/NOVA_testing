"""Static Phase 0 regression checks that require only the Python stdlib."""

from __future__ import annotations

from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_agent_has_no_retired_visual_or_self_approval_tools() -> None:
    text = _read("agent.py")
    tree = ast.parse(text)
    assert "ask_specialist" in text
    for name in (
        "capture_screen",
        "analyze_screen_with_gpt56",
        "look_at_screen_locally",
        "start_guardian_vision",
        "stop_guardian_vision",
        "approve_action",
        "set_nova_safe_mode",
    ):
        assert name not in text, f"retired/unsafe model tool still present: {name}"
    assert tree is not None


def test_legacy_vision_module_captures_no_pixels() -> None:
    text = _read("tools/vision.py")
    assert "ImageGrab" not in text
    assert "PIL" not in text
    assert "SCREENSHOT_DIR" not in text
    assert "@function_tool" not in text


def test_transcript_storage_defaults_off() -> None:
    text = _read("tools/conversations.py")
    assert 'NOVA_SAVE_TRANSCRIPTS' in text
    assert 'default=False' in text
    assert 'NOVA_MIRROR_TRANSCRIPTS_TO_OBSIDIAN' in text


def test_model_cannot_approve_or_disable_safe_mode() -> None:
    text = _read("tools/permissions.py")
    decorated_region = text.split("# Compatibility-only callables", 1)[0]
    assert "async def approve_action" not in decorated_region
    assert "async def set_nova_safe_mode" not in decorated_region
    assert "async def enable_nova_safe_mode" in decorated_region
    assert "async def deny_action" in decorated_region


def test_prompt_uses_live_vision_and_one_specialist_tool() -> None:
    text = _read("prompts.py")
    assert "ask_specialist" in text
    assert "ask_gpt56" not in text
    assert "ask_groq" not in text
    assert "ask_ollama" not in text
    assert "analyze_screen_with_gpt56" not in text
    assert "capture_screen" not in text


def test_session_cleanup_removes_pending_state() -> None:
    """Behavioral, not source-matching.

    This previously asserted the literal source text
    ``"pending.session_id == session_id"``, which broke the moment grant keys
    became principal-scoped -- and, worse, would have kept passing if cleanup
    were behaviorally broken while the string survived. The property that
    actually matters is that clearing a session drops its pending actions and
    its standing grants, so assert that instead.
    """
    import asyncio

    from nova_policy.engine import (
        ActionPolicy,
        PermissionEngine,
        PermissionLevel,
        Principal,
    )

    engine = PermissionEngine()
    engine.register(
        ActionPolicy(
            name="cleanup_probe",
            level=PermissionLevel.SENSITIVE,
            confirmation_message="Confirm?",
            allow_session_approval=True,
        )
    )

    async def _work() -> str:
        return "executed"

    user = Principal.user()
    pending = asyncio.run(
        engine.run("cleanup_probe", "probe", _work, principal=user)
    )
    assert "executed" not in pending
    assert engine._pending

    asyncio.run(engine.approve(scope="session", principal=user))
    assert engine._session_grants

    engine.clear_session("voice")

    assert not engine._pending
    assert not engine._session_grants

    # And the standing grant really is gone: the action confirms again.
    again = asyncio.run(
        engine.run("cleanup_probe", "probe", _work, principal=user)
    )
    assert "executed" not in again


def test_agent_registers_shutdown_permission_cleanup() -> None:
    text = _read("agent.py")
    assert "permission_engine.clear_session(bridge_session_id)" in text
    assert 'permission_engine.clear_session("voice")' in text


def _run_direct() -> None:
    tests = [
        test_agent_has_no_retired_visual_or_self_approval_tools,
        test_legacy_vision_module_captures_no_pixels,
        test_transcript_storage_defaults_off,
        test_model_cannot_approve_or_disable_safe_mode,
        test_prompt_uses_live_vision_and_one_specialist_tool,
        test_session_cleanup_removes_pending_state,
        test_agent_registers_shutdown_permission_cleanup,
    ]
    for test in tests:
        test()
    print(f"Phase 0 static contract: {len(tests)} checks passed.")


if __name__ == "__main__":
    _run_direct()
