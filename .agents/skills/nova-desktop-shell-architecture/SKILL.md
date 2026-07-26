---
name: nova-desktop-shell-architecture
description: Use when designing or building NOVA's Dashboard/desktop-shell — widgets, the dock, top toolbar, workspaces, window management, the Tauri app, or the Python-to-shell bridge — for architecture principles distilled from studying Seelen UI, and which patterns to adopt now vs. build later vs. never copy.
---

# NOVA Desktop Shell Architecture

## Overview

NOVA's Dashboard is evolving from a webpage-over-desktop into a real desktop
shell (widgets, dock, workspaces, window management). This captures the
architecture lessons from studying Seelen UI (a real Rust/Tauri desktop-shell
project) and a broader vision pass — what to adopt now, what to build later,
and what never to copy. Full research: `notes/seelen-ui-study.md` and
`notes/desktop-shell-vision.md`.

## Core principle: separate responsibilities into processes

- **Python agent** (`agent.py`) — AI decisions, tool routing, memory. Never
  touches windows directly.
- **Native shell** (Tauri/Rust, `Dashboard/nova-app`) — owns window
  discovery/activation/move/resize, tray, media sessions, notifications. The
  only thing allowed to call Windows APIs on external apps.
- **Small recovery service** (future) — survives shell crashes, restores
  taskbar/shortcuts. Not built yet.
- **WebView widgets** — visual only, talk to the shell through typed
  commands/events, never directly to the OS.

## Adopt now (cheap, high value)

- Typed commands/events instead of ad-hoc JSON strings (one contract file,
  generated TS bindings) — stops frontend/backend command-name mismatches.
- Event bus instead of per-widget polling: one collector per state type
  (system, media, window, agent, calendar...), widgets subscribe.
- Widget manifest (id, size, permissions, refresh policy) even before a full
  plugin system exists — makes future work additive, not a rewrite.
- Declarative workspace profiles (JSON: which apps, what layout) — use
  **PowerToys FancyZones/Workspaces** as the backend before building a
  custom tiling window manager.
- Granular permissions per widget/skill (`system.cpu.read`, `email.send`,
  `computer.lock`...) routed through NOVA's existing permission engine — a
  weather widget must never implicitly get `email.send`.
- Performance governor: pause animation/refresh when hidden, minimized, on
  battery saver, or a fullscreen app/game is active.
- Mica-style material for the main dashboard surface, Acrylic for
  menus/popups/flyouts — not one flat blur everywhere.

## Build later, in order — don't jump ahead

1. Stabilize current dashboard (reliable widget move/resize/pin, tray,
   minimize/activate).
2. Shell bridge: move window discovery/activation into the Tauri shell,
   typed IPC to Python.
3. Smart dock + top toolbar + workspace profiles + command center
   (Alt+Space).
4. Intelligence layer: voice-controlled widgets, context-aware surfaces,
   resource-aware behavior.
5. Optional, only after the above is solid: taskbar replacement, full
   tiling WM, third-party widget marketplace.

## Never copy without asking Ahmed first

- Don't hide/replace the Windows taskbar by default — breaks fullscreen
  apps, multi-monitor, DPI edge cases.
- Don't run NOVA as administrator by default — use a small elevated helper
  for the one operation that needs it, then exit.
- Don't let widget JavaScript call NOVA tools directly — everything
  dangerous routes through the permission engine.
- Don't stack multiple desktop-customization engines (Seelen + Rainmeter +
  another dock) — duplicate hooks, wasted RAM.
- **Seelen UI's source is AGPL-3.0** — study its architecture, never copy
  its code into NOVA (different license, would obligate the combined
  project).

## Quick reference: what maps to what

| NOVA idea | Reference pattern | Where |
|---|---|---|
| Widget window behavior | Presets: Desktop / Overlay / Popup / None | seelen-ui-study.md §Widgets |
| Workspace switching | Declarative layout tree (leaf/stack/horizontal/vertical) | seelen-ui-study.md §Tiling |
| System state → widgets | One provider per state type, event-driven | seelen-ui-study.md §Shared state |
| "Start coding mode" | Workspace profile (apps + layout + wallpaper + widgets) | desktop-shell-vision.md §Workspace profiles |
| Engineering budgets | Idle CPU <1%, shell+widgets RAM <300MB, refresh 1-2s | desktop-shell-vision.md §Performance |
