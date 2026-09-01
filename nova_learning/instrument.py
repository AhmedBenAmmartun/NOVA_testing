from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from time import perf_counter
from typing import Any, ParamSpec, TypeVar

from .context import get_current_experience
from .redaction import redact
from .schema import ToolCall


P = ParamSpec("P")
R = TypeVar("R")


def _ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1000))


def observed(tool_name: str) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Observe an async tool call without changing behavior when no turn is active.

    This fail-open behavior is deliberate: introducing learning instrumentation
    must not make a working NOVA capability fail merely because the recorder is
    unavailable or a call occurs outside a user turn.
    """
    normalized_name = tool_name.strip()
    if not normalized_name:
        raise ValueError("tool_name cannot be empty")

    def decorate(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(fn)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            started_at = perf_counter()
            try:
                result = await fn(*args, **kwargs)
            except Exception as error:
                current = get_current_experience()
                if current is not None:
                    current.tools.append(
                        ToolCall(
                            name=normalized_name,
                            args=redact(kwargs),
                            ok=False,
                            latency_ms=_ms(started_at),
                            error=type(error).__name__,
                        )
                    )
                raise

            current = get_current_experience()
            if current is not None:
                current.tools.append(
                    ToolCall(
                        name=normalized_name,
                        args=redact(kwargs),
                        ok=True,
                        latency_ms=_ms(started_at),
                    )
                )
            return result

        return wrapped

    return decorate
