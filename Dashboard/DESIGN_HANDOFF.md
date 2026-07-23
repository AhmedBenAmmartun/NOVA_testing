# Handoff: NOVA Desktop — AI Agent Control Center

## Overview
A full-screen desktop shell / control center for a personal voice AI agent ("NOVA"). Five horizontally-swipeable pages: widget dashboard, agent visualization ("Second Brain"), app & file launcher, calendar, and an agent activity/control page. Plus system chrome: top bar, dock, notifications/toasts, quick settings, Ctrl+K command palette, and a live speech-transcript pill.

## About the Design Files
`NOVA Desktop.dc.html` is a **design reference built in HTML** — a working prototype showing intended look and behavior, not production code to copy directly. The task is to **recreate this design in the real app environment** (e.g. an Electron/Tauri shell, or a React overlay on the existing NOVA Python/LiveKit agent). If no frontend exists yet, Electron + React or Tauri + React are good fits since the agent stack is local. All data in the prototype is simulated; this document marks every simulated source and what should replace it.

## Fidelity
**High-fidelity.** Colors, typography, spacing, radii, and interactions are final. Recreate pixel-perfectly.

## Design Tokens
- Background base: `#060a14`; wallpaper image behind everything with a dim overlay `rgba(3,6,14, dim)` — dim is user-adjustable 0–0.8, default 0.35
- Text: `#eaf0f6`; secondary `rgba(234,240,246,.62)`, tertiary `.5–.55`
- Accents: teal `#2ee6d6`, violet `#7c86f8` (highlight `#9aa2ff`), danger/pink `#e05f8a` (light `#f08cab`), warm `#f5a97b`, gold `#f5c97b`
- Glass cards: `rgba(10,14,24,.62)` + `backdrop-filter: blur(18px)` + border `1px solid rgba(255,255,255,.09)` + `box-shadow: inset 0 1px 0 rgba(255,255,255,.07), 0 10px 30px rgba(0,0,0,.28)`
- Radii: cards 18px (hero panels 22px), menus 12–16px, pills 999px
- Fonts: **Space Grotesk** (600/700) for display/headings/numerals; system `'Segoe UI', system-ui` for body; `Consolas, monospace` for tool-call/log text
- Type scale: labels 11px uppercase tracking .1em; body 12–13px; card titles 14–16px; clock 34px
- Motion: page slide `.5s cubic-bezier(.3,.8,.3,1)`; card hover lift `translateY(-3px)` .2s; popovers fadeUp .18s; everything honors a `reduceMotion` flag

## Screens / Views

### Chrome (all pages)
- **Top bar** (60px, transparent): orb logo (24px) + "NOVA" wordmark + clock/date; center "⌕ Ask NOVA · Ctrl K" pill button; right: notifications bell w/ unread badge + settings gear (32px circular glass buttons). CPU/RAM mini-pill appears in top bar only when the System widget is not on the dashboard.
- **Dock** (bottom center, glass pill): app tiles 44px, hover `translateY(-6px) scale(1.12)`, teal running dots, NOVA orb at the end (opens page 2). Auto-hide option slides it down 90px; 14px bottom hover strip peeks it.
- **Page dots** bottom center: active dot stretches to 16px with teal→violet gradient; page name flashes for 1.8s on change.
- **Navigation**: drag/swipe, horizontal wheel (300px accumulation threshold, 950ms lockout — important to prevent skipping), arrow keys, edge arrow buttons, page dots. Pages wrap around (5 pages).
- **Toasts** top-right: glass, icon + title + text, auto-dismiss 5.2s, click to dismiss.
- **Quick settings popover**: Lock canvas / Dock auto-hide / Demo privacy toggles (34×19px pill switches).

### 1 · Dashboard
6-column grid, 108px rows, 14px gap, `grid-auto-flow: dense`, scrolls vertically if needed. Widgets (all 2 cols wide): Clock (1 row), Weather (1), NOVA status w/ mini orb + current route (1), Tasks checklist (2), Now Playing w/ progress + controls (2), System w/ CPU/RAM ring gauges (1), Obsidian notes (2), Up next (1). Hover reveals a "⋯" menu: Pin/Unpin, Duplicate, Remove (disabled while pinned). "+" button (bottom-right of grid, 44px) opens the widget picker: 3 layout presets (Daily/Study/Minimal) + 8 add-able widgets. Empty state: "Your canvas is empty."
- **Real data**: clock/date (local), weather API, Spotify (playerctl/Web API), CPU/RAM (psutil or OS API), tasks & notes from the Obsidian vault.

### 2 · NOVA + Second Brain
Left: hero canvas — ~110-node orbiting particle graph (teal/violet nodes, faint violet edges, elliptical orbit, gentle wobble) with the large orb (74px) + phase label centered; "Second Brain · Obsidian vault" caption + linked-note count. Bottom strip: **Model routes** — chips per model (Gemini Flash, Groq Llama, Ollama, GPT-5.6, Obsidian Brain); the active route lights teal; each chip shows `12.8k · $0.09` usage; right end shows `Today · 77.2k tok · $1.43` total.
Right column: **Live conversation** (chat bubbles, user right/violet, NOVA left/teal, waveform bars animating while listening/speaking, dimmed while thinking) and **Execution timeline** (time + tag pill [Tool/Memory/Route/Vision] + monospace call).
- **Real data**: agent state machine (listening/thinking/speaking), router events, STT/TTS transcript, tool-call log, vault note count, token/cost metering from the router.

### 3 · Apps & Files
Left: app launcher — search field, Pinned grid, then A–Z groups (auto-fill 86px tiles; tiles are gradient placeholders with 2-letter glyphs — **replace with real app icons**). Right: Quick folders chips + Recent files list (extension badge, name, age).
- **Real data**: installed apps + icons, shell folders, recent files (OS MRU).

### 4 · Calendar
Left: July-style month grid (7 cols, equal rows), today ringed teal, event chips (deadline events pink, others violet). Right: "Coming up" agenda list with colored left bars.
- **Real data**: Google Calendar / ICS.

### 5 · Agent (control center)
Left: **Agent activity** feed — filter chips (All/Task/Tool/Memory/Route/Vision), rows = time + tag pill + monospace call + status (ok/running/approved/denied; running is gold, denied pink). Newest first, cap ~40.
Right: **Needs approval** queue (pink-tinted cards: action, monospace detail, Approve/Deny buttons — teal/pink) and **Memory browser** — search + vault memory cards (title, snippet, age, ✕ forget).
- **Real data**: the agent's event bus; approvals gate sensitive tools (screen capture, file writes); memory browser reads/deletes vault memory notes.

### Command palette (Ctrl+K or top-bar button)
Dimmed overlay + centered 560px glass panel: small orb + borderless input ("Tell NOVA what to do…") + "↵ delegate" hint + 4 suggestion rows. Enter delegates: closes, phase→thinking, activity entry `delegate("…")` status *running*, then Tool entry, then completion notification (prototype simulates with 2.2s/4.8s timers — replace with real agent task lifecycle).

### Live transcript pill
Above the dock: pulsing teal dot + text typing out as speech is recognized (prototype types 2 chars/50ms), ✕ dismiss, auto-fades 3.5s after completion. Wire to streaming STT partials.

## The Orb (shared component — build once, size prop)
Sphere, sizes 24/28/34/40/74px:
1. Base: `radial-gradient(circle at 33% 28%, #2c3468 0%, #171d44 52%, #070a1c 100%)`, round, outer glow `0 0 .5×size rgba(46,230,214,.35), 0 0 1.2×size rgba(124,134,248,.22)` pulsing 3.2s
2. Clipped inside: two counter-rotating blurred conic-gradient "plasma" layers (teal/violet streaks, blur ≈ 9–12% of size); spin speed maps to agent phase — 7s listening, 2.4s thinking, 3.6s speaking
3. Teal under-glow `radial-gradient(circle at 50% 72%, rgba(46,230,214,.45), transparent 55%)`
4. Specular highlight: blurred white ellipse at 16%/8%, 42%×30%
5. Inset rim: `inset 0 1px … rgba(255,255,255,.2), inset 0 -2px … rgba(46,230,214,.3)`

## State Management
Global: `page`, agent `phase` + `route`, `widgets[]` (id/type/pinned), `tasks[]`, `notifs[]`/`toasts[]`, `approvals[]`, `memories[]`, `activity[]` (time/tag/text/status), `usage{model→{tok,cost}}`, `transcript`, settings (`lock`, `dockAutoHide`, `privacy`, `wallpaperDim`, `reduceMotion`). Persist widgets + settings. In production these come from the agent's event stream (WebSocket/IPC from the LiveKit/Python side).

## Assets
- `wallpaper-clean.png` — user's wallpaper, taskbar cropped off
- App icons: NOT included — prototype uses gradient placeholder tiles; source real icons from the OS or the user
- Fonts: Space Grotesk via Google Fonts

## Additions since v1 (all present in the prototype)
- **Multi-window shell**: multiple app windows at once — z-order focus on click, cascade placement, drag by title bar, snap left/right (⇤ ⇥ buttons → half-screen), minimize (gold dot) / close (pink dot), Escape closes topmost. Desktop behind visible windows scales to .965 + dims (brightness .72). Dock icons toggle minimize for open apps; running dots reflect open windows.
- **Real app catalog**: launcher/dock/pinned lists mirror the user's actual Windows install (ChatGPT, development assistant, Copilot, Ollama, Obsidian, VS Code, Visual Studio 2022, Python, Node.js, Git, Ubuntu, Office, Samsung apps…). Icon tiles use per-brand gradient colors + short glyphs (see BRAND map in the logic class) — replace with real extracted app icons in production.
- **Daily briefing widget** (4-col): time-based greeting, overnight summary line, stat chips (weather / open tasks / next event / memories saved).
- **Focus modes** (settings): Study / Work / Off-hours — each applies a widget layout preset, switches the model route, and (Off-hours) mutes toasts. Active mode shows as a violet pill in the top bar. Clicking the active mode clears it.
- **Approval permissions**: "Auto-allow" toggle list (File writes / Screen capture / Shell commands / Web purchases) under the approval queue on the Agent page — in production this gates which agent actions enter the approval queue.
- **Widget drag-to-rearrange**: HTML5 drag on widget cards reorders the grid (disabled when canvas is locked).
- **Wallpaper switcher**: Photo / Aurora / Deep space swatches in settings; gradient layers cross-fade over the photo.
- **Lock screen**: settings button → full-screen blurred overlay with 96px orb, 64px clock, date, "still listening" pulse; click or any key unlocks.
- **Sound cues** (settings toggle, default off): WebAudio sine blips — task check 880Hz, approve 760Hz, deny 300Hz, notification 660Hz, ~180ms exponential decay.
- **Tasks widget**: checking strikes through for 900ms then moves the item to a "Completed" section (click to un-complete); circular progress ring shows done/total.
- **Quick folders**: user's real desktop folders (ML_project, AI Agent, Projects for nova, zonta, Obsidian Vault…).

## Files
- `NOVA Desktop.dc.html` — the full prototype (template + logic). Open in a browser to interact.
- `support.js` — prototype runtime (ignore for implementation; render logic is in the HTML file)
- `wallpaper-clean.png`
