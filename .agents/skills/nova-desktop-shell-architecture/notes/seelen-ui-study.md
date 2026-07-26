# Seelen UI architecture study (condensed)

Source: ChatGPT research pass, 2026-07-25, studying Seelen UI 2.8 (a real
Rust/Tauri Windows desktop-shell replacement: dock, widgets, tiling window
manager, theming). Seelen's source is **AGPL-3.0-or-later** — study the
architecture, never copy its code into NOVA.

## Process separation

Seelen is three cooperating processes, not one window:

```
seelen-ui    main desktop app (Rust/Tauri core, state, widget/window manager)
slu-service  background Windows service: hotkeys, power events, window ops,
             taskbar recovery. Survives if seelen-ui crashes.
slu          CLI tool
```

Why it matters: if the visual shell crashes, the service can still restore
the taskbar, clean up global shortcuts, and recover the desktop. NOVA needs
the same boundary — a broken widget must never leave the taskbar hidden or
the desktop unusable.

## IPC

Main process ↔ service talk over Windows named pipes
(`\\.\pipe\seelen-ui-{session_id}`), scoped per Windows login session, with
a signature check before an action executes. Typed serialized commands, not
arbitrary strings. NOVA's current `127.0.0.1:8787` HTTP bridge is fine for
development; system-level commands should eventually move to an
authenticated named pipe / local socket.

## Shared state, not per-widget polling

One native module owns each state type (system, media, window, agent,
calendar...). Changes are computed once and emitted as typed events;
widgets subscribe only to what they need. NOVA should mirror this with one
provider per state type (`SystemStateProvider`, `MediaStateProvider`,
`WindowStateProvider`, `AgentStateProvider`...) instead of every widget
independently checking CPU/music/window/battery every second.

## Typed commands and events

```ts
await invoke(SeelenCommand.SwitchWorkspace, { workspaceId });
subscribe(SeelenEvent.VirtualDesktopsChanged, (event) => { ... });
```

Command names, argument shapes, and event payloads are generated from the
Rust definitions — a wrong argument is a compile error, not a mystery
runtime failure. NOVA should have one contract file (commands + events +
permissions) that generates matching TypeScript, so the dashboard frontend
and the Python/Rust backend can never send mismatched message shapes.

## Widgets

A widget is an isolated small web app (HTML/CSS/JS, Svelte/React/vanilla)
in its own WebView, described by a manifest (id, display name, icon, size,
resizable/movable, settings schema). Placement presets:

| Preset | Behavior | NOVA maps to |
|---|---|---|
| Desktop | behind ordinary windows, no title bar | clock, weather, system monitor |
| Overlay | above ordinary windows, no title bar | NOVA orb, live transcript, camera preview |
| Popup | temporary flyout | notification detail, right-click menu |
| None | widget controls its own window | — |

Lifecycle: WebView created → `widget.init()` → apply preset/position/theme
→ mount → `widget.ready()` → show. Prevents white flashes and half-rendered
widgets appearing at the wrong size.

## Permissions

Seelen prompts per third-party widget for protected commands (currently a
small enum: `Run`, `OpenFile`); bundled widgets are auto-trusted, decisions
persist. This is a good pattern but too coarse for NOVA, which handles far
more sensitive data (email, calendar, camera, files) — NOVA needs granular
capabilities (`apps.launch`, `email.send`, `screen.capture`,
`computer.lock`, ...) routed through the existing permission engine, with
Allow-once / Allow-while-open / Always / Deny per capability, and
third-party widgets getting nothing beyond their declared list.

## Window positioning

A dedicated Rust library (not scattered `SetWindowPos` calls) batches
target rectangles, detects no-op moves, supports easing/animation per
window independently, and handles DPI changes across monitors. NOVA should
have exactly one component allowed to move external application windows,
to avoid different dashboard features fighting over activate/resize.

## Tiling (later-stage feature, not needed yet)

Layouts are declarative trees interpreted by native code, not arbitrary
JS: `Leaf` (one window), `Stack` (tabbed), `Horizontal`/`Vertical` (splits),
with priorities and grow factors. NOVA's first step should be much
simpler — declarative **workspace profiles** (list of apps + a layout tree)
that launch and arrange windows for "start coding mode," not a full tiling
window manager. Use PowerToys FancyZones/Workspaces as the backend first.

## What NOT to copy yet

Taskbar replacement, Alt+Tab replacement, a custom virtual-desktop
implementation, a full tiling WM, third-party widget code with broad
command access, running the whole app as administrator. These are
late-stage shell features with real Windows-compatibility risk (fullscreen
apps, multi-monitor, DPI, UAC, sleep/wake) — build them only after the
foundation (shell bridge, typed IPC, widget runtime, workspaces) is solid
and proven.
