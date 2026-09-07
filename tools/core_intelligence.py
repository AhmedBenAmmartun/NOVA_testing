"""Intrinsic read-only Core Intelligence tool for the unified NOVA agent."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool


def _broker_from_context(context: RunContext):
    session = getattr(context, "session", None)
    if session is None:
        raise RuntimeError("NOVA Core Intelligence could not access the active session.")
    try:
        agent = session.current_agent
    except (AttributeError, RuntimeError) as exc:
        raise RuntimeError(
            "NOVA Core Intelligence could not access the active agent."
        ) from exc

    broker = getattr(agent, "core_intelligence", None)
    if broker is None:
        raise RuntimeError(
            "NOVA Core Intelligence is not attached to this agent session."
        )
    return broker


@function_tool()
async def get_nova_core_context(context: RunContext, task: str = "") -> str:
    """Read current NOVA project/Git awareness for a project-bearing task.

    This tool is read-only. It grants no permission. A1 project packets remain
    SHADOW_ONLY unless the shadow-evaluation graduation bar is met and trusted
    runtime configuration explicitly enables influence.
    """

    broker = _broker_from_context(context)
    return broker.render_for_model(task)


CORE_INTELLIGENCE_TOOLS = (get_nova_core_context,)
