# NOVA Dashboard

The real NOVA desktop shell, implemented from `DESIGN_HANDOFF.md`
(design_handoff_nova_desktop). Five swipeable pages — widget dashboard,
NOVA + Second Brain, Apps & Files, Calendar, Agent control center — plus
top bar, dock, command palette (Ctrl+K), notifications, and lock screen.

NOVA ships as a **standalone Windows desktop app** (Tauri 2) — its own
`NOVA.exe`, icon, taskbar identity, and installer. No browser is involved: the
UI renders in a borderless native window via the system WebView2 runtime, and
the Python data server is started silently as a child process. See
`nova-app/README.md` for the app internals.

## Run it

```powershell
# The standalone app (recommended). Starts the data server itself, silently.
&"$env:LOCALAPPDATA\Programs\NOVA\NOVA.exe"

# Dev loop for the app (hot-reloads Rust + serves web/):
cd Dashboard\nova-app ; npx tauri dev

# Backend only, no UI (for debugging the feeds):
venv\Scripts\python.exe Dashboard\server.py   # binds 127.0.0.1:8787
```

The server binds to 127.0.0.1 only. The Python side adds no new dependencies —
it uses aiohttp/psutil/spotipy/python-dotenv already in the venv. The app shell
adds a Rust/Tauri build toolchain (already installed on this machine).

## Standalone use (no NOVA repo)

`server.py`/`feeds.py` auto-detect whether they're embedded in the NOVA repo
(an `agent.py` next door) or running on their own — if standalone, `Dashboard/`
is treated as the project root itself, and `Dashboard/nova_bridge.py` (a
vendored copy) is used so the module still imports with no live agent behind
it. Run it anywhere with just this folder's own `requirements.txt`:

```powershell
pip install -r requirements.txt
python server.py            # real mode: honest offline/empty states
$env:NOVA_DASHBOARD_DEMO=1; python server.py   # demo mode: sample data, labeled
```

Demo mode (`NOVA_DASHBOARD_DEMO=1`) only fakes the pieces nobody else's machine
has real data for — agent status, Obsidian notes/tasks, Spotify now-playing,
model usage, and the conversation/activity feeds. System stats, weather, and
the installed-app catalog stay real either way. See `demo_data.py`.

## The app: window modes, tray, autostart

- **Dashboard mode** — a normal movable/resizable window with a custom NOVA
  title bar (minimize / maximize / hide / close). Closing hides to the tray;
  NOVA keeps running.
- **Desktop mode** — borderless, pinned to the bottom of the z-order, no
  taskbar button, sized to the work area (never covers the taskbar). A small
  toolbar offers *Dashboard* (return) and *Click-through* (let clicks fall to
  the desktop; use the tray to come back). Rainmeter-like.
- **System tray menu** — Open / Hide / Toggle Desktop Widgets / Toggle Edit Mode / Toggle Click-through / Always on Top / Start
  with Windows / Restart NOVA / Quit NOVA. Left-click the tray icon to show.
- **Start with Windows** — toggled from the tray; uses the OS autostart
  mechanism (registry Run key), no PowerShell/terminal/Edge window at login.
- **Single instance** — launching NOVA again focuses the running window.
- Window size/position persist (window-state plugin); selected page, widget
  layout, and last mode persist in the WebView2 localStorage.

## Architecture

```
web/index.html    the design shell (template + logic; pixel-per the handoff)
web/support.js    prototype runtime that renders the template
web/tauri-shell.js  title bar + tray/mode wiring; INERT in a plain browser
server.py         aiohttp: static files + one WebSocket (/ws) + collectors
feeds.py          real-data collectors (see table below)
actions.py        handlers for clicks the shell sends back over the socket
runtime/          gitignored private command envelopes and transient state
nova-app/         the Tauri 2 desktop wrapper (Rust + tauri.conf.json)
```

The shell connects to `ws://127.0.0.1:8787/ws` (the app sets `window.NOVA_BACKEND`;
a plain browser derives it from the URL). A teal **DASHBOARD** pill shows once
connected; before that, or while the agent isn't running, cards show an honest
"offline"/"not connected" state rather than inventing data. Set
`NOVA_DASHBOARD_DEMO=1` when starting `server.py` to opt into a clearly-labeled
**DEMO DATA** pill and curated sample data instead (see "Standalone use" below)
— useful for showing the dashboard off with nothing real behind it.

The browser/backend boundary is versioned as contract `1.1.0`. The frontend
exposes `window.NOVAIntegration` for future NOVA adapters, and the server exposes
`GET /health` plus the WebSocket snapshot contract. WebSocket actions accept
only the bundled local page and Tauri origins; arbitrary websites are rejected.

React 18.3.1, ReactDOM 18.3.1, Babel Standalone 7.29.0, Space Grotesk, and their
licenses are bundled under `web/vendor/` and `web/fonts/`. The dashboard does
not depend on a CDN to start.

## Edit layout

Select **Edit layout** near the upper-right corner. Every main card on all five
pages can be moved and resized. Layouts save independently per page in local
storage and scale between supported display sizes. Edit Mode also provides:

- pin and hide/restore;
- undo and `Ctrl+Z`;
- Reset Current Page and Reset All Pages;
- eight-direction resizing;
- card-local scrolling for overflowing content.

Outside Edit Mode the cards are locked and edit controls are hidden. Each page
has an isolated clipped canvas, preventing adjacent pages from painting into the
current page.

## What is real

| Surface | Source |
| --- | --- |
| CPU / RAM rings + top-bar pill | psutil, every 2s |
| Now playing + play/pause/next/prev | Spotify Web API (cached OAuth) with window-title fallback; controls send real media keys |
| Weather widget + briefing chip | wttr.in (no key; `NOVA_CITY` env optional) |
| Clock, greeting | local time |
| Obsidian notes widget, Second Brain note count, memory browser | `OBSIDIAN_VAULT_PATH` scan; memories = `NOVA/*.md` |
| Tasks widget | checkboxes in `<vault>/NOVA/Tasks.md` (toggles write back) |
| Memory "forget" (✕) | moves the note to `<vault>/NOVA/.trash/` — never deletes |
| Agent phase (orb speed, status widget) | `conversation agent_state` lines in nova_tools.log |
| Activity feed + execution timeline | nova_tools.log tool calls, tagged Tool/Memory/Route/Vision |
| Needs-approval queue | reconstructed from `audit_logs/nova_actions.jsonl` |
| Approve/Deny buttons | private atomic command bridge into the active agent process and its in-memory permission engine |
| Ctrl+K delegation | inserted as a real user text turn in the active LiveKit `AgentSession` |
| Live conversation bubbles + transcript pill | newest file in `conversation_logs/` |
| Model route chips usage | `cloud_usage.json` written by nova_core (request counts) |
| App launcher, dock, quick folders, recent files | Trusted normalized Win32/shortcut/UWP registry, opaque application IDs, real Desktop folders, security-filtered Windows Recent items |


## Desktop widgets and security

Desktop Mode is a transparent, bottom-of-z-order widget layer over the real
Windows wallpaper. It hides the dashboard wallpaper, outer frame, top bar,
page arrows/dots, large dock, application windows, and other full-dashboard
chrome. Locked Desktop Mode is click-through; Edit Mode temporarily restores
mouse input so cards can be moved, resized, pinned, or hidden. Desktop widget
positions are saved separately from the five Dashboard page layouts.

Tray actions and keyboard shortcuts:

- **Ctrl+Shift+D** — toggle Dashboard/Desktop Mode.
- **Ctrl+Shift+E** — toggle Desktop Edit Mode.
- **Ctrl+Shift+T** — toggle click-through while Desktop Mode is locked.

The Apps & Files backend never accepts executable paths, PowerShell, command
lines, or shell instructions from the web UI. The UI sends only an opaque
registered application ID; Python resolves the trusted Win32 shortcut, UWP
AUMID, or executable internally. Recent-file shortcuts are resolved before
being shown, and both the scanner and final open action block `.env`,
credential/secret/token/password files, SSH/GPG/cloud credential directories,
private keys, certificates, and password databases. Sensitive paths and values
are never sent to the browser or written to activity logs.

## Local agent bridge

The dashboard server and LiveKit agent remain separate processes. Small,
validated commands cross `Dashboard/runtime/bridge/` as private atomic JSON
envelopes. The active agent claims each command once, executes approvals in the
same process that owns the pending executor, and returns a bounded result to the
dashboard. Commands expire after two minutes. The bridge transports no API
keys, environment values, arbitrary code, or private file contents.

`GET /health` reports `agentBridge: active` when a LiveKit console/dev session
is connected and `agentBridge: waiting` otherwise. Start the agent and
dashboard together to use Approve/Deny and Ctrl+K delegation.

## Known limitation

- **Calendar page** is still design demo data (no Google Calendar/ICS wired).
- Widget layout and settings persist in the WebView2 localStorage.
- The installed app finds the Python backend via `NOVA_PROJECT_ROOT` (env),
  then the exe's parent chain, then the project's known path. The backend is
  launched from the venv (not embedded), so it expects this project present.

## Verification

From the project root:

```powershell
npm --prefix Dashboard run lint
npm --prefix Dashboard run build
npm --prefix Dashboard test
& ".\venv\Scripts\python.exe" -m py_compile agent.py nova_bridge.py nova_agent_bridge.py Dashboard\server.py Dashboard\feeds.py Dashboard\actions.py
& ".\venv\Scripts\python.exe" -m unittest discover -s Dashboard\tests -p "test_*.py" -v
```

The browser matrix is checked at 1920×1080, 1600×900, 1366×768, and
1280×720. Build the native Windows installer from `Dashboard/nova-app` with
`npm install` followed by `npm run build`.
