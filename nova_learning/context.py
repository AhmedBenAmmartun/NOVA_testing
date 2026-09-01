from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from time import perf_counter

from .schema import Experience


_current_experience: ContextVar[Experience | None] = ContextVar(
    "nova_current_experience",
    default=None,
)


@dataclass(slots=True)
class ExperienceScope:
    experience: Experience
    token: Token
    started_at: float


def begin_experience(experience: Experience | None = None) -> ExperienceScope:
    """Bind one Experience to the current async task/context."""
    current = experience or Experience()
    token = _current_experience.set(current)
    return ExperienceScope(current, token, perf_counter())


def get_current_experience(*, required: bool = False) -> Experience | None:
    current = _current_experience.get()
    if required and current is None:
        raise RuntimeError("No NOVA learning Experience is active in this context")
    return current


def end_experience(scope: ExperienceScope) -> Experience:
    """Finalize latency and restore the previous context binding."""
    scope.experience.latency_ms = max(
        scope.experience.latency_ms,
        int((perf_counter() - scope.started_at) * 1000),
    )
    _current_experience.reset(scope.token)
    return scope.experience
