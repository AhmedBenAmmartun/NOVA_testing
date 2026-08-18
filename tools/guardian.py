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


async def look_at_screen_locally(
    context: RunContext,
    question: str = "",
) -> str:
    """Compatibility-only stub for retired screenshot vision."""
    del context, question
    return (
        "Guardian screenshot vision is retired. Open NOVA Vision and "
        "explicitly enable a live visual source instead."
    )


async def start_guardian_vision(
    context: RunContext,
    minutes: float = 5.0,
) -> str:
    """Compatibility-only stub; it never starts pixel capture."""
    del context, minutes
    return (
        "Guardian screenshot vision is retired. Open NOVA Vision and "
        "choose the visual source yourself."
    )


async def stop_guardian_vision(
    context: RunContext,
) -> str:
    """Compatibility-only stop operation for the retired vision path."""
    del context
    runtime = get_guardian_runtime()
    await runtime.stop_vision()
    return "Guardian screenshot vision is inactive."


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