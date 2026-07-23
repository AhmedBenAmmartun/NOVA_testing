# Dashboard Wiring Plan — 2026-07-22

Unlike a typical "propose an architecture" wiring plan, this one documents
**what's already real and working** (per `DASHBOARD_AND_INTEGRATIONS_AUDIT.md`)
plus the specific gaps to close — because the centralized backend service,
app registry, and event contract Ahmed asked for already exist and are
functional, not scaffolding to design from scratch.

## 1. Current architecture (verified, not proposed)

```
Dashboard/nova-app (Tauri v2, Rust)          Dashboard/server.py (aiohttp, Python)
  spawns pythonw.exe Dashboard/server.py  →    binds 127.0.0.1:PORT only
  renders Dashboard/web/ in native WebView2     serves web/ static assets
  tray, click-through, desktop-mode, etc.       GET /health, GET /ws (WebSocket)
                                                 12 background asyncio loops
                                                        │
                                                        ▼
                                                   Hub.publish(type, payload)
                                                        │ fan-out to all clients
                                                        ▼
Dashboard/web/index.html  connectLive()  ←──── WebSocket /ws
  reads window.NOVA_BACKEND (Tauri) or
  location.host (plain browser) or
  falls back to support.js's simulated demo loops
```

Two-way: client → server via the same `/ws` socket, JSON messages handled
by `Dashboard/actions.py`'s `handle()`.

## 2. Backend service / IPC layer — already exists

`Dashboard/server.py` **is** the backend service Ahmed asked for. It is not
missing; it needs the fixes in `IMPLEMENTATION_ROADMAP.md` Stage 2 (crash
auto-restart), not a redesign. `nova_bridge.py`'s file-based `CommandStore`
is the separate IPC channel to the live voice-agent process (a different
process from the dashboard, per `PROJECT_STRUCTURE.md` §2) — atomic,
file-based, 2-minute command expiry, already working per prior verification.

## 3. Centralized application registry — schema as actually implemented

`Dashboard/app_registry.py`'s real record shape (reconstructed from its
actual field usage, not a hypothetical):

```json
{
  "id": "vscode",
  "name": "VS Code",
  "source": "shortcut | win32_registry | uwp | builtin",
  "launch_target": "C:\\...\\Code.exe  (or ms-settings: / explorer.exe / shell:AppsFolder\\<AUMID> for UWP)",
  "process_names": ["code.exe"],
  "icon_data_uri": "data:image/png;base64,...",
  "pinned": false
}
```

Real discovery order (`build_registry()`): Start Menu `.lnk` shortcuts
(`discover_shortcuts`) → Win32 uninstall-registry entries with an icon path
(`discover_win32_registry`) → UWP apps via `Get-StartApps`
(`discover_uwp`) → two hardcoded builtins (File Explorer, Settings). Display
names are normalized through `APP_DISPLAY_RENAMES`; known launchable process
names for window-focus matching live in `KNOWN_PROCESSES`. Icons are cached
via `app_icons.icon_data_uri` (ctypes-based extraction) — **not**
`Dashboard/appicons.py`, which is dead code, see `CLEANUP_PLAN.md`.

**Gap to close**: add a `KNOWN_PROCESSES`/`APP_DISPLAY_RENAMES` entry for
development assistant (currently the one traced UI target with zero wiring anywhere).

## 4. Event names and data contracts — already versioned and consistent

Both sides already agree on a versioned contract (`v1.1.0`,
`Dashboard/server.py:40` / `Dashboard/web/nova-integration.js:4`):

**Server → client** (`Hub.publish` types, handled in `onLive()`):
`snapshot, stats, spotify, weather, phase, activity, activity_seed, tasks,
talk, transcript, obsidian, approvals, usage, apps, briefing, integrations,
mail, calendar, notify`

**Client → server** (`actions.handle()` types):
`media, launch (legacy/test-only), app_action, pin_app, refresh_apps,
open_folder, open_recent, sync_integrations, task, forget, approval,
delegate`

No changes recommended here — the contract is internally consistent and
already exercised by 16 passing JS tests + 33 passing Python tests
(`Dashboard/tests/`).

## 5. Error-response format

`actions.py` handlers that can fail (`sync_integrations`, `open_recent`,
`open_folder`) currently catch exceptions and return an in-band
`{type: "notify", ...}` message rather than a distinct error envelope —
functional but informal. **Recommendation (not yet implemented)**: adopt a
consistent `{type: "error", source: "<action_name>", message: "..."}`
envelope for all handler failures, so the frontend can distinguish "this
specific action failed" from a generic toast. Low priority — current
behavior is not broken, just less structured than it could be.

## 6. App detection strategy — already implemented, documented above (§3)

## 7. Widget state storage — already implemented

`localStorage` only (`nova.desktop.layout.v2.page.{n}`, `nova.widgets`,
`nova.settings`), scoped to the WebView2 profile at
`%LOCALAPPDATA%\NOVA\edge-profile`. Per-machine, not synced/backed up by
NOVA itself. See `IMPLEMENTATION_ROADMAP.md` Stage 2 for the optional
backend-persistence upgrade.

## 8. Real-time NOVA activity events — already implemented

`feeds.tools_log_loop` tails `nova_tools.log` in real time and publishes
`activity`/`activity_seed` messages — genuinely reflects live tool calls
from the running agent process, not synthetic.

## 9. Authentication-state events

For email/calendar: `integration_feeds.py`'s `status_message` publishes
connected-account state (read-only, queries `IntegrationDatabase` directly,
no keyring dependency — this is why the Calendar/Mail *display* still works
even while `sync` is currently broken per NOVA-001/§2.5 of the dashboard
audit). For the dashboard itself: no user-facing login exists (it's a
localhost-bound, single-user app; origin-checked WebSocket handshake is the
only "auth" boundary, appropriately so for this threat model).

## 10. Notification events

Two distinct systems currently share the word "notification" — see
`DASHBOARD_AND_INTEGRATIONS_AUDIT.md` §2.7:
- Dashboard's own in-app toast (`notify` WS message → `pushNotif()`) — always works, no dependency.
- Real Windows Action Center toasts (`nova_integrations/notifications.py`, `winotify`) — currently broken, blocked on Stage 1's dependency install.

**Recommendation**: once `winotify` is installed, consider also routing
select dashboard-originated events (not just email) through real Windows
toasts, since the plumbing will already be there.

## 11. Email and calendar event design — already implemented

`integrations` (account/connection state), `mail` (unread + recent),
`calendar` (agenda), `briefing` (daily summary) message types are already
defined, published every 20s (`server.py`'s `BACKGROUND_LOOPS`), and consumed
by `index.html`. No new design needed — just needs live data once Stage 1/5
of the roadmap unblocks sync.

## 12. Security boundaries between dashboard and system tools

Already reasonably drawn, per the dashboard audit:
- `/ws` origin-checked (`_origin_allowed`) — rejects non-same-origin, non-Tauri pages.
- Recent-file/folder opens go through `security.py`/`safe_paths.py` sensitive-path denylists before any `os.startfile` call.
- `nova_bridge` delegate/approval commands re-enter the **same** `nova_policy.permission_engine` used by voice — no separate, weaker dashboard-only approval path (confirmed in `FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md` §3.4).
- Tauri capability grants are minimal (`capabilities/default.json`: window control + events only, no filesystem/shell/HTTP grants) — the webview itself cannot reach the filesystem directly even if compromised; all filesystem actions go through the Python backend's own validation.

**One gap**: `tauri.conf.json`'s `"csp": null` (NOVA-011) — defense-in-depth
recommendation, not an active exploit path given the above.

## 13. Recommended implementation order

Given most of the "wiring" already exists, the real order is the punch list
already in `IMPLEMENTATION_ROADMAP.md`:
1. Dependency install (unblocks calendar/mail live data — the biggest visible "dashboard doesn't show real data" complaint has a one-line fix).
2. Screen-capture permission gating (security, unrelated to dashboard but same priority tier).
3. Specialist-model routing decision (unblocks "model-routing status" dashboard display, currently nothing to show).
4. Dashboard-specific polish: development assistant icon, Search tile relabel, feeds.py logging, crash auto-restart, CSP.
