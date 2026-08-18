"""LiveKit tools for NOVA's declarative Skills Engine."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool


def _agent_and_skills(context: RunContext):
    session = getattr(context, "session", None)
    if session is None:
        raise RuntimeError("NOVA skill tools could not access the active LiveKit session.")
    try:
        agent = session.current_agent
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeError("NOVA skill tools could not access the active agent.") from exc
    registry = getattr(agent, "skill_registry", None)
    if registry is None:
        raise RuntimeError("NOVA skill registry is not attached to the active agent.")
    return agent, registry


@function_tool()
async def list_skills(context: RunContext) -> str:
    """List reusable NOVA skills and whether each skill is enabled."""
    _agent, registry = _agent_and_skills(context)
    return registry.list_text()


@function_tool()
async def search_skills(context: RunContext, query: str) -> str:
    """Find a reusable NOVA skill for a task."""
    _agent, registry = _agent_and_skills(context)
    return registry.search_text(query)


@function_tool()
async def skill_info(context: RunContext, skill_id: str) -> str:
    """Describe one NOVA skill without executing it."""
    _agent, registry = _agent_and_skills(context)
    return registry.info_text(skill_id)


@function_tool()
async def use_skill(context: RunContext, skill_id: str, task: str = "") -> str:
    """Load a reusable NOVA skill playbook for the current task."""
    agent, registry = _agent_and_skills(context)
    spec = registry.get(skill_id)
    if spec is None:
        return f"Unknown skill '{skill_id}'. Use search_skills first."

    manager = getattr(agent, "capability_manager", None)
    if manager is not None:
        missing = [cap for cap in spec.required_capabilities if not manager.is_active(cap)]
        if missing:
            return (
                f"Skill '{spec.skill_id}' requires inactive capabilities: {', '.join(missing)}. "
                "Activate them with activate_capability, then call use_skill again."
            )
    return registry.playbook_text(skill_id, task)


@function_tool()
async def create_skill(
    context: RunContext,
    name: str,
    description: str,
    instructions: str,
    required_capabilities: str = "",
    tags: str = "",
) -> str:
    """Create a reusable declarative skill ONLY when the user explicitly asks NOVA to save/learn a workflow."""
    _agent, registry = _agent_and_skills(context)
    required = [part.strip() for part in required_capabilities.split(",") if part.strip()]
    parsed_tags = [part.strip() for part in tags.split(",") if part.strip()]
    try:
        spec = registry.create_user_skill(
            name=name,
            description=description,
            instructions=instructions,
            required_capabilities=required,
            tags=parsed_tags,
            risk="mixed",
        )
    except ValueError as exc:
        return f"I could not create that skill: {exc}"
    return f"Created NOVA skill '{spec.skill_id}' ({spec.name}) version {spec.version}."


@function_tool()
async def update_skill(
    context: RunContext,
    skill_id: str,
    instructions: str,
    description: str = "",
) -> str:
    """Update a user-created NOVA skill ONLY when the user explicitly asks to change that skill."""
    _agent, registry = _agent_and_skills(context)
    try:
        spec = registry.update_user_skill(
            skill_id,
            instructions=instructions,
            description=description or None,
        )
    except ValueError as exc:
        return f"I could not update that skill: {exc}"
    return f"Updated NOVA skill '{spec.skill_id}' to version {spec.version}. The previous version was preserved."


SKILL_CONTROL_TOOLS = (
    list_skills,
    search_skills,
    skill_info,
    use_skill,
    create_skill,
    update_skill,
)
