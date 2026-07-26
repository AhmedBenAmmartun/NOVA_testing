# NOVA desktop-shell vision (condensed)

Source: ChatGPT research pass, 2026-07-24/25, prompted by a Windows
customization video (1hr/10hr/24hr setups) plus the Seelen UI study. This is
the broader target shape for NOVA's Dashboard, refined and superseded in
detail by `seelen-ui-study.md` where the two disagree — this file covers
the pieces that study didn't (customization levels, dock/toolbar/command
center specifics, wallpaper, performance budgets, tool comparisons).

## Progressive customization levels

Users pick a level; NOVA doesn't reinstall anything to change it.

- **Simple**: orb, clock/date, weather, small dock, search, Spotify
  controls, basic glass theme.
- **Advanced** (current target): movable/resizable widgets, multiple
  dashboard pages, custom dock, top info bar, workspace profiles, animated
  backgrounds, app launcher, Obsidian/calendar/email widgets, system
  monitoring.
- **Ultimate** (long-term): automatic window organization, AI-generated
  layouts, context-aware widgets, voice-controlled desktop, live vision,
  dynamic themes, multi-monitor, phone/watch connection, face/voice
  recognition, proactive notifications, a security mode.

## Widget manifest shape

```json
{
  "id": "nova.system-monitor",
  "name": "System Monitor",
  "version": "1.0.0",
  "placement": ["desktop", "overlay"],
  "defaultSize": { "width": 360, "height": 220 },
  "permissions": ["system.cpu.read", "system.memory.read"],
  "refreshPolicy": { "activeMs": 1000, "idleMs": 5000, "hidden": "suspend" },
  "resizable": true,
  "movable": true,
  "multiInstance": false
}
```

`refreshPolicy.hidden: "suspend"` matters — hidden widgets should stop
updating entirely, not just render less often.

## Smart dock

Should track real state (installed / running / active / minimized /
launching / failed / has-notifications / has-multiple-windows), not just
static pinned icons:

| Interaction | Action |
|---|---|
| Left-click | Activate or launch |
| Second click on active | Minimize |
| Middle-click | Open a new window |
| Right-click | NOVA actions |
| Hover | Window preview |
| Drag | Reorder |
| Drop file | Open with app |

## Top toolbar

Configurable modules (NOVA state, workspace, weather, calendar, CPU/RAM,
media, mic/camera, notifications, battery, time). Context-sensitive: only
show what matters for the active workspace (e.g. coding → project + git
status + CPU/RAM; studying → course + assignment due + focus timer).

## Command center (Alt+Space)

Two routes: a deterministic command (open an app) executes immediately
without touching the AI; an ambiguous natural-language request goes to
NOVA's router. Opening VS Code should never cost a Gemini call.
Reference: Flow Launcher (fast app/file/web search, plugin system) and
PowerToys Command Palette — imitate the fast-path behavior, don't adopt the
tool itself as NOVA's permanent interface.

## Workspace profiles

```json
{
  "id": "coding",
  "name": "Coding Workspace",
  "applications": [
    { "id": "vscode", "project": "C:/Projects/AI Agent" },
    { "id": "terminal", "workingDirectory": "C:/Projects/AI Agent" },
    { "id": "claude" }
  ],
  "layout": {
    "type": "horizontal",
    "children": [
      { "type": "leaf", "application": "vscode", "growFactor": 2 },
      { "type": "vertical", "children": [
        { "type": "leaf", "application": "claude" },
        { "type": "leaf", "application": "terminal" }
      ]}
    ]
  }
}
```

"NOVA, start coding mode" → activate profile, launch/position apps, show
the relevant widgets, mute low-priority notifications, set wallpaper, pull
the current task from Obsidian. Build on PowerToys FancyZones/Workspaces
first rather than a custom window manager.

## Visual materials

- Main dashboard background → Mica-style (persistent-surface material).
- Widget panels → light translucent surface.
- Dock → stronger blur.
- Menus/popovers → Acrylic (Microsoft's own guidance: Acrylic is for
  transient surfaces, not persistent ones).
- Provide a reduced-effects mode for lower-RAM machines.

Use one design-token file (radius/spacing/blur/animation-duration scales)
consumed everywhere instead of per-widget hand-picked values.

## Wallpaper system (future)

Static / video / WebGL / audio-reactive / weather-reactive /
time-of-day / NOVA-status-reactive. Lively Wallpaper is a reasonable
existing engine to bridge to rather than building a renderer from scratch.

## Performance governor (do this alongside any visual work, not after)

```
if widget hidden:            suspend animation, stop refresh
if dashboard minimized:      reduce event frequency
if battery saver on:         disable heavy blur, reduce waveform FPS, pause camera
if fullscreen app/game:      pause wallpaper animation, hide widgets, keep only alerts
if display off:              pause rendering loops; resume safely on wake
if RAM over budget:          unload inactive dashboard pages/widgets
```

Target budgets (targets, not measured Seelen numbers): idle shell CPU <1%,
normal dashboard CPU <3%, shell+core-widgets RAM <300MB, system-monitor
refresh 1-2s, weather refresh 15-30min, calendar event-driven or every few
minutes, 60fps active / reduced when idle.

## Tools referenced (learn from, don't stack simultaneously)

| Tool | What to take |
|---|---|
| Rainmeter | Widget/skin architecture idea |
| PowerToys FancyZones/Workspaces | Initial window-layout backend |
| Flow Launcher | Search/command/plugin behavior reference |
| Lively Wallpaper | Animated-background engine to bridge to |
| Windhawk | Optional taskbar/Start-menu styling — keep optional, deeper Windows hooks |
| Seelen UI | Architecture reference — see seelen-ui-study.md; AGPL, don't copy code |

Don't run several of these (or several docks/launchers/wallpaper engines)
at once — duplicate startup hooks, overlapping shortcuts, wasted RAM.

## Build order (matches SKILL.md, more detail)

1. **Stabilize**: fix the desktop window edge/border, reliable widget
   move/resize/pin/lock/hide, saved layout positions, system tray, start
   with Windows, reliable app activate/minimize.
2. **Shell bridge**: dedicated shell service for windows/dock/tray/
   shortcuts/media-session/notifications; Python agent calls it over typed
   local IPC instead of doing OS work itself.
3. **Unified shell**: smart dock, top toolbar, theme engine, workspace
   switching, command center, smooth page transitions.
4. **Intelligence**: voice-controlled widgets, AI-generated layouts,
   context-aware widgets, proactive calendar/email alerts, resource-aware
   behavior.
5. **Ultimate** (optional, only after the above is proven stable): live
   vision window, face/voice recognition, cross-device sync, security
   monitoring, widget/plugin SDK, mobile companion.

## NOVA should eventually learn from video itself

Idea for a future tool: `learn_from_video(url)` — pull transcript/chapters,
extract design principles and concrete features, save a structured note to
`<vault>/NOVA/Learning/Videos/<title>.md` (source, chapters, timestamped
observations, tools mentioned, adopt/reject verdicts with reasoning, and
NOVA implementation tasks). Not built; this file itself is the manual
version of what that tool would have produced.
