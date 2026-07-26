"""Agent-side dispatcher for validated NOVA dashboard commands."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from nova_bridge import CommandStore, command_store
from nova_policy import PermissionEngine, permission_engine


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentStatusReporter:
    """In-memory phase tracker persisted by the bridge heartbeat loop."""

    session_id: str
    store: CommandStore = command_store
    route: str = "Gemini Flash"
    model: str = "gemini-2.5-flash-native-audio-preview-12-2025"
    phase: str = "starting"
    detail: str | None = None

    def set_phase(
        self,
        phase: str,
        *,
        route: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        if route:
            self.route = route
        self.detail = detail

    def snapshot(self) -> dict[str, str | None]:
        return {
            "phase": self.phase,
            "route": self.route,
            "model": self.model,
            "detail": self.detail,
        }

    async def publish_now(self) -> None:
        updater = getattr(self.store, "update_agent_status", None)
        if updater is None:
            await asyncio.to_thread(self.store.heartbeat, self.session_id)
            return
        await asyncio.to_thread(
            updater,
            self.session_id,
            self.phase,
            route=self.route,
            model=self.model,
            detail=self.detail,
        )


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
    status: AgentStatusReporter | None = None,
) -> None:
    """Publish status heartbeats and poll commands for one LiveKit session."""
    reporter = status or AgentStatusReporter(session_id=session_id, store=store, phase="idle")
    last_heartbeat = 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_heartbeat >= 1.0:
                snapshot = reporter.snapshot()
                if hasattr(store, "update_agent_status"):
                    await asyncio.to_thread(
                        store.heartbeat,
                        session_id,
                        phase=snapshot["phase"],
                        route=snapshot["route"],
                        model=snapshot["model"],
                        detail=snapshot["detail"],
                    )
                else:
                    await asyncio.to_thread(store.heartbeat, session_id)
                last_heartbeat = now
            if reporter.phase == "starting":
                await asyncio.sleep(0.25)
                continue
            claimed = await asyncio.to_thread(store.claim, session_id)
            for claimed_path, command in claimed:
                previous_phase = reporter.phase
                if command.get("kind") == "approval":
                    reporter.set_phase("tool_running", detail="Processing dashboard approval")
                    await reporter.publish_now()
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
                    if command.get("kind") == "approval":
                        reporter.set_phase(previous_phase if previous_phase != "tool_running" else "idle")
                        await reporter.publish_now()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    reporter.set_phase("error", detail=f"Dashboard command failed: {type(error).__name__}")
                    await reporter.publish_now()
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
