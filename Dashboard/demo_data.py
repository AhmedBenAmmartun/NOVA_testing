"""Curated sample data for NOVA_DASHBOARD_DEMO=1 standalone runs.

This module only exists so a from-scratch clone of the dashboard (no NOVA
agent, no Ahmed's Obsidian vault, no Spotify behind it) looks alive instead
of a wall of honest "offline"/"not connected" states. It is opt-in only
(set NOVA_DASHBOARD_DEMO=1) and never activates on its own — the real
feeds in feeds.py already report an accurate empty/offline state when
their data source is missing, and that must stay the default everywhere
demo mode isn't explicitly requested. The frontend labels every screen
that uses this data with a visible "DEMO DATA" badge (see Hub.snapshot's
"mode" field and index.html's isDemo prop) so it is never mistaken for a
real, live NOVA.
"""

from __future__ import annotations

import asyncio
import os
import time

DEMO_MODE = os.getenv("NOVA_DASHBOARD_DEMO", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_PHASE_CYCLE = ["idle", "listening", "thinking", "speaking"]
_PHASE_SECONDS = 6


async def agent_status_loop(app) -> None:
    index = 0
    while True:
        phase = _PHASE_CYCLE[index % len(_PHASE_CYCLE)]
        index += 1
        now = time.time()
        await app["hub"].publish(
            {
                "type": "agent_status",
                "online": True,
                "status": phase,
                "phase": phase,
                "route": "Gemini Flash",
                "model": "gemini-2.5-flash-native-audio-preview",
                "detail": None,
                "sessionId": "demo-session",
                "startedAt": now,
                "heartbeatAt": now,
                "heartbeatAge": 0,
            }
        )
        await asyncio.sleep(_PHASE_SECONDS)


async def spotify_loop(app) -> None:
    await app["hub"].publish(
        {
            "type": "spotify",
            "available": True,
            "configured": True,
            "open": True,
            "status": "playing",
            "title": "Deep Focus",
            "artist": "NOVA Radio",
            "album": "Ambient Mix",
            "artwork": None,
            "device": "This Computer",
            "playing": True,
            "progress": 41,
            "progressMs": 98_000,
            "durationMs": 240_000,
        }
    )
    while True:
        await asyncio.sleep(3600)


_DEMO_MEMORIES = [
    {
        "id": 1,
        "title": "Project decisions.md",
        "snippet": "Decided to use LiveKit + Gemini Realtime for the voice pipeline.",
        "when": "1d",
    },
    {
        "id": 2,
        "title": "Weak topics.md",
        "snippet": "Review polar coordinates before Tuesday's quiz.",
        "when": "2d",
    },
]

_DEMO_RECENT_NOTES = [
    {"title": "Build Week retro.md", "when": "2h"},
    {"title": "Study notes - Calc III.md", "when": "1d"},
    {"title": "Interview prep.md", "when": "3d"},
]

_DEMO_TASKS = [
    {"id": 1, "label": "Finish Dashboard demo mode", "done": False},
    {"id": 2, "label": "Record Build Week demo video", "done": True},
    {"id": 3, "label": "Review Obsidian memory notes", "done": True},
]


async def obsidian_loop(app) -> None:
    await app["hub"].publish(
        {
            "type": "obsidian",
            "available": True,
            "count": 128,
            "recent": _DEMO_RECENT_NOTES,
            "memories": _DEMO_MEMORIES,
        }
    )
    await app["hub"].publish({"type": "tasks", "available": True, "items": _DEMO_TASKS})
    while True:
        await asyncio.sleep(3600)


async def usage_loop(app) -> None:
    while True:
        await app["hub"].publish(
            {
                "type": "usage",
                "models": {
                    "Gemini Flash": "12 req",
                    "Groq Llama": "4 req",
                    "Ollama": "2 req",
                    "GPT-5.6": "1 req",
                    "Obsidian Brain": "6 req",
                },
                "total": "Today · 25 cloud requests",
            }
        )
        await asyncio.sleep(3600)


async def conversation_loop(app) -> None:
    await app["hub"].publish(
        {
            "type": "talk",
            "items": [
                {"who": "user", "text": "Nova, what's on my schedule today?"},
                {
                    "who": "nova",
                    "text": "This is demo data — nothing real is connected right now.",
                },
            ],
        }
    )
    while True:
        await asyncio.sleep(3600)


_DEMO_TIMELINE = [
    {"time": "9:41 AM", "tag": "Tool", "text": 'get_weather("local")', "status": "ok"},
    {"time": "9:42 AM", "tag": "Memory", "text": 'obsidian.search("build week")', "status": "ok"},
    {"time": "9:44 AM", "tag": "Route", "text": "router -> gemini/flash", "status": "ok"},
    {"time": "9:47 AM", "tag": "Tool", "text": 'spotify.play("Deep Focus")', "status": "ok"},
]


async def activity_loop(app) -> None:
    for item in _DEMO_TIMELINE:
        await app["hub"].publish({"type": "activity", **item})
        await asyncio.sleep(0.05)
    await app["hub"].publish({"type": "approvals", "items": []})
    while True:
        await asyncio.sleep(3600)
