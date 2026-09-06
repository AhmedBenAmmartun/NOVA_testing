"""Model-callable controls for NOVA OS capabilities."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool

from nova_verification import verify_fields


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


def _verify_capability_state(manager, capability_id: str, *, expected_active: bool):
    spec = manager.registry.get(capability_id)
    if spec is None:
        return verify_fields(
            "capability_activation",
            expected={"known_capability": True},
            observed={"known_capability": False},
        )

    toolset_id = f"nova_{spec.capability_id}"
    tool_context = manager.build_tool_context()
    exposed = any(getattr(item, "id", None) == toolset_id for item in tool_context)
    expected_exposed = bool(spec.tools) and bool(expected_active)

    return verify_fields(
        "capability_activation",
        expected={
            "active": bool(expected_active),
            "toolset_exposed": expected_exposed,
        },
        observed={
            "active": manager.is_active(spec.capability_id),
            "toolset_exposed": exposed,
        },
    )


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
        verification = _verify_capability_state(
            manager,
            capability_id,
            expected_active=True,
        )
        if not verification.ok:
            return (
                result
                + " "
                + verification.render()
                + " I am not claiming the runtime tool exposure succeeded."
            )
        return (
            result
            + " "
            + verification.render()
            + " The updated runtime tool context is observed; same-turn model "
              "re-planning is not claimed by this contract."
        )
    return result


@function_tool()
async def deactivate_capability(context: RunContext, capability_id: str) -> str:
    """Deactivate an optional NOVA capability and remove its tools this session."""
    agent, manager = _manager_from_context(context)
    result = manager.deactivate(capability_id)
    if result.startswith("Deactivated capability"):
        await agent.update_tools(manager.build_tool_context())
        verification = _verify_capability_state(
            manager,
            capability_id,
            expected_active=False,
        )
        if not verification.ok:
            return (
                result
                + " "
                + verification.render()
                + " I am not claiming the runtime tool removal succeeded."
            )
        return result + " " + verification.render()
    return result


CAPABILITY_CONTROL_TOOLS = (
    list_capabilities,
    search_capabilities,
    get_active_capabilities,
    capability_info,
    activate_capability,
    deactivate_capability,
)
