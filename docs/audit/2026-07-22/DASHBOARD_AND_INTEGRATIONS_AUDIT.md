# NOVA Dashboard and Integrations Audit — 2026-07-22

Scope: read-only code trace of `Dashboard/` (desktop shell) and the
Gmail/Outlook integration stack (`nova_integrations/`, `tools/email_calendar.py`,
`tools/media.py`, `tools/obsidian.py`). No `.env`, cached OAuth tokens, or
secret files were opened — only existence/size/mtime checks were performed
where noted. All claims below cite `file:line`.

Status categories used: **Working** / **Partially working** / **Present but
not wired** / **Mocked or simulated** / **Broken** / **Missing** / **Dead or
unused** / **Security risk** / **Needs manual verification**.

---

## Part 1 — Dashboard as a real desktop component

### 1.1 Process model

Two independent processes, connected only over a local WebSocket:

- `Dashboard/server.py` — aiohttp app, binds `127.0.0.1` only (`Dashboard/server.py:348`),
  serves `Dashboard/web/` as static files (`Dashboard/server.py:132-144`) and
  one `/ws` endpoint (`Dashboard/server.py:100-129`).
- `Dashboard/nova-app/src-tauri` — a Tauri 2 Rust shell (`nova_desktop_lib`)
  that spawns `pythonw.exe Dashboard/server.py` as a child process
  (`Dashboard/nova-app/src-tauri/src/lib.rs:76-104`) and renders
  `Dashboard/web/index.html` in a native WebView2 window. A release build
  exists on disk (`Dashboard/nova-app/src-tauri/target/release/NOVA.exe`,
  `.../target/release/nsis/` installer present) — **Working**, not just
  scaffolding.

`Start-NOVA.ps1:42-59` and `Dashboard/start_dashboard.ps1:9-28` both look for
the built `NOVA.exe` first (installed copy in `%LOCALAPPDATA%\Programs\NOVA\`
or the release build under `nova-app\src-tauri\target\release\`) and fall
back to running `server.py` directly with `pythonw.exe` if no exe is built —
**Working** dual-path launcher, verified present: `%LOCALAPPDATA%\NOVA\NOVA.exe`
exists (5.6 MB) alongside an `uninstall.exe`, confirming an NSIS install
actually happened on this machine.

### 1.2 Window transparency / frameless / acrylic / always-on-top

`Dashboard/nova-app/src-tauri/tauri.conf.json:12-27`: the main window is
declared `"decorations": false, "transparent": true, "shadow": true,
"resizable": true, "dragDropEnabled": false`. This is real Tauri config, not
a doc claim — **Working** (frameless + OS-compositor transparency).

**Finding — acrylic/blur is claimed by the dependency graph but never
applied.** `Cargo.toml:18` pulls in `window-vibrancy = "0.6"`, but
`src-tauri/src/lib.rs` never calls `apply_blur`/`apply_acrylic`/`apply_mica`
(confirmed by grep — zero matches for `vibrancy|apply_blur|apply_acrylic|apply_mica`
anywhere under `Dashboard/nova-app`). The only "blur" in the product is a CSS
`backdrop-filter: blur(...)` applied to individual cards in
`Dashboard/web/index.html` (e.g. `web/index.html:382`) and
`Dashboard/web/tauri-shell.js:29` — a per-element CSS effect, not a
window-level OS acrylic/Mica surface. **Status: Dead or unused dependency** —
`window-vibrancy` is declared and compiled but has no effect. Not a
correctness bug (CSS blur reads similarly to the eye) but the crate is dead
weight and a misleading signal about how the effect is achieved.

Always-on-top: implemented as a real Tauri command,
`set_always_on_top` (`lib.rs:187-191`) calling `win.set_always_on_top(on)`,
wired to a checkable tray menu item (`lib.rs:242-244, 297-308`) — **Working**.
No UI control for it inside the web page itself was found (only the tray
menu toggles it).

Click-through: `set_click_through` (`lib.rs:193-196`) calls
`win.set_ignore_cursor_events(on)`, invoked from `tauri-shell.js:72` whenever
desktop-mode state changes, and toggled via `Ctrl+Shift+T`
(`tauri-shell.js:105-115`) or the tray "Toggle Click-through" item
(`lib.rs:241, 291-296`) — **Working**.

### 1.3 System tray

`build_tray()` (`lib.rs:236-349`) builds a real `TrayIconBuilder` with a menu
(Show/Hide/Return to Desktop/Toggle Edit/Toggle Click-through/Always on
Top/Start with Windows/Restart NOVA/Quit NOVA), wired to `on_menu_event` and
`on_tray_icon_event` handlers that call the same window commands described
above, plus `restart_backend()` (kills and respawns the Python child,
`lib.rs:216-223`) and `quit_app()` (kills the Python child, then
`app.exit(0)`, `lib.rs:225-230`). `tauri.conf.json` has no static `trayIcon`
config block, but Tauri 2 does not require one when the tray is built
programmatically with `.default_window_icon()` (`lib.rs:263`) — **Working**,
verified against the actual Rust, not a doc claim.

Close-to-tray: `on_window_event` intercepts `WindowEvent::CloseRequested`,
calls `api.prevent_close()` and `window.hide()` instead of exiting
(`lib.rs:391-397`) — **Working**, matches the README's "Closing hides to the
tray" claim (`Dashboard/README.md:35`).

Single instance: `tauri_plugin_single_instance` registered
(`lib.rs:357-361`), focuses the existing window on a second launch —
**Working**, dependency present in `Cargo.toml:19` and actually invoked.

Autostart: `tauri_plugin_autostart` registered (`lib.rs:363-366`),
`set_autostart`/`get_autostart` commands (`lib.rs:198-213`) and a checkable
tray item wired to `app.autolaunch()` — **Working** (uses the OS Run-key
mechanism via the plugin, not a hand-rolled registry write).

### 1.4 "Desktop mode" (Rainmeter-like widget layer)

`enter_desktop_mode` (`lib.rs:165-175`) sets non-resizable, skip-taskbar,
always-on-bottom (`set_always_on_bottom(true)`), sizes/positions the window to
the work area, and shows it. `enter_dashboard_mode` (`lib.rs:177-185`)
reverses this. Both are invoked from `Dashboard/web/tauri-shell.js`
(`invoke('enter_desktop_mode', ...)` at `tauri-shell.js:71`), driven by a
small reducer state machine in `Dashboard/web/desktop-mode-state.js:1-48`
(mode/clickThrough/editing/resumeClickThrough). CSS in `tauri-shell.js:14-34`
hides dashboard chrome (wallpaper image, top/dock bars, page dots) when
`.nova-desktop-mode` is set. **Working** — this is a real feature, not a stub;
it is gated behind `window.__TAURI__` (`tauri-shell.js:5`) so it is inert when
the page loads in a plain browser (matches the doc's "INERT in a plain
browser" claim, `Dashboard/README.md:53`).

### 1.5 Minimize / restore / resize / drag

- `win_minimize`, `win_toggle_maximize`, `win_hide`, `win_show`
  (`lib.rs:134-161`) are real Tauri commands using the native `WebviewWindow`
  API — **Working**, but no caller in the JS was found for `win_minimize` or
  `win_toggle_maximize` outside `tauri-shell.js`'s own `win_show` call
  (`tauri-shell.js:111`); the custom title bar with min/max/close buttons that
  `Dashboard/README.md:33-34` describes was not located in `index.html`'s
  markup search — **Needs manual verification** (title-bar buttons may exist
  in the HTML template sections not grep-matched by the patterns used, or the
  doc line is aspirational).
- In-page window drag/resize/snap (the simulated "app windows" — Chrome,
  Notepad, etc. opened as floating cards inside the web page when not
  `st.live`-resolvable, see §1.7) is implemented purely in JS:
  `Dashboard/web/dashboard-enhancements.js:619-736` (`raiseWindow`,
  `beginWindowOperation`, `moveWindowOperation`, snap-to-edge via
  `layout-engine.js:85-114`). This is a **simulated** window manager inside
  the page DOM, unrelated to the real OS window — **Working as a UI
  simulation**, not an OS-level multi-window feature.

### 1.6 Widget layout persistence

Confirmed **file-based only in the sense of `localStorage`**, not a backend
file: `Dashboard/web/layout-engine.js:66-69` (`pageStorageKey` →
`nova.desktop.layout.v2.page.{n}`), written by
`dashboard-enhancements.js:566-572` (`saveLayout` →
`localStorage.setItem(...)`) and read back by `restoreLayouts()`
(`dashboard-enhancements.js:71-78`). Dashboard widget picks/settings
(`nova.widgets`, `nova.settings`) persist the same way in `index.html:786-797`
(`persistMaybe`). None of this reaches the Python backend or a file on disk —
it lives in the WebView2/Chromium profile's local storage
(`%LOCALAPPDATA%\NOVA\edge-profile` exists on disk, confirming the WebView2
profile directory is real). **Working**, but "layout persistence" is
per-machine-profile, not portable/backed-up by NOVA itself.

### 1.7 Page navigation (5 pages)

`PAGE_COUNT = 5` (`layout-engine.js:1`), pages named `['Dashboard', 'NOVA +
Second Brain', 'Apps & Files', 'Calendar', 'Agent Control']`
(`dashboard-enhancements.js:16`) / `['Dashboard', 'NOVA', 'Apps & Files',
'Calendar', 'Agent']` (`index.html:1103`). Navigation is a CSS transform
carousel (`index.html:1104-1113`, `go()`/dot clicks/arrow keys/swipe via
`endDrag()` at `index.html:1005-1008`), each page an isolated
`data-page-canvas` with `overflow:hidden; isolation:isolate` — **Working**,
purely client-side, no backend involvement.

### 1.8 Live WebSocket data flow

Server → client message types actually published by `Hub.publish`
(`Dashboard/server.py:56-85`) and handled in `onLive()`
(`Dashboard/web/index.html:832-899`): `snapshot, stats, spotify, weather,
phase, activity, activity_seed, tasks, talk, transcript, obsidian, approvals,
usage, apps, briefing, integrations, mail, calendar, notify`. This list
matches `Dashboard/web/nova-integration.js:5-10`'s `DATA_TYPES` contract
exactly (both are version `1.1.0`, `server.py:40` / `nova-integration.js:4`).

Client → server action types actually sent via `sendLive()`
(`index.html:824-827`) and handled in `actions.handle()`
(`Dashboard/actions.py:55-255`): `media, launch (legacy), app_action,
pin_app, refresh_apps, open_folder, open_recent, sync_integrations, task,
forget, approval, delegate`. `nova-integration.js:11-14`'s `ACTION_TYPES`
list omits `launch` (correctly — it's a legacy/test-only path per
`actions.py:73-76`) — contract is internally consistent. **Working**, and the
origin check (`_origin_allowed`, `server.py:88-97`) restricts `/ws` to the
same-origin page or the two `tauri://`/`http(s)://tauri.localhost` origins,
rejecting arbitrary websites — a real (if basic) CSRF-style guard, appropriate
for a localhost-bound service.

### 1.9 Multi-monitor / display-scaling

No explicit multi-monitor handling was found. `workArea()`
(`tauri-shell.js:53-61`) reads `window.screen.availLeft/availTop/availWidth/
availHeight`, which on Windows reflects only the monitor the window currently
sits on — desktop mode will size/position correctly on whichever monitor the
window is on, but there is no code enumerating other monitors or moving the
widget layer to a specific one. DPI/scaling: Tauri/WebView2 handles OS display
scaling transparently by default; no custom `LogicalSize` vs `PhysicalSize`
handling bugs were found, but no explicit scaling tests exist either. **Status:
Present but minimal** — works for the common single/primary-monitor case,
**Needs manual verification** on multi-monitor / mixed-DPI setups.

### 1.10 Startup / shutdown / crash recovery

- Startup: `Start-NOVA.ps1` starts at most one voice agent (checked via
  `Get-CimInstance Win32_Process` command-line match, `Start-NOVA.ps1:23-30`)
  and at most one dashboard (`Get-Process -Name 'NOVA'` check,
  `Start-NOVA.ps1:43-44`) — **Working**, idempotent.
- Shutdown: `quit_app` kills the Python child before exiting
  (`lib.rs:225-230`), and the top-level Tauri `RunEvent::Exit` handler also
  kills the backend as a second safety net (`lib.rs:400-405`) — **Working**,
  no orphaned `python.exe`/`pythonw.exe` process should be left behind on a
  clean quit.
- **Crash recovery: Missing.** If `server.py` crashes after startup (e.g. an
  unhandled exception in a background loop), nothing in `lib.rs` detects the
  dead child and restarts it automatically — the only path to a fresh backend
  is the user manually clicking "Restart NOVA" in the tray
  (`lib.rs:319-324`, calls `restart_backend`). `ensure_backend()`
  (`lib.rs:97-104`) only runs once, at `setup()` time
  (`lib.rs:385-390`). There is no health-check polling loop, no
  `is_backend_up()` recheck after startup, and no auto-respawn-on-exit logic
  for the `Child` handle. If the Tauri app itself crashes, nothing restarts
  it either (no watchdog process, no Windows service). **Gap, worth flagging
  to Ahmed** if unattended reliability matters.

### 1.11 Icon/app wiring matrix

Frontend apps resolve to a backend record only if `app_registry.build_registry()`
(`Dashboard/app_registry.py:284-311`) discovers a matching Start Menu
shortcut (`discover_shortcuts`, `.py:126-152`), a Win32 uninstall-registry
entry with a `.exe` icon (`discover_win32_registry`, `.py:155-194`), a UWP
app via `Get-StartApps` (`discover_uwp`, `.py:197-231`), or one of two
hardcoded builtins (File Explorer, Settings, `.py:234-239`). Every click goes
through `openApp()` (`index.html:1016-1025`): if `st.live` and a resolved
`appId` exists, it sends `{type:'app_action', id, action:'activate'}`; **only
if that send fails or there is no live `record.id` does it fall back to a
fake in-page window** (`index.html:1021-1024`, `pushActivity('Tool',
'apps.launch(...)')` — this is the "looks like it launched, actually just
opened a simulated card" failure mode). `app_action` is handled server-side
by `actions.perform_action()` (`app_registry.py:388-402`), which calls
`_start()` → `os.startfile(record.launch_target)` (`.py:335-345`) for
`launch`/first `activate`, or `_window_action()`
(`.py:372-385`, real `ShowWindow`/`SetForegroundWindow`/`PostMessageW` calls)
for focus/minimize/maximize/restore/close on an already-running window found
via `EnumWindows` (`.py:348-369`) matched against `record.process_names`.

| UI Element | Frontend File | Handler | Backend Endpoint | Tool/Service | Current Status | Problem | Required Fix |
|---|---|---|---|---|---|---|---|
| Dock: Chrome | `index.html:1256` (`dockApps`) → `mkApp()` `index.html:1184-1194` | `openApp()` `index.html:1016` | `app_action` → `actions.py:88-97` | `app_registry.perform_action` → `os.startfile` | **Working** if Chrome is discovered by `discover_shortcuts`/`discover_win32_registry` (renamed via `APP_DISPLAY_RENAMES`, `app_registry.py:31-36`); **Partially working** (falls back to fake window) if not found | Discovery depends on a real Start Menu shortcut or uninstall-registry icon path existing | None — works as designed when Chrome is actually installed with a Start Menu entry |
| Dock: VS Code | same path | same | same | same | **Working** if "Visual Studio Code" shortcut exists (renamed to "VS Code") | Same discovery dependency | None |
| Dock: Terminal | same path | same | same | `KNOWN_PROCESSES["Terminal"] = ("windowsterminal.exe",)` `app_registry.py:46` | **Working** if Windows Terminal Start Menu shortcut exists | — | — |
| Dock: development assistant | same path | same | same | `KNOWN_PROCESSES["development assistant"] = ("development assistant.exe",)` `app_registry.py:43` | **Working** if the development assistant desktop app created a Start Menu shortcut | Only launches/focuses the desktop app — no deep link into a conversation | — |
| Dock: ChatGPT | same path | same | same | `KNOWN_PROCESSES["ChatGPT"] = ("chatgpt.exe",)` `app_registry.py:44` | Same pattern as development assistant | — | — |
| Dock: Obsidian | same path | same | same | `KNOWN_PROCESSES["Obsidian"] = ("obsidian.exe",)` `app_registry.py:45` | **Working** if the Obsidian desktop app is installed | — | — |
| Dock: Spotify | same path | same | same | `KNOWN_PROCESSES["Spotify"] = ("spotify.exe",)` `app_registry.py:47` | **Working** | — | — |
| Dock: **Search** | `index.html:1256, 1261, 1264` | `name === 'Search'` special-cases to `this.toggleCmd()` | none — never reaches the WebSocket | NOVA's own Ctrl+K command palette (`index.html:1044-1047`) | **Working, but not what the icon implies**: does **not** open Windows Search/Start menu search — it opens NOVA's local delegate/command palette | Not a bug, but worth relabeling in the UI if the intent is "search my PC" | Rename the tile or add a real `explorer.exe search-ms:` path if Windows Search was the intent |
| Start menu grid: any of the ~60 names in `allAppNames` (`index.html:1196`), incl. **Chrome, Edge (`Microsoft Edge`), Outlook, Settings, Terminal, VS Code, Ollama, Obsidian, Spotify, development assistant, ChatGPT** etc. | `index.html:1196-1199` (`mkApp` per name) | `openApp()` | `app_action` | `app_registry` discovery (shortcuts / win32 registry / UWP `Get-StartApps`) | **Working** for anything actually installed with a discoverable shortcut/registry entry/UWP AUMID; **Partially working / silent fallback to fake window** for anything in the hardcoded `allAppNames` list that is not actually installed on this machine (e.g. Xbox, Bixby, Samsung Notes, PENUP — these are cosmetic entries copied from a generic Windows Start-menu mock and will almost never resolve to a real `appId`) | The 60-name list (`index.html:1196`) is static/hardcoded demo content, not derived from `st.allAppNames` unless the live feed supplies it (it does: `apps` message sets `s.allAppNames = m.all`, `index.html:879`) — so once live, the *real* Start-menu-derived list replaces the demo list. In demo/offline mode the fake list is shown and every tile opens a fake window | None needed once live; document that the offline fallback list is cosmetic |
| **development assistant** | — | — | — | — | **Missing.** No occurrence of "development assistant" anywhere in `Dashboard/web/index.html`, `support.js`, `dashboard-enhancements.js`, or `app_registry.py` (`KNOWN_PROCESSES` has no development assistant entry, and it is absent from `allAppNames`) | Not wired at all — clicking nothing opens development assistant specifically; it would only appear if a generic Start-Menu shortcut named "development assistant" is discovered and happens to render via the fallback OKLCH gradient tile with no branding | Add a `KNOWN_PROCESSES`/`APP_DISPLAY_RENAMES` entry and a dock/allApps tile if development assistant desktop presence is wanted |
| File Explorer | `index.html:1195, 1256` | `openApp()` | `app_action` | `_builtins()` → `explorer.exe` (`app_registry.py:236`) | **Working** — always resolves, no discovery dependency | — | — |
| Settings | `allAppNames` list | `openApp()` | `app_action` | `_builtins()` → `ms-settings:` UWP URI (`app_registry.py:237`) | **Working** — `os.startfile("ms-settings:")` reliably opens Windows Settings | — | — |
| Recent files (Obsidian/VS Code/Edge icons by extension) | `index.html:1200-1211` | `open()` → `sendLive({type:'open_recent', id})` | `actions.py:126-142` | `security.can_open_recent_target` + `os.startfile` | **Working** — resolves `.lnk` targets server-side via `resolve_shortcut_targets` (`security.py:170-182`), blocked for sensitive paths (`safe_paths.py`/`security.py` denylist) | — | — |
| Quick folders (Desktop/Downloads/Documents/Obsidian Vault + up to 4 Desktop subfolders) | `index.html:1392` | `open()` → `sendLive({type:'open_folder', name})` | `actions.py:115-124` | `os.startfile` on a real path built in `feeds.scan_apps()` (`feeds.py:464-490`) | **Working** | — | — |
| Media prev/play-pause/next | `index.html:1373-1374, 1407` | `sendLive({type:'media', action})` | `actions.py:65-71` | `_press_key()` → `keybd_event` virtual media keys (`actions.py:27-30`) | **Working** — real OS-level media key injection, not app-specific | Requires *some* media app to be listening; not Spotify-specific | — |
| Pin/unpin app tile | `index.html:1192` | `sendLive({type:'pin_app', id, pinned})` | `actions.py:99-106` | `app_registry.set_pinned` → writes `~/.nova/dashboard_apps.json` (`app_registry.py:251-255`) | **Working** — persisted to a real file on disk, survives restarts | — | — |
| NOVA Activity / execution timeline | Agent Control page widgets (`index.html` timeline/activity rendering, `index.html:850-861`) | n/a (data-only, no click-to-launch) | `activity`/`activity_seed` messages | `feeds.tools_log_loop` tailing `nova_tools.log` (`server.py:214-219`, `feeds.py:552-581`) | **Working** — this is a live data feed, not an app launcher; correctly reflects real tool calls from the running agent | — | — |
| Approve/Deny (agent action approvals) | `index.html:1302-1303` | `sendLive({type:'approval', id, decision})` | `actions.py:195-233` | `nova_bridge.CommandStore.enqueue_approval` → private JSON envelope consumed by the live LiveKit agent process (`nova_bridge.py`) | **Working** only while an agent session (`console`/`dev`) is actually running; otherwise queued up to 2 minutes then presumably expires unconsumed | Approval silently times out with no dashboard-visible "expired" message beyond the audit log's own `expired` status (`feeds.py:669`) | Consider a toast/notify on expiry, currently only shows up as an activity-feed status flip |
| Ctrl+K delegate ("ask NOVA to do X") | `index.html:1057` | `sendLive({type:'delegate', text})` | `actions.py:235-253` | same `CommandStore` bridge, `enqueue_delegate` | **Working**, same live-session dependency as Approve/Deny | — | — |
| "Sync Now" (Email & Calendar) | `index.html:1434` (`if (!this.sendLive({ type: 'sync_integrations' }))...`) | `actions.py:145-169` | `nova_integrations.runtime.get_runtime().sync.sync_all()` | **Broken in the current venv** (see Part 2 §2.5) — the handler's own `except Exception` catches the failure and returns a "Synchronization failed" notification (`actions.py:165-169`), so the UI degrades gracefully rather than crashing | `keyring`/`msal`/`google-auth-oauthlib`/`googleapiclient` are not installed (verified: `ModuleNotFoundError`), so `get_runtime()` raises `SecretStoreError` before any network call | `pip install -r requirements-email-calendar.txt` into the project venv |

**Duplicate/dead code found:** `Dashboard/app_icons.py` (imported by
`app_registry.py:20`) is the icon extractor actually in use.
`Dashboard/appicons.py` is a near-identical, independently-implemented icon
extractor (pywin32-based instead of raw ctypes) that is **never imported by
any Python file under `Dashboard/`** (confirmed with a scoped grep for
`appicons` across `Dashboard/*.py` — zero hits). **Status: Dead or unused** —
safe to delete, or the duplication should be resolved/documented so a future
edit to icon logic doesn't silently touch the wrong file.

### 1.12 Doc-vs-code discrepancy found

`Dashboard/README.md:152` states *"Calendar page is still design demo
data (no Google Calendar/ICS wired)"*. This is now **stale**: `server.py`'s
`integrations_loop` (`server.py:286-292`) publishes real `calendar`/`mail`/
`integrations`/`briefing` messages from `integration_feeds.py`
(`integration_feeds.py:184-338`), and `index.html:1215` (`liveCalendar =
st.calendarPayload && st.calendarPayload.available !== false ?
st.calendarPayload : null`) genuinely prefers live calendar data over the
demo fallback when it is available. The calendar page **is** wired to
`nova_integrations`' SQLite database (a 77 KB database exists at
`%LOCALAPPDATA%\NOVA\integrations\nova_integrations.db`, last modified
2026-07-21 19:30, strongly suggesting it holds real synced rows, though row
contents were not read per the read-only/no-secrets constraint). Whether it
currently *shows* real events depends on whether any account was ever
connected — see Part 2. **Recommend updating the README** rather than trusting
its "known limitation" note at face value.

---

## Part 2 — Integration readiness

### 2.1 Spotify (`tools/media.py`, `Dashboard/feeds.py`)

Two independent, non-conflicting implementations of "what's playing":
window-title scraping via `EnumWindows`/`GetWindowText` (`tools/media.py:11-68`,
duplicated almost verbatim in `Dashboard/feeds.py:109-140`) needs no
credentials and works the moment Spotify is open. The Spotify Web API path
(`tools/media.py:74-108`, `Dashboard/feeds.py:147-183`) needs
`SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` in `.env` and a cached OAuth token
at `PROJECT_ROOT/.spotify_cache` (existence confirmed via `.gitignore:5-6`
coverage; content not read). **Status: Working** per DEVELOPMENT.md's own
verification note and consistent with the code read here — playback control
(`play_spotify_song`, `tools/media.py:256-322`) needs Spotify Premium and an
active device, everything else (media-key transport control, now-playing
display) works without Premium. `open_browser=False` is correctly set in the
dashboard's `SpotifyOAuth` construction (`feeds.py:176`) so a stale/expired
cache fails closed instead of popping a browser window from a background
process — good practice, no security concern found.

### 2.2 Obsidian (`tools/obsidian.py`)

Read/write is properly sandboxed: `resolve_obsidian_note()`
(`tools/obsidian.py:49-72`) resolves paths and rejects anything outside the
vault via `Path.relative_to()` plus an explicit `.obsidian` config-folder
block; `resolve_nova_memory_folder()` (`.py:157-183`) further restricts
writes to under `<vault>/NOVA/`, rejecting `.`/`..`/`.env*`/`.obsidian`
segments. `write_memory_note()` (`.py:198-232`) never overwrites (always
finds a free filename by incrementing a counter, `.py:220-224`) and refuses
to save anything matching `SECRET_MARKERS` (`.py:14-23`, `.py:209-210`) — a
simple substring heuristic (`.env`, `api key`, `bearer `, `sk-`, `token`,
etc.), which is a **best-effort, not a guarantee** (won't catch a secret with
unusual formatting) but is a reasonable belt-and-suspenders check for an
LLM-authored note. **Status: Working**, matches DEVELOPMENT.md's claims.

### 2.3 Gmail/Google Calendar + Microsoft Graph/Outlook (`nova_integrations/`)

This is **substantial, largely real implementation work**, not scaffolding:

- **Google** (`nova_integrations/connectors/google_workspace.py`): real
  `InstalledAppFlow` OAuth (`.py:57-82`), real Gmail History API incremental
  sync with 404 cursor-reset recovery (`.py:114-185`), real Calendar API
  `syncToken` incremental sync with 410 cursor-reset recovery
  (`.py:187-278`), real body fetch + HTML stripping
  (`.py:280-289, 425-441, 486-492`), correctly scoped
  (`gmail.metadata` vs `gmail.readonly` depending on content mode,
  `.py:69-71`).
- **Microsoft** (`nova_integrations/connectors/microsoft_graph.py`): real MSAL
  `PublicClientApplication.acquire_token_interactive` (no client secret,
  `.py:60-82`), real Graph delta-query sync for mail and calendar with
  410/429/401/403 handling including a distinct
  `AdminApprovalRequired` path for tenant-blocked consent (`.py:112-267,
  301-331`) — this directly implements the FGCU scenario documented in
  `docs/FGCU_AND_OAUTH_SETUP.md:5-9` (Microsoft-tenant admin-consent
  detection, not bypassed).
- **Secrets**: `nova_integrations/secrets.py` uses the OS keyring (Windows
  Credential Manager via `python-keyring`) with an explicit refusal to fall
  back to plaintext storage (`secrets.py:35-39`, raises `SecretStoreError` if
  the resolved keyring backend name contains "fail" or "plaintext"). No
  token file, no plaintext cache — matches `docs/SECURITY_MODEL.md:7`'s claim.
  Token cache values themselves were not read (per audit constraints).
- **Storage**: `nova_integrations/storage.py` is a real SQLite schema with a
  migrations table (`storage.py:55-72`), `accounts`, `mail_messages`,
  `calendar_events`, `notification_receipts`, `settings`, `audit_events`
  tables (`storage.py:76-165`) — normalized metadata only, no body/attachment
  columns, matching `docs/SECURITY_MODEL.md:8`.
- **Wiring into the live agent — CONFIRMED, contradicting the audit
  prompt's uncertainty**: `agent.py:15-24` imports
  `list_connected_accounts, sync_email_calendar, get_unread_emails,
  read_email, get_calendar_agenda, get_next_event, find_calendar_conflicts,
  get_daily_briefing` from `tools`, and `Assistant.__init__`
  (`agent.py:161-170`) registers all eight as live function tools on the
  voice agent. `tools/email_calendar.py` itself calls `get_runtime()`
  (`nova_integrations/runtime.py`) lazily per tool invocation. **This is
  fully wired**, not just present.
- **read_email body access is gated through the existing permission
  engine** (`tools/email_calendar.py:17-28`, registers a `SENSITIVE`-level
  `read_email_body_cloud` policy with `allow_session_approval=False`, i.e.
  every full-body read needs a fresh one-time approval), and that approval
  will surface in the Dashboard's existing Approve/Deny queue because both
  systems write to/read from the same audit-log-driven mechanism
  (`nova_policy` engine → `audit_logs/nova_actions.jsonl` →
  `Dashboard/feeds.py`'s `ApprovalsTracker`). Good cross-cutting integration,
  actually connects two subsystems that were built somewhat independently.
- **Prompt-injection defense**: every tool that surfaces provider text
  explicitly labels it as untrusted data and instructs the model not to treat
  sender/subject/title/location as commands (`tools/email_calendar.py:85,
  151, 181, 217`), and email bodies are wrapped in an explicit
  "BEGIN/END UNTRUSTED EMAIL CONTENT" delimiter with an inline warning
  (`.py:149-153`). This is a deliberate, well-executed defense, not an
  afterthought.

**Status: Present and wired, but currently Broken at runtime** — see 2.5.

### 2.4 Startup wiring (`nova_startup.py`, `nova_integrations/startup_hook.py`)

`nova_integrations/startup_hook.py:13-22` (`start_integrations_safely`)
starts the background `IntegrationSupervisor` (a daemon thread polling every
`config.sync.interval_seconds`, default 180s, with per-account exponential
backoff on `RateLimited`, `nova_integrations/supervisor.py:44-101`). This
hook is called from `nova_startup.py:305` inside `run_standby()`, which is a
**separate standby entry point** (`python nova_startup.py`) distinct from
both `agent.py` (the LiveKit voice session) and `Dashboard/server.py`. No
reference to `nova_startup.py` was found in `Start-NOVA.ps1`,
`Dashboard/start_dashboard.ps1`, or any Tauri Rust code — **Status: Present
but not wired into the actual launch path** the user runs. The background
supervisor (continuous incremental sync every 3 minutes) only runs if
`nova_startup.py` is separately launched (manually, or via an
un-audited Windows Scheduled Task/Run-key entry that was not found in this
repo). The agent-side tools (`sync_email_calendar`) and the dashboard's "Sync
Now" button both trigger **on-demand** syncs directly through
`get_runtime()`, so integration functionality does not strictly require
`nova_startup.py` — but continuous background sync (so mail/calendar are
already fresh before the user asks) does.

### 2.5 Critical finding: integration dependencies are not installed

```
venv\Scripts\python.exe -c "import msal"                  -> ModuleNotFoundError
venv\Scripts\python.exe -c "import google_auth_oauthlib"  -> ModuleNotFoundError
venv\Scripts\python.exe -c "import googleapiclient"       -> ModuleNotFoundError
venv\Scripts\python.exe -c "import keyring"                -> ModuleNotFoundError
venv\Scripts\python.exe -c "import winotify"                -> ModuleNotFoundError
venv\Scripts\python.exe -c "import google.auth"            -> OK
venv\Scripts\python.exe -c "import requests"                -> OK
```

`requirements-email-calendar.txt` lists `google-auth-oauthlib`,
`google-api-python-client`, `msal`, `keyring`, `winotify` as a **separate,
not-yet-installed** requirements file (`requirements-email-calendar.txt:1-2`,
"Install into NOVA's existing virtual environment" — i.e. this is a manual
step that was documented but not completed in this venv).

Directly reproduced the failure:
```
venv\Scripts\python.exe -c "from nova_integrations.runtime import get_runtime; get_runtime()"
-> SecretStoreError: Install the 'keyring' package before connecting accounts.
```
This happens because `build_runtime()` (`nova_integrations/runtime.py:47-49`)
eagerly constructs `KeyringSecretStore()`, whose `__init__`
(`nova_integrations/secrets.py:29-33`) does `import keyring` and converts the
`ImportError` into `SecretStoreError` immediately — **every** `get_runtime()`
call fails right now, which means:

- `list_connected_accounts`, `sync_email_calendar`, `get_unread_emails`,
  `read_email`, `get_calendar_agenda`, `get_next_event`,
  `find_calendar_conflicts`, `get_daily_briefing` (all 8 live agent tools)
  will all raise/fail the moment NOVA calls any of them.
- The dashboard's "Sync Now" button (`actions.py:145-169`) fails gracefully
  (caught, shown as a notification) — **not** a crash, but sync cannot
  actually run.
- The dashboard's **read-only** feeds (`integration_feeds.status_message`,
  `mail_message`, `calendar_message`) do **not** go through `get_runtime()` —
  they call `load_config()` + `IntegrationDatabase(...)` directly
  (`integration_feeds.py:72-82`), which needs no keyring. So the Calendar
  page and mail/notification widgets can still **display whatever was last
  synced** into the 77 KB SQLite database while the dependencies were
  presumably present, but that data is now frozen — no new sync can occur
  until the missing packages are installed.

**Status: Broken** (import-time failure, not a partial/degraded state) for
any *write*/*sync* path; **Working (stale)** for the *read-only* dashboard
display path. Also confirmed `google_oauth_desktop_client.json` does **not**
exist at `%LOCALAPPDATA%\NOVA\integrations\` — so even after reinstalling
dependencies, Google account connection cannot proceed until that OAuth
client file is placed there per `docs/FGCU_AND_OAUTH_SETUP.md:41`; only
Microsoft/FGCU connection is currently possible (assuming a `client_id` is
present in `config.json`, which was not opened per the no-secrets
constraint — **Needs manual verification**).

**Required fix**: `venv\Scripts\python.exe -m pip install -r
requirements-email-calendar.txt`.

### 2.6 FGCU-specific handling

Confirmed real, not just documented: `microsoft_graph.py:343-351`
(`_raise_auth_result`) inspects the MSAL error/description for `"admin"`,
`"consent"`, or `"aadsts65001"` and raises a distinct
`AdminApprovalRequired` exception with a message directing the user to
contact their tenant admin — this is exactly the FGCU tenant-consent scenario
`docs/FGCU_AND_OAUTH_SETUP.md:7,23` describes, and it is not bypassed (no
attempt to use client-credential/app-only flow, no attempt to prompt for a
password). `AccountCategory.SCHOOL` (`nova_integrations/models.py:16-19`)
exists as a first-class category alongside `PERSONAL`/`WORK`, and the CLI's
`accounts connect --category school` (`nova_integrations/cli.py:31`)
supports labeling an FGCU account as such — used only for display/notification
color-coding in the dashboard (`Dashboard/integration_feeds.py:30-34`), not
for any different security handling.

### 2.7 Windows notifications

Two independent notification code paths exist and are **not the same
system**:
- `nova_integrations/notifications.py:31-51` (`WindowsToastNotifier`) — used
  only for the email/calendar integration's own "new mail" toast, via the
  `winotify` package, which is confirmed **not installed** in the venv
  (§2.5). Falls back to logging a failed toast rather than crashing sync
  (`.py:49-51`), so a missing `winotify` degrades silently to "no toast, sync
  still records the notification receipt in SQLite" — **Broken** (winotify
  missing) but fails soft.
- `Dashboard/actions.py`'s `_notify()` (`.py:43-44`) and the `notify`
  WebSocket message type (`server.py`/`index.html:897`) are the **dashboard's
  own** in-app toast system (`pushNotif`, `index.html:998-1004`), rendered
  inside the web page itself, not a real Windows Action Center toast. These
  are two separate concepts that share the word "notification" — worth
  clarifying if Ahmed expects real Windows toasts from dashboard events (he
  currently only gets them from the (currently broken) email integration
  path).

### 2.8 System stats (psutil) and weather (wttr.in)

Both straightforward and confirmed real: `feeds.stats_message()`
(`feeds.py:97-102`) calls `psutil.cpu_percent()`/`psutil.virtual_memory()`
directly, polled every 2s (`server.py:167-170`) — **Working**, no
configuration needed, `psutil` is a base dependency already in `requirements.txt`
(confirmed installed — `app_registry.py` imports it at module load and the
dashboard runs). `feeds.weather_message()` (`feeds.py:232-250`) hits
`https://wttr.in/{city}?format=j1` with a 10s timeout and a broad
`except Exception: return None` (degrades to "no weather card" rather than
crashing the polling loop), optional `NOVA_CITY` env var, no API key —
**Working**, matches DEVELOPMENT.md's claim exactly.

---

## Summary for the caller

Icon wiring matrix: of the ~13 distinct UI-element rows traced end-to-end,
**10 reach a real OS-level launch call** (`os.startfile`/`ShowWindow`/
`keybd_event`) when the target app is actually installed and discoverable —
Chrome, VS Code, Terminal, development assistant, ChatGPT, Obsidian, Spotify, File Explorer,
Settings, recent files, quick folders, and media keys all genuinely work.
**1 is mislabeled** (the "Search" dock tile opens NOVA's own command palette,
not Windows Search). **1 is entirely unwired** (development assistant has no icon, no
`app_registry` entry, no dock/list presence anywhere). The generic ~60-name
Start-menu grid is only real once the dashboard is `live` and the server has
supplied `st.allAppNames`; offline/demo mode shows a cosmetic hardcoded list
where most tiles (Xbox, Bixby, PENUP, etc.) will never resolve to a real app
and silently open a fake in-page window instead — not a bug, but worth
knowing it's there. Also found: `Dashboard/appicons.py` is dead, unused
duplicate code of `Dashboard/app_icons.py`; `window-vibrancy` is a dead Cargo
dependency (declared, never called); there is no crash-auto-restart for the
Python backend child process.

The single biggest integration gap: the entire Gmail/Outlook stack
(`nova_integrations/`) is genuinely well-built and fully wired into
`agent.py`'s live tool list and the dashboard's UI — but it is **currently
non-functional** because `keyring`, `msal`, `google-auth-oauthlib`, and
`google-api-python-client` are not installed in the project venv, so every
call to `get_runtime()` throws `SecretStoreError` immediately. The dashboard
still shows old data from a 77 KB SQLite database that was populated at some
earlier point, but nothing can sync until `pip install -r
requirements-email-calendar.txt` is run — and Google account connection
additionally needs a `google_oauth_desktop_client.json` placed at
`%LOCALAPPDATA%\NOVA\integrations\`, which does not currently exist.
