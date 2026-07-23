"""NOVA dashboard server.

Serves the design shell in web/ and streams real data to it over one
WebSocket: psutil system stats, Spotify now-playing, wttr.in weather, the
Obsidian vault (notes, memories, tasks), the agent's nova_tools.log and
audit trail, conversation transcripts, cloud usage, and the real Windows
app catalog. Binds to 127.0.0.1 only.

Run with the project venv:
    venv\\Scripts\\python.exe Dashboard\\server.py
"""

from __future__ import annotations

import asyncio
import collections
import json
import sys
from pathlib import Path

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

DASHBOARD_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = DASHBOARD_DIR.parent
sys.path.insert(0, str(DASHBOARD_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

import actions  # noqa: E402
import feeds  # noqa: E402
import integration_feeds  # noqa: E402
from nova_bridge import CommandStore, command_store  # noqa: E402

WEB_DIR = DASHBOARD_DIR / "web"
DEFAULT_PORT = 8787
CONTRACT_VERSION = "1.1.0"
TAURI_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
}


class Hub:
    """Fan-out point: caches the latest message per type, broadcasts to all."""

    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()
        self.latest: dict[str, dict] = {}
        self.activity: collections.deque[dict] = collections.deque(maxlen=40)

    async def publish(self, message: dict | None) -> None:
        if not message:
            return
        if message["type"] == "activity":
            self.activity.append(
                {k: message[k] for k in ("time", "tag", "text", "status")}
            )
        elif message["type"] not in ("notify", "transcript"):
            self.latest[message["type"]] = message

        dead = []
        payload = json.dumps(message, ensure_ascii=False)
        for client in self.clients:
            try:
                await client.send_str(payload)
            except (ConnectionError, RuntimeError):
                dead.append(client)
        for client in dead:
            self.clients.discard(client)

    def snapshot(self) -> dict:
        parts = list(self.latest.values())
        if self.activity:
            parts.append({"type": "activity_seed", "items": list(self.activity)})
        return {
            "type": "snapshot",
            "contractVersion": CONTRACT_VERSION,
            "mode": "live",
            "parts": parts,
        }


def _origin_allowed(request: web.Request) -> bool:
    """Allow the bundled UI and this server's own page, not arbitrary sites."""
    origin = request.headers.get("Origin")
    if not origin:
        return True
    local_origins = {
        f"http://{request.host}",
        f"https://{request.host}",
    }
    return origin in local_origins or origin in TAURI_ORIGINS


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Origin is not allowed")
    hub: Hub = request.app["hub"]
    socket = web.WebSocketResponse(heartbeat=25)
    await socket.prepare(request)
    hub.clients.add(socket)
    try:
        await socket.send_str(json.dumps(hub.snapshot(), ensure_ascii=False))
        async for frame in socket:
            if frame.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                message = json.loads(frame.data)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            replies = await asyncio.to_thread(
                actions.handle,
                message,
                request.app["targets"],
                request.app["approvals"],
                request.app["bridge"],
            )
            for reply in replies:
                await hub.publish(reply)
    finally:
        hub.clients.discard(socket)
    return socket


async def index_handler(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html")


async def asset_handler(request: web.Request) -> web.FileResponse:
    path = (WEB_DIR / request.match_info["path"]).resolve()
    try:
        path.relative_to(WEB_DIR)
    except ValueError as error:
        raise web.HTTPNotFound() from error
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def health_handler(request: web.Request) -> web.Response:
    agent = await asyncio.to_thread(request.app["bridge"].active_session)
    integrations = await asyncio.to_thread(integration_feeds.status_message)
    return web.json_response(
        {
            "service": "nova-dashboard",
            "status": "ok",
            "mode": "live",
            "contractVersion": CONTRACT_VERSION,
            "agentBridge": "active" if agent["active"] else "waiting",
            "integrations": integrations.get("status", "unknown"),
            "integrationAccounts": len(integrations.get("accounts", [])),
        }
    )


# ---------------------------------------------------------
# Background collectors
# ---------------------------------------------------------

async def stats_loop(app: web.Application) -> None:
    while True:
        await app["hub"].publish(await asyncio.to_thread(feeds.stats_message))
        await asyncio.sleep(2)


async def spotify_loop(app: web.Application) -> None:
    while True:
        await app["hub"].publish(await asyncio.to_thread(feeds.spotify_message))
        await asyncio.sleep(4)


async def weather_loop(app: web.Application) -> None:
    async with aiohttp.ClientSession() as session:
        while True:
            message = await feeds.weather_message(session)
            if message:
                await app["hub"].publish(message)
                await asyncio.sleep(30 * 60)
            else:
                await asyncio.sleep(5 * 60)


async def obsidian_loop(app: web.Application) -> None:
    while True:
        await app["hub"].publish(await asyncio.to_thread(feeds.obsidian_message))
        await app["hub"].publish(await asyncio.to_thread(feeds.tasks_message))
        await asyncio.sleep(60)


async def usage_loop(app: web.Application) -> None:
    while True:
        await app["hub"].publish(await asyncio.to_thread(feeds.usage_message))
        await asyncio.sleep(30)


async def apps_loop(app: web.Application) -> None:
    while True:
        message, targets = await asyncio.to_thread(feeds.scan_apps)
        # Mutate in place: reassigning keys on a started aiohttp app is deprecated.
        for key, value in targets.items():
            app["targets"].setdefault(key, {}).clear()
            app["targets"][key].update(value)
        await app["hub"].publish(message)
        await asyncio.sleep(2 * 60)

async def apps_runtime_loop(app: web.Application) -> None:
    while True:
        registry = app["targets"].get("apps", {})
        if registry:
            message = await asyncio.to_thread(
                feeds.apps_runtime_message, registry
            )
            await app["hub"].publish(message)
        await asyncio.sleep(2)

async def tools_log_loop(app: web.Application) -> None:
    tail = feeds.FileTail(feeds.NOVA_TOOLS_LOG)
    while True:
        for line in await asyncio.to_thread(tail.read_new_lines):
            await app["hub"].publish(feeds.parse_log_line(line))
        await asyncio.sleep(1)


async def audit_loop(app: web.Application) -> None:
    tracker: feeds.ApprovalsTracker = app["approvals"]
    tail = feeds.FileTail(feeds.AUDIT_LOG, from_start=True)

    # Replay history silently so the pending queue starts accurate.
    for line in await asyncio.to_thread(tail.read_new_lines):
        tracker.feed(line)
    tracker.drop_stale()
    await app["hub"].publish(tracker.message())

    while True:
        changed = False
        for line in await asyncio.to_thread(tail.read_new_lines):
            for message in tracker.feed(line):
                await app["hub"].publish(message)
            changed = True
        if tracker.drop_stale() or changed:
            await app["hub"].publish(tracker.message())
        await asyncio.sleep(1)


async def conversation_loop(app: web.Application) -> None:
    watch = feeds.ConversationWatch()
    while True:
        for message in await asyncio.to_thread(watch.poll):
            await app["hub"].publish(message)
        await asyncio.sleep(2)


def _bridge_result_messages(result: dict) -> list[dict]:
    """Turn a consumed agent result into the existing dashboard contract."""
    kind = result.get("kind")
    status = result.get("status")
    message = str(result.get("message", ""))[:500]
    ok = status == "completed"
    label = "Delegation" if kind == "delegate" else "Approval"
    activity_status = "ok" if ok else "denied"
    return [
        {
            "type": "activity",
            "time": feeds.now_label(),
            "tag": "Task",
            "text": f"{label.lower()} {status}",
            "status": activity_status,
        },
        {
            "type": "notify",
            "icon": "◉",
            "title": label,
            "text": message or f"NOVA reported: {status}.",
        },
    ]


async def bridge_results_loop(app: web.Application) -> None:
    bridge: CommandStore = app["bridge"]
    while True:
        results = await asyncio.to_thread(bridge.read_results)
        for result in results:
            for message in _bridge_result_messages(result):
                await app["hub"].publish(message)
        await asyncio.sleep(0.5)


async def integrations_loop(app: web.Application) -> None:
    """Publish local read-only account, unread-mail, and calendar snapshots."""
    while True:
        messages = await asyncio.to_thread(integration_feeds.snapshot_messages)
        for message in messages:
            await app["hub"].publish(message)
        await asyncio.sleep(20)


async def integration_events_loop(app: web.Application) -> None:
    """Forward new safe integration events into NOVA's notification panel."""
    tail = integration_feeds.IntegrationEventTail()
    while True:
        events = await asyncio.to_thread(tail.read_new)
        for event in events:
            message = integration_feeds.event_to_dashboard(event)
            if message:
                await app["hub"].publish(message)
        await asyncio.sleep(1)


BACKGROUND_LOOPS = (
    stats_loop,
    spotify_loop,
    weather_loop,
    obsidian_loop,
    usage_loop,
    apps_loop,
    apps_runtime_loop,
    tools_log_loop,
    audit_loop,
    conversation_loop,
    bridge_results_loop,
    integrations_loop,
    integration_events_loop,
)


async def start_background(app: web.Application):
    app["loop_tasks"] = [asyncio.create_task(loop(app)) for loop in BACKGROUND_LOOPS]
    yield
    for task in app["loop_tasks"]:
        task.cancel()


def build_app() -> web.Application:
    app = web.Application()
    app["hub"] = Hub()
    app["targets"] = {"apps": {}, "folders": {}, "recent": {}}
    app["approvals"] = feeds.ApprovalsTracker()
    app["bridge"] = command_store
    app.router.add_get("/ws", websocket_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/", index_handler)
    app.router.add_get("/{path:.*}", asset_handler)
    app.cleanup_ctx.append(start_background)
    return app


if __name__ == "__main__":
    import os

    port = int(os.getenv("NOVA_DASHBOARD_PORT", str(DEFAULT_PORT)))
    web.run_app(build_app(), host="127.0.0.1", port=port)
