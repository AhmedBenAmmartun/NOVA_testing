"""LiveKit tools for NOVA Guardian."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from typing import Any, cast

from livekit.agents import RunContext, function_tool

from nova_guardian import get_guardian_runtime


def _safe_value(value: Any) -> Any:
    """
    Convert Guardian objects into safe JSON-compatible values.

    Screenshot bytes, image data, and private process command lines
    are never returned by these tools.
    """

    safe_summary_method = getattr(
        value,
        "safe_summary",
        None,
    )

    if callable(safe_summary_method):
        try:
            summary = safe_summary_method()
            return _safe_value(summary)

        except TypeError:
            # Some safe_summary methods may require arguments.
            # Continue to the other conversion methods.
            pass

        except Exception:
            # A failed summary method should not crash the tool.
            pass

    if (
        is_dataclass(value)
        and not isinstance(value, type)
    ):
        dataclass_value = asdict(
            cast(Any, value)
        )

        return _safe_value(
            dataclass_value
        )

    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (list, tuple, set),
    ):
        return [
            _safe_value(item)
            for item in value
        ]

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
            type(None),
        ),
    ):
        return value

    return str(value)


def _json_response(value: Any) -> str:
    """Return a readable JSON tool response."""

    return json.dumps(
        _safe_value(value),
        indent=2,
        ensure_ascii=False,
        default=str,
    )


@function_tool()
async def get_guardian_status(
    context: RunContext,
) -> str:
    """
    Check whether NOVA Guardian and its monitors are active.

    Use this when the user asks whether Guardian is running,
    whether local vision is active, or whether monitoring is paused.
    """

    _ = context

    runtime = get_guardian_runtime()

    return _json_response(
        runtime.safe_summary()
    )


@function_tool()
async def look_at_screen_locally(
    context: RunContext,
    question: str = (
        "Briefly describe the visible application and anything "
        "that appears to require the user's attention."
    ),
) -> str:
    """
    Analyze the foreground window with local Ollama vision.

    The screenshot remains in memory, is not saved to disk, and is
    not uploaded to a cloud provider. Sensitive windows are blocked.
    """

    _ = context

    cleaned_question = question.strip()

    if not cleaned_question:
        cleaned_question = (
            "Briefly describe what is visible "
            "in the active application."
        )

    runtime = get_guardian_runtime()

    try:
        result = await runtime.look_once(
            cleaned_question
        )

    except Exception as error:
        return (
            "NOVA could not complete the local screen analysis. "
            f"Error type: {type(error).__name__}."
        )

    if result.analyzed:
        return (
            "Local screen analysis completed.\n\n"
            f"{result.text}\n\n"
            f"Local model: {result.model}"
        )

    reason = (
        result.reason
        or "analysis_not_completed"
    )

    return (
        "Local screen analysis was not completed.\n\n"
        f"Reason: {reason}\n"
        f"Details: {result.text}"
    )


@function_tool()
async def start_guardian_vision(
    context: RunContext,
    minutes: float = 5.0,
) -> str:
    """
    Start a temporary local-only ambient-vision session.

    Use only after the user explicitly asks NOVA to start watching
    or monitoring their screen. The session automatically expires.
    """

    _ = context

    try:
        requested_minutes = float(
            minutes
        )

    except (
        TypeError,
        ValueError,
    ):
        requested_minutes = 5.0

    safe_minutes = max(
        0.25,
        min(requested_minutes, 30.0),
    )

    runtime = get_guardian_runtime()

    try:
        started = await runtime.start_vision(
            minutes=safe_minutes
        )

    except Exception as error:
        return (
            "Guardian vision could not be started. "
            f"Error type: {type(error).__name__}."
        )

    if not started:
        status = runtime.safe_summary()

        if status.get("vision_active"):
            return (
                "Local Guardian vision is already active. "
                "No additional session was started."
            )

        return (
            "Guardian vision could not be started. "
            "Check the Guardian configuration and "
            "the local Ollama vision model."
        )

    return (
        "Local Guardian vision started for approximately "
        f"{safe_minutes:g} minute(s). "
        "Screenshots remain local and are not stored."
    )


@function_tool()
async def stop_guardian_vision(
    context: RunContext,
) -> str:
    """
    Stop NOVA Guardian's current local-vision session.

    Window monitoring and defensive security monitoring remain
    available after local vision is stopped.
    """

    _ = context

    runtime = get_guardian_runtime()

    try:
        stopped = await runtime.stop_vision()

    except Exception as error:
        return (
            "Guardian vision could not be stopped normally. "
            f"Error type: {type(error).__name__}."
        )

    if stopped:
        return (
            "Local Guardian vision has been stopped. "
            "No further screenshots will be analyzed."
        )

    return (
        "Local Guardian vision was not active."
    )


@function_tool()
async def check_guardian_security(
    context: RunContext,
) -> str:
    """
    Run one defensive local security scan.

    The scan checks local process activity, network listeners,
    Microsoft Defender status, and Windows Firewall status.
    It does not terminate processes or change system settings.
    """

    _ = context

    runtime = get_guardian_runtime()

    try:
        result = await asyncio.to_thread(
            runtime.scan_security_once
        )

    except Exception as error:
        return (
            "Guardian could not complete the local "
            "security scan. "
            f"Error type: {type(error).__name__}."
        )

    return (
        "Guardian defensive security scan completed.\n\n"
        f"{_json_response(result)}"
    )


@function_tool()
async def get_guardian_alerts(
    context: RunContext,
    limit: int = 10,
) -> str:
    """
    Return recent unacknowledged Guardian alerts.

    Use this when the user asks about suspicious activity,
    warnings, security events, or Guardian notifications.
    """

    _ = context

    try:
        requested_limit = int(
            limit
        )

    except (
        TypeError,
        ValueError,
    ):
        requested_limit = 10

    safe_limit = max(
        1,
        min(requested_limit, 25),
    )

    runtime = get_guardian_runtime()

    try:
        alerts = runtime.recent_alerts(
            limit=safe_limit
        )

    except Exception as error:
        return (
            "Guardian could not retrieve recent alerts. "
            f"Error type: {type(error).__name__}."
        )

    if not alerts:
        return (
            "Guardian has no current "
            "unacknowledged alerts."
        )

    safe_alerts = [
        _safe_value(alert)
        for alert in alerts
    ]

    return (
        f"Guardian found {len(safe_alerts)} "
        "unacknowledged alert(s).\n\n"
        f"{_json_response(safe_alerts)}"
    )