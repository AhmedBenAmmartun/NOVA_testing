"""Permission-management tools exposed to NOVA.

Approval is deliberately excluded from the model-callable tool surface.
Only a trusted user interface may grant a pending action. The model may list
pending actions, deny one, or make Safe Mode stricter by enabling it.
"""

from livekit.agents import RunContext, function_tool

from nova_policy import permission_engine


@function_tool()
async def list_pending_actions(
    context: RunContext,
) -> str:
    """List NOVA actions currently waiting for trusted user approval."""
    return permission_engine.list_pending()


@function_tool()
async def deny_action(
    context: RunContext,
    action_id: str = "latest",
) -> str:
    """Deny and cancel a pending NOVA action."""
    return permission_engine.deny(action_id=action_id)


@function_tool()
async def enable_nova_safe_mode(
    context: RunContext,
) -> str:
    """Enable NOVA Safe Mode. Disabling it requires a trusted UI action."""
    return permission_engine.set_safe_mode(enabled=True)


# Compatibility-only callables. These are intentionally NOT decorated with
# @function_tool, so the LLM cannot grant permissions or weaken Safe Mode.
async def set_nova_safe_mode(
    context: RunContext,
    enabled: bool,
) -> str:
    del context
    if enabled:
        return permission_engine.set_safe_mode(enabled=True)
    return (
        "Safe Mode can only be disabled from NOVA's trusted permission "
        "interface, not by the AI model."
    )
