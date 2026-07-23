"""Agent-side dispatcher for validated NOVA dashboard commands."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from nova_bridge import CommandStore, command_store
from nova_policy import PermissionEngine, permission_engine


logger = logging.getLogger(__name__)


async def dispatch_dashboard_command(
    session: Any,
    command: dict,
    permissions: PermissionEngine = permission_engine,
) -> str:
    """Execute one validated local-dashboard command inside the agent process."""
    kind = command["kind"]
    payload = command["payload"]

    if kind == "delegate":
        text = str(payload["text"]).strip()
        speech = session.generate_reply(
            user_input=text,
            allow_interruptions=True,
        )
        completed = await speech
        handle = completed if completed is not None else speech
        if hasattr(handle, "exception") and handle.exception() is not None:
            raise RuntimeError("The delegated NOVA reply failed")
        return "The delegated prompt was delivered to the active NOVA session."

    action_id = str(payload["action_id"])
    if payload["decision"] == "approve":
        return await permissions.approve(
            action_id=action_id,
            scope=str(payload.get("scope", "once")),
        )
    return permissions.deny(action_id=action_id)


async def dashboard_bridge_loop(
    session: Any,
    session_id: str,
    store: CommandStore = command_store,
    permissions: PermissionEngine = permission_engine,
) -> None:
    """Poll the private inbox while one LiveKit session is active."""
    last_heartbeat = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_heartbeat >= 2.0:
                await asyncio.to_thread(store.heartbeat, session_id)
                last_heartbeat = now
            claimed = await asyncio.to_thread(store.claim, session_id)
            for claimed_path, command in claimed:
                try:
                    result = await dispatch_dashboard_command(
                        session,
                        command,
                        permissions,
                    )
                    await asyncio.to_thread(
                        store.complete,
                        claimed_path,
                        command,
                        "completed",
                        result,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "dashboard bridge command failed id=%s kind=%s error=%s",
                        command.get("id"),
                        command.get("kind"),
                        type(error).__name__,
                    )
                    await asyncio.to_thread(
                        store.complete,
                        claimed_path,
                        command,
                        "failed",
                        "NOVA could not run that dashboard command. Check nova_tools.log.",
                    )
            await asyncio.sleep(0.5)
    finally:
        await asyncio.to_thread(store.clear_heartbeat, session_id)


async def stop_dashboard_bridge(task: asyncio.Task) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
