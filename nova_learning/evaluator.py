from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Evaluation:
    outcome: str
    source: str
    score: float


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split()).strip()
    return ""


def evaluate_tool_result(
    *,
    tool_name: str,
    output: object | None,
    is_error: bool,
) -> Evaluation | None:
    """Conservatively evaluate verified tool results in memory.

    Tool output is inspected only to derive a categorical outcome. The raw output
    is never returned from this function and must never be persisted by callers.
    Unknown tools intentionally return None rather than guessing success.
    """
    name = str(tool_name or "").strip()
    if is_error:
        return Evaluation("failure", "verified_tool_error", 1.0)

    text = _text(output)
    lower = text.lower()

    if name == "get_time":
        if text:
            return Evaluation("success", "verified_tool_result:get_time", 0.98)
        return None

    if name == "get_class_capture_status":
        if (
            "class recording is active for" in lower
            or "no class recording is active" in lower
        ):
            return Evaluation("success", "verified_tool_result:class_status", 0.98)
        return None

    if name == "start_class_capture":
        if "class recording is active for" in lower or "class recording is already active for" in lower:
            return Evaluation("success", "verified_tool_result:class_active", 1.0)
        if (
            "tell me which class" in lower
            or "ask the user which one" in lower
            or "which one is it" in lower
            or "course required" in lower
        ):
            return Evaluation("partial", "verified_tool_result:needs_user_input", 0.95)
        if (
            "couldn't start class recording" in lower
            or "did not become healthy" in lower
            or "not claiming recording succeeded" in lower
        ):
            return Evaluation("failure", "verified_tool_result:class_start_failed", 1.0)
        return None

    if name == "get_recent_class_context":
        if "recent finalized transcript for" in lower:
            return Evaluation("success", "verified_tool_result:class_context", 0.98)
        if "no finalized transcript lines are available yet" in lower:
            return Evaluation("partial", "verified_tool_result:class_context_pending", 0.9)
        if "no active class recording exists" in lower:
            return Evaluation("failure", "verified_tool_result:no_active_class", 0.98)
        return None

    if name == "mark_class_moment":
        if lower.startswith("marked "):
            return Evaluation("success", "verified_tool_result:class_marked", 1.0)
        if "no class recording is active" in lower or "couldn't mark the class moment" in lower:
            return Evaluation("failure", "verified_tool_result:class_mark_failed", 1.0)
        return None

    if name == "end_class_capture":
        if "class recording finalized with status" in lower:
            return Evaluation("success", "verified_tool_result:class_finalized", 1.0)
        if "no class recording is active" in lower:
            return Evaluation("success", "verified_tool_result:already_inactive", 0.95)
        if "finalization has not completed yet" in lower:
            return Evaluation("partial", "verified_tool_result:class_finalization_pending", 0.95)
        return None

    return None


def correction_signal(text: str) -> str | None:
    """Detect only strong correction language; never return raw user text."""
    normalized = " ".join(str(text or "").lower().split()).strip()
    if not normalized:
        return None

    strong = (
        "that's wrong",
        "that is wrong",
        "you're wrong",
        "you are wrong",
        "not what i said",
        "not what i meant",
        "that's not what i said",
        "that's not what i meant",
        "you misunderstood",
        "you misheard me",
        "i said ",
        "no, i said",
        "no i said",
    )
    if any(token in normalized for token in strong):
        return "explicit_user_correction"
    return None
