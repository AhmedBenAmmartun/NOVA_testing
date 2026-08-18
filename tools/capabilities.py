"""Model-callable controls for NOVA OS capabilities."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool


def _manager_from_context(context: RunContext):
    session = getattr(context, "session", None)
    if session is None:
        raise RuntimeError("NOVA capability tools could not access the active LiveKit session.")

    try:
        agent = session.current_agent
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeError("NOVA capability tools could not access the active agent.") from exc

    manager = getattr(agent, "capability_manager", None)
    if manager is None:
        raise RuntimeError("NOVA capability manager is not attached to the active agent.")
    return agent, manager


@function_tool()
async def list_capabilities(context: RunContext) -> str:
    """List NOVA's available capability groups and whether each is active."""
    _agent, manager = _manager_from_context(context)
    return manager.list_text()


@function_tool()
async def search_capabilities(context: RunContext, query: str) -> str:
    """Find NOVA capabilities relevant to a requested task or tool."""
    _agent, manager = _manager_from_context(context)
    return manager.search_text(query)


@function_tool()
async def get_active_capabilities(context: RunContext) -> str:
    """List the capability groups currently loaded into NOVA's tool context."""
    _agent, manager = _manager_from_context(context)
    return manager.active_text()


@function_tool()
async def capability_info(context: RunContext, capability_id: str) -> str:
    """Describe one NOVA capability, including its tools and permission class."""
    _agent, manager = _manager_from_context(context)
    return manager.info_text(capability_id)


@function_tool()
async def activate_capability(context: RunContext, capability_id: str) -> str:
    """Activate a NOVA capability and make its tools available in this session."""
    agent, manager = _manager_from_context(context)
    result = manager.activate(capability_id)
    if result.startswith("Activated capability"):
        await agent.update_tools(manager.build_tool_context())
    return result


@function_tool()
async def deactivate_capability(context: RunContext, capability_id: str) -> str:
    """Deactivate an optional NOVA capability and remove its tools this session."""
    agent, manager = _manager_from_context(context)
    result = manager.deactivate(capability_id)
    if result.startswith("Deactivated capability"):
        await agent.update_tools(manager.build_tool_context())
    return result


CAPABILITY_CONTROL_TOOLS = (
    list_capabilities,
    search_capabilities,
    get_active_capabilities,
    capability_info,
    activate_capability,
    deactivate_capability,
)
