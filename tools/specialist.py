"""Unified specialist-model tool for NOVA."""

from __future__ import annotations

from livekit.agents import RunContext, function_tool

from nova_core import (
    ModelRouter,
    NoProviderAvailableError,
    RouterError,
    create_model_router,
)

from .common import logger


_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """
    Create or return NOVA's shared specialist router.

    It is created lazily so environment variables are loaded first.
    """

    global _model_router

    if _model_router is None:
        _model_router = create_model_router()

    return _model_router


def _normalize_role(role: str) -> str:
    """Convert similar role names into supported router roles."""

    cleaned_role = (
        role
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "code": "coding",
        "programming": "coding",
        "debug": "coding",
        "debugging": "coding",
        "reason": "reasoning",
        "analysis": "reasoning",
        "planning": "reasoning",
        "research": "reasoning",
        "local": "private",
        "offline": "private",
        "privacy": "private",
    }

    normalized_role = aliases.get(
        cleaned_role,
        cleaned_role,
    )

    supported_roles = {
        "reasoning",
        "coding",
        "private",
    }

    if normalized_role not in supported_roles:
        return "reasoning"

    return normalized_role


async def route_specialist_request(
    task: str,
    *,
    role: str = "reasoning",
    private: bool = False,
) -> str:
    """
    Route a task through NOVA's model-provider system.

    This internal function can be tested without a LiveKit RunContext.
    """

    cleaned_task = task.strip()

    if not cleaned_task:
        return "The specialist request was empty."

    normalized_role = _normalize_role(role)

    try:
        router = get_model_router()

        if private or normalized_role == "private":
            result = await router.route_private(
                cleaned_task
            )

        else:
            result = await router.route(
                cleaned_task,
                role=normalized_role,
                allow_fallback=True,
            )

        logger.info(
            "Specialist request completed: "
            "provider=%s model=%s role=%s fallback=%s",
            result.provider,
            result.model,
            normalized_role,
            result.used_fallback,
        )

        return result.text

    except NoProviderAvailableError as error:
        logger.warning(
            "No specialist provider was available: %s",
            error,
        )

        return (
            "No specialist model is currently available. "
            "Check the cloud connection or start Ollama."
        )

    except RouterError as error:
        logger.warning(
            "Specialist routing failed: %s",
            error,
        )

        return (
            "NOVA could not route that specialist request."
        )

    except Exception:
        logger.exception(
            "Unexpected specialist routing failure"
        )

        return (
            "The specialist system encountered an unexpected error."
        )


@function_tool()
async def ask_specialist(
    context: RunContext,
    task: str,
    role: str = "reasoning",
    private: bool = False,
) -> str:
    """
    Ask NOVA's specialist-model router for help.

    Use role="coding" for programming, debugging, and architecture.
    Use role="reasoning" for planning, research, and deep analysis.
    Set private=true for private or offline tasks that must use the
    local Ollama provider. The router automatically falls back to
    Ollama when the selected cloud specialist is unavailable.
    """

    _ = context

    return await route_specialist_request(
        task,
        role=role,
        private=private,
    )