"""Permission-management tools exposed to NOVA."""

from livekit.agents import RunContext, function_tool

from nova_policy import permission_engine


@function_tool()
async def list_pending_actions(
    context: RunContext,
) -> str:
    """List NOVA actions currently waiting for approval."""

    return permission_engine.list_pending()


@function_tool()
async def approve_action(
    context: RunContext,
    action_id: str = "latest",
    scope: str = "once",
) -> str:
    """
    Approve and execute a pending NOVA action.

    Use scope='once' for one approval.
    Use scope='session' only when the action permits it.
    """

    return await permission_engine.approve(
        action_id=action_id,
        scope=scope,
    )


@function_tool()
async def deny_action(
    context: RunContext,
    action_id: str = "latest",
) -> str:
    """Deny and cancel a pending NOVA action."""

    return permission_engine.deny(
        action_id=action_id,
    )


@function_tool()
async def set_nova_safe_mode(
    context: RunContext,
    enabled: bool,
) -> str:
    """Enable or disable NOVA Safe Mode."""

    return permission_engine.set_safe_mode(
        enabled=enabled,
    )