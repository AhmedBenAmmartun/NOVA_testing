# NOVA — Project Structure Inventory

Read-only inspection. Repo root: `C:\Users\ahmed\OneDrive\Desktop\AI Agent`.
Branch at time of audit: `nova-desktop-integration` (main: `main`).
`.env` was not opened; only variable *names* were read from `.env.example`
(the tracked template) and confirmed against `agent.py`/`nova_startup.py`
loader calls.

## 0. Git state — this materially changes how to read the tree

`git status` shows the working tree carries a **large uncommitted/staged
change set** (183 status lines) on top of commit `1da0f5a`. Everything
listed as `A` (added) below exists on disk and was inspected as real code,
but **is not yet part of any commit** on this branch. Five new top-level
Python packages appear this way: `nova_core/`, `nova_guardian/`,
`nova_integrations/`, `nova_policy/`, `providers/` — plus a large Dashboard
rewrite, `tests/`, `scripts/`, `config/`, and doc updates. Three inventory
zips also sit at repo root (`NOVA-Email-Calendar-Integration-for-development assistant.zip`,
`NOVA-Integration-Source-20260721-160110.zip`,
`NOVA-Missing-Source-20260721-161704.zip`) — untracked build artifacts from
whatever process staged this work, gitignored via `*.zip`.

## 1. Directory tree (noise pruned: `.git`, `venv`, `.venv`, `__pycache__`,
`.pytest_cache`, `node_modules`, `.pnpm-store`, `screenshots/`, `logs/`,
`conversation_logs/`, `Dashboard/nova-app/src-tauri/{target,gen}`,
`.nova-patch-backup/`, `.nova_integration_backup/` — the last two are
gitignored dated snapshots from earlier in-place patch runs, safe to ignore)

```
AI Agent/
├── agent.py                  LiveKit AgentServer entry point — THE voice agent
├── prompts.py                 SYSTEM_PROMPT (NOVA persona, Study/Quiz Mode choreography)
├── nova_bridge.py             CommandStore: atomic file-based inbox/outbox/heartbeat
│                               shared by the dashboard process and the agent process
├── nova_agent_bridge.py       Runs INSIDE the live agent process: polls nova_bridge,
│                               injects delegated text turns, resolves approve/deny
├── nova_startup.py            Separate standby supervisor (NOT imported by agent.py):
│                               Windows single-instance mutex, starts Guardian runtime
│                               + integrations supervisor, writes logs/nova_status.json
├── nova_wakeword.py            Standalone local wake-word listener ("Hey Jarvis"),
│                               never imported by agent.py — run manually/separately
├── offline_agent.py           Standalone CLI loop straight to tools.models.run_ollama;
│                               bypasses LiveKit/Gemini entirely, own load_dotenv calls
├── requirements.txt            Main dependency list (LiveKit stack + email/calendar deps
│                               folded in; no aiohttp pin even though Dashboard/server.py
│                               needs it — relies on a transitive install)
├── requirements-email-calendar.txt   Near-duplicate of the email/calendar subset of
│                               requirements.txt (kept as an optional standalone installer)
├── .env / .env.example        Secrets file (not opened) / tracked template documenting
│                               every variable name NOVA reads (LiveKit, Gemini, OpenAI,
│                               Groq, Ollama, provider routing/budget, Guardian, vision
│                               privacy exclusions, Spotify)
│
├── core/                      OLD routing scaffolding (task.py, router.py,
│                               orchestrator.py). Confirmed by repo-wide grep: **imported
│                               by nothing**. Dead code, superseded by nova_core/.
├── nova_core/                 NEW routing package: configuration.py (profiles/env),
│                               provider_registry.py, cloud_budget.py, router.py
│                               (ModelRouter/RoutingAttempt). Actually imported — by
│                               tools/specialist.py only.
├── providers/                 Provider adapters used by nova_core: base.py (ModelProvider
│                               ABC + error types), openai_provider.py, ollama_provider.py.
│                               providers/__init__.py exports only OpenAI + Ollama.
│                               groq_provider.py EXISTS on disk but is not imported by
│                               __init__.py, provider_registry.py, or anywhere else —
│                               orphaned/unwired file.
├── nova_guardian/              Local security/vision monitor package: ambient_vision.py,
│                               config.py, events.py, security_monitor.py, state.py,
│                               window_monitor.py, runtime.py (GuardianRuntime,
│                               get_guardian_runtime — the shared singleton). Imported by
│                               tools/guardian.py (agent-facing tools) and nova_startup.py
│                               (standby supervisor). NOT imported by agent.py directly.
├── nova_integrations/          Read-only Gmail/Outlook/Calendar package: models.py,
│                               runtime.py (IntegrationRuntime/get_runtime), accounts.py,
│                               connectors/{google_workspace,microsoft_graph,base}.py,
│                               secrets.py (keyring-backed), storage.py, sync.py, cli.py,
│                               supervisor.py, startup_hook.py, notifications.py. Imported
│                               by tools/email_calendar.py and nova_startup.py.
├── nova_policy/                Central approval/permission engine: engine.py
│                               (PermissionEngine, ActionPolicy, PermissionLevel,
│                               module-level `permission_engine` singleton). Imported by
│                               tools/permissions.py, tools/email_calendar.py, and
│                               nova_agent_bridge.py (dashboard-approval resolution).
│
├── tools/                      38 function-tool modules, re-exported through
│                               tools/__init__.py:
│   ├── __init__.py              Central export surface; agent.py imports names from here
│   ├── common.py                Sandbox helpers + shared `logger` (nova_tools.log)
│   ├── desktop.py                open/close/restart app, website, window control,
│                                 notifications, quick settings, virtual desktops
│   ├── files.py                  notes + file ops/finder/open + Desktop create + course
│                                 materials (pypdf)
│   ├── conversations.py          SessionConversationRecorder (auto-saves session logs)
│                                 + search/read tools
│   ├── information.py            weather, web search, system info, time
│   ├── media.py                  music/Spotify/YouTube controls
│   ├── models.py                 ask_gpt56 (OpenAI), ask_groq (OpenAI-client→Groq),
│                                 ask_ollama (local) — OLDER, independent specialist tools
│   ├── specialist.py              ask_specialist — NEWER unified tool that wraps
│                                 nova_core.ModelRouter (route()/route_private())
│   ├── vision.py                  capture_screen + confirmed GPT-5.6 screen analysis
│   ├── obsidian.py                search_memory / read_memory_note / save_memory_note,
│                                 vault-sandboxed
│   ├── guardian.py                LiveKit tool wrappers around nova_guardian's runtime
│                                 (check_guardian_security, alerts, status, local vision
│                                 on/off) — safe_summary()-only, never returns screenshots
│   ├── permissions.py             list_pending_actions/approve_action/deny_action/
│                                 set_nova_safe_mode → nova_policy.permission_engine
│   └── email_calendar.py          list_connected_accounts, sync_email_calendar,
│                                 get_unread_emails, read_email (SENSITIVE, one-time
│                                 approval via nova_policy), calendar tools → wraps
│                                 nova_integrations.runtime.get_runtime()
│
├── Dashboard/                   Real NOVA desktop shell (aiohttp backend + static web UI
│                               + optional Tauri native wrapper)
│   ├── server.py                 aiohttp app, binds 127.0.0.1 only; GET / and static
│                                 assets from web/, GET /health, GET /ws (WebSocket hub);
│                                 12 background asyncio loops publish typed messages
│                                 (stats, spotify, weather, obsidian, usage, apps,
│                                 tools-log tail, audit tail, conversation tail, bridge
│                                 results, integration snapshot, integration events)
│   ├── feeds.py (778 lines)       Real data collectors: psutil, Spotify (cached OAuth +
│                                 window-title fallback), wttr.in weather, Obsidian vault
│                                 reads, Windows app registry scan, log tailing, approvals
│                                 tracker parsing audit_logs/nova_actions.jsonl
│   ├── integration_feeds.py       Read-only snapshot of nova_integrations accounts/mail/
│                                 calendar + tail of integration event log
│   ├── actions.py (255 lines)     Handles inbound WebSocket messages from the UI: app
│                                 launch/pin, recent-file open, folder open, and
│                                 delegate/approval commands written into nova_bridge
│                                 (BridgeValidationError on malformed input)
│   ├── app_registry.py            Builds/caches the real Start Menu + pinned + recent app
│                                 catalog; calls app_icons.icon_data_uri for icon caching
│   ├── app_icons.py               LIVE icon extraction/caching module (imported by
│                                 app_registry.py)
│   ├── appicons.py                UNUSED near-duplicate of app_icons.py — nothing in the
│                                 repo imports it (dead file, likely an earlier draft)
│   ├── security.py / safe_paths.py  Path/target sandboxing for recent-file opens and
│                                 shortcut resolution
│   ├── package.json               Node test/lint harness only (`node --test`,
│                                 `node --check` on each web/*.js file) — no bundler,
│                                 confirming web/ is hand-written static JS, not built
│   ├── start_dashboard.ps1        Launches `venv\Scripts\python.exe Dashboard\server.py`
│   ├── DESIGN_HANDOFF.md / LIVE-INTEGRATION.md / README.md   Design + wiring docs
│   ├── web/                       Static frontend served by server.py AND bundled by
│   │                              Tauri (frontendDist points here, see nova-app/)
│   │   ├── index.html               5-page design shell; also contains the ~150-line
│   │                                "NOVA live bridge" WebSocket client
│   │                                (`connectLive()`, `new WebSocket(...+'/ws')`,
│   │                                reads `window.NOVA_BACKEND` or falls back to
│   │                                `location.host`; with neither, stays in pure
│   │                                simulated-demo mode)
│   │   ├── support.js               Original design-handoff logic class (state machine,
│   │                                simulated data loops used as fallback)
│   │   ├── tauri-shell.js            Sets `window.NOVA_BACKEND = '127.0.0.1:8787'` when
│   │                                running inside the Tauri shell
│   │   ├── nova-integration.js, layout-engine.js, desktop-mode-state.js,
│   │   │   dashboard-enhancements.{js,css}   Additional UI layers/state
│   │   └── vendor/                   Vendored React/Babel UMD builds (no npm install
│   │                                needed to view the page)
│   ├── nova-app/                  Tauri v2 desktop wrapper ("NOVA.exe")
│   │   ├── package.json             `@tauri-apps/cli` + `@tauri-apps/api`, scripts:
│   │                                tauri/dev/build
│   │   └── src-tauri/
│   │       ├── tauri.conf.json       `build.frontendDist: "../../web"` — i.e. Tauri
│   │       │                        bundles the SAME Dashboard/web/ files server.py
│   │       │                        serves; no separate frontend build step. Window is
│   │       │                        undecorated/transparent (custom chrome), NSIS
│   │       │                        installer target, CSP disabled (`"csp": null`).
│   │       ├── src/lib.rs, src/main.rs   Minimal Tauri Rust shell
│   │       └── icons/, gen/, capabilities/default.json   Standard Tauri scaffolding
│   └── tests/                     Dashboard-local test suite (see §7)
│
├── config/nova_integrations.example.json   Template for nova_integrations config (real
│                               file, if any, would sit outside tracked repo)
├── scripts/start_integrations.ps1   Launches the integrations supervisor standalone
├── tests/                       Root-level pytest suite — ONLY covers
│                               nova_integrations (graph errors, privacy, storage, sync).
│                               Does not test agent.py, tools/, or nova_core/.
├── docs/
│   ├── FGCU_AND_OAUTH_SETUP.md, SECURITY_MODEL.md
│   └── audit/2026-07-22/        This audit's output directory (already contained
│                                GIT_STATE_BEFORE.md / SECURITY_REPORT.md from a parallel
│                                audit task before this file was added)
├── .agents/skills/run-ai-agent/  driver.py test harness + SKILL.md (tools/chat/
│                               console-check/dev-check commands, see DEVELOPMENT.md)
├── .agents/skills/                Mirrors run-ai-agent plus nova-code-review,
│                               nova-tool-pattern — appears to be a development assistant-side skills copy
├── course_materials/              Gitignored except .gitkeep; one sample PDF present
├── models/wakewords/              Local wake-word model assets for nova_wakeword.py
├── references/                    Gitignored clone-for-study repos (openai-python,
│                               python-agents-examples) — reference only, not shipped
├── audit_logs/                    Runtime output dir for nova_policy approvals
│                               (nova_actions.jsonl) — read by Dashboard/feeds.py
├── nova-file-inventory.txt        Untracked, gitignored inventory dump at repo root
├── .nova-patch-backup/             Gitignored dated snapshots (Dashboard patches)
├── .nova_integration_backup/       Gitignored dated snapshots (agent.py/tools/
│                               nova_integrations patches) — evidence of iterative
│                               in-place patch runs on 2026-07-21/22
└── AGENTS.md, README.md, ROADMAP.md, HACKATHON_LOG.md, HACKATHON_SUBMISSION.md,
    THIRD_PARTY_SERVICES.md, PROJECT_TASKS.md, START-HERE.md   Narrative/process docs
```

## 2. Entry points (verified against actual code, not docs)

| Surface | Real command | What actually runs |
|---|---|---|
| Voice agent (interactive) | `venv\Scripts\python.exe agent.py console` | `agent.py` — LiveKit `AgentServer`, one `@server.rtc_session` handler `my_agent`, `AgentSession` wired to `google.realtime.RealtimeModel` (Gemini `gemini-2.5-flash-native-audio-preview-12-2025`, voice "Puck"). Starts `dashboard_bridge_loop` as a background task per session. |
| Voice agent (LiveKit Cloud dispatch) | `venv\Scripts\python.exe agent.py dev` | Same `agent.py`, registers worker `my-agent`; needs explicit dispatch (e.g. LiveKit playground). |
| Standby/background supervisor | `venv\Scripts\python.exe nova_startup.py` (or `--check`) | **Not** the voice agent. Starts `nova_guardian.get_guardian_runtime()` and `nova_integrations.startup_hook.start_integrations_safely()`, writes `logs/nova_status.json` every 10s. Windows single-instance mutex guard. Independent process from `agent.py` — Guardian's continuous monitoring loop runs only if this script (or something that imports it) is running. |
| Dashboard backend | `venv\Scripts\python.exe Dashboard\server.py` or `Dashboard\start_dashboard.ps1` | aiohttp app on `127.0.0.1:8787`. Serves `Dashboard/web/` statically and a `/ws` WebSocket hub fed by 12 background loops. |
| Dashboard as native window | `Dashboard\nova-app` → `npm run tauri dev` / `npm run tauri build`, or the built `NOVA.exe` | Tauri v2 shell that loads `../../web` (same files `server.py` serves) inside a native undecorated window; **does not embed the Python backend** — still needs `Dashboard/server.py` running separately for live data, else falls back to the design's simulated demo loops. |
| Combined manual launch | `Start-NOVA.ps1` (`-DashboardOnly` / `-AgentOnly` switches) | Starts `agent.py console` if not already running (`Win32_Process` command-line match), then either the installed/`release` `NOVA.exe` or `npm run dev` inside `Dashboard\nova-app`. Does **not** start `nova_startup.py`'s standby supervisor or `Dashboard\server.py` itself — the PS1 assumes the Tauri exe path and doesn't launch the aiohttp backend, so a bare `Start-NOVA.ps1` run leaves the dashboard in demo mode unless `Dashboard/server.py` is started separately. |
| Local wake-word test | `venv\Scripts\python.exe nova_wakeword.py` | Standalone; never invoked by `agent.py`, `Start-NOVA.ps1`, or `nova_startup.py`. |
| Offline text chat | `venv\Scripts\python.exe offline_agent.py` | Standalone CLI to local Ollama only, via `tools.models.run_ollama`. Bypasses LiveKit and Gemini entirely. |
| Test harness | `.agents\skills\run-ai-agent\driver.py {tools|chat|console-check|dev-check}` | Documented and consistent with actual `agent.py`/`tools/` structure. |

All commands referenced in `DEVELOPMENT.md`/`AGENTS.md`/`Start-NOVA.ps1`/`START-HERE.md` point at files that exist on disk; verified above.

## 3. Frontend ↔ backend communication (Dashboard)

- Protocol: single WebSocket at `GET /ws` (aiohttp `WebSocketResponse`), plus plain `GET /health` (JSON) and static `GET /` + `GET /{path:.*}` asset serving.
- Origin check (`_origin_allowed`) restricts the WS handshake to same-host origins or the three `tauri://`/`http(s)://tauri.localhost` origins — rejects arbitrary external pages with `HTTPForbidden`.
- Server → client: a `Hub` class fans out JSON messages to all connected sockets and caches the latest per-`type` message plus a 40-item activity ring buffer; new clients get a `type: "snapshot"` replay on connect.
- Client → server: `websocket_handler` parses inbound JSON, calls `actions.handle(message, targets, approvals, bridge)` in a thread, and republishes whatever `actions.handle` returns (used for app-launch/pin actions and for delegate/approval commands, which land in `nova_bridge.command_store`).
- Frontend implementation lives in `Dashboard/web/index.html`'s `connectLive()` (not in `support.js`): reads `window.NOVA_BACKEND` (set to `127.0.0.1:8787` by `tauri-shell.js` when running under Tauri) or falls back to `location.host` when loaded over http(s); with neither, it silently stays in the original design's simulated-demo mode (`support.js`'s loops keep running). This is the "real vs simulated" switch described in `DEVELOPMENT.md`.

## 4. Model-routing flow — the key duplicate/gap

`agent.py` imports `ask_specialist` from `tools` (line 16 of `agent.py`) but **`ask_specialist` is never added to `Assistant`'s `tools=[...]` list** (lines 161–215). Grepping `agent.py` for `ask_gpt56|ask_groq|ask_ollama|ask_specialist` matches only the unused `ask_specialist` import. Net effect: **none of NOVA's specialist-model tools (old or new) are currently reachable by voice** — the LLM has no function-tool it can call to reach GPT-5.6, Groq, Ollama, or the unified router, even though every layer beneath that gap is fully implemented and wired to each other:

```
tools/specialist.py (ask_specialist, @function_tool)
        │  imports
        ▼
nova_core/__init__.py  →  nova_core/router.py (ModelRouter.route/route_private)
        │  imports                              │  imports
        ▼                                        ▼
nova_core/provider_registry.py            nova_core/cloud_budget.py, configuration.py
        │  builds registry from
        ▼
providers/__init__.py  →  providers/openai_provider.py, providers/ollama_provider.py
        (providers/groq_provider.py exists but is not imported by __init__.py or the
         registry — a second, unrelated gap: a written-but-unwired Groq adapter)
```

Meanwhile `tools/models.py` (`ask_gpt56`, `ask_groq`, `ask_ollama`) is the **older**, independent specialist implementation described as working in `DEVELOPMENT.md`'s "Non-obvious facts" — it talks to providers directly via the OpenAI client, with no `nova_core` involvement. It is exported from `tools/__init__.py` but, like `ask_specialist`, is not imported into `agent.py` at all. So there are effectively **two competing specialist-routing implementations** (`tools/models.py` direct-call vs. `nova_core`+`providers`+`tools/specialist.py` router), and **neither is currently attached to the live voice agent's tool list** — a functional regression/incomplete-migration, not just a stale-doc issue, since `DEVELOPMENT.md` describes the old tools as working and opt-in.

The truly dead code is separate: `core/` (root-level `task.py`/`router.py`/`orchestrator.py`) is imported by nothing anywhere in the repo (confirmed by repo-wide grep) — it predates `nova_core/` and both `DEVELOPMENT.md` and this audit treat it as legacy scaffolding, not part of any active flow.

## 5. Tool-registration flow (agent.py ← tools/)

```
tools/__init__.py   re-exports every function from tools/{desktop,files,information,
                     media,models,vision,obsidian,conversations,guardian,permissions,
                     email_calendar,specialist}.py
        │
        ▼
agent.py  `from tools import (...)`  — explicit name-by-name import list (line 15-70)
        │
        ▼
class Assistant(Agent): tools=[ ... ]  — a SEPARATE explicit list (lines 161-215) that
                     must be kept in sync with the import list by hand
```

Both lists must match for a tool to be callable; as shown in §4, they currently do not (`ask_specialist` is imported but not registered; `ask_gpt56`/`ask_groq`/`ask_ollama` are registered in neither list). Every other imported name in the current tree does appear in both lists (checked by diff of the two blocks).

## 6. Dashboard data flow (feeds.py → actions.py → web/index.html)

- `feeds.py` (778 lines) is pure data-collection: `stats_message` (psutil), `spotify_message` (cached OAuth Spotify Web API + window-title fallback + media keys), `weather_message` (wttr.in), `obsidian_message`/`tasks_message` (vault file reads, `<vault>/NOVA/Tasks.md`), `scan_apps` (Start Menu/Desktop/Recent via `app_registry.build_registry`), `FileTail`/`parse_log_line` (tails `nova_tools.log`), `ApprovalsTracker` (parses `audit_logs/nova_actions.jsonl`), `ConversationWatch` (tails `conversation_logs/`), `usage_message` (reads `cloud_usage.json`).
- `integration_feeds.py` layers a read-only snapshot of `nova_integrations` (connected accounts, unread mail counts, calendar) plus an event-log tail on top of the same Hub.
- `actions.py` (255 lines) is the only place with side effects: app launch/pin (`app_registry.perform_action`), recent-file/folder open (guarded by `security.can_open_recent_target`/`is_sensitive_path`), and writing delegate/approval commands into `nova_bridge.command_store` for the agent process to pick up.
- `server.py`'s 12 background loops (`BACKGROUND_LOOPS`) call into `feeds`/`integration_feeds`/`nova_bridge` on fixed intervals (2s stats, 4s Spotify, 30 min weather, 60s Obsidian, 30s usage, 10 min app rescan, 1s log tail, 1s audit tail, 2s conversation tail, 0.5s bridge results, 20s integrations, 1s integration events) and publish through the `Hub`, which fans out over `/ws` to `index.html`'s `connectLive()`.
- Everything above is real (live system/file/API data) when `Dashboard/server.py` is running; with no server reachable, `index.html` stays on `support.js`'s original simulated-demo loops (per `DEVELOPMENT.md`, calendar specifically is still called out there as "Demo Data" even in live mode — not verified further in this pass).

## 7. Authentication / secret flow (no secret values read)

- `.env` is the real secrets file at repo root; `.env.example` is the tracked template (both confirmed via `.gitignore`: `.env` and `.env.*` are ignored, `!.env.example` is the one exception).
- Loaders found (`load_dotenv` call sites, values never inspected):
  - `agent.py`: `load_dotenv(".env.local")` then `load_dotenv(".env")` (later call does not override already-set vars by default — `.env.local` wins if both define the same key).
  - `nova_startup.py`: `load_dotenv(ENV_PATH, override=True)` where `ENV_PATH = PROJECT_ROOT / ".env"` — only loads `.env`, not `.env.local`, and does override.
  - `offline_agent.py`: same two-call pattern as `agent.py`.
  - `Dashboard/server.py`: `load_dotenv(PROJECT_ROOT / ".env.local")` then `load_dotenv(PROJECT_ROOT / ".env")`.
- `.env.example` documents these variable groups (names only): LiveKit (`LIVEKIT_URL/API_KEY/API_SECRET`), Gemini (`GOOGLE_API_KEY`, `NOVA_REALTIME_MODEL`/`NOVA_VOICE`/`NOVA_TEMPERATURE` — present but, per `DEVELOPMENT.md`, ignored by `agent.py`, which hardcodes Ahmed's tuning), OpenAI specialist (`OPENAI_API_KEY`, `NOVA_ENABLE_OPENAI`, `NOVA_OPENAI_MODEL`), Groq (`GROQ_API_KEY`, `GROQ_MODEL`, `NOVA_ENABLE_GROQ`), Ollama (`NOVA_ENABLE_OLLAMA`, `NOVA_OLLAMA_MODEL`, `NOVA_OLLAMA_BASE_URL`), provider routing (`NOVA_PROFILE`, `NOVA_FALLBACK_ENABLED`), cloud budget (`NOVA_CLOUD_BUDGET_ENABLED`, `NOVA_CLOUD_DAILY_REQUEST_LIMIT`), Guardian (`NOVA_GUARDIAN_ENABLED`, `NOVA_SECURITY_MONITOR_ENABLED`, `NOVA_WINDOW_MONITOR_ENABLED`, `NOVA_GUARDIAN_AUTO_RESPONSE`, `NOVA_SECURITY_SCAN_INTERVAL_SECONDS`), ambient vision (`NOVA_VISION_MODE`, `NOVA_LOCAL_VISION_ONLY`, `NOVA_PAUSE_ON_SENSITIVE_WINDOWS`, `NOVA_LOCAL_VISION_MODEL`, several timeout/threshold/retention vars, `NOVA_VISION_EXCLUDED_PROCESSES`, `NOVA_SENSITIVE_WINDOW_KEYWORDS`), Spotify (`SPOTIFY_CLIENT_ID/SECRET/REDIRECT_URI`).
  - Per `DEVELOPMENT.md`'s known issues, the real `.env` additionally has a duplicate `OBSIDIAN_VAULT_PATH`/`OBSIDIAN_VAULT_NAME` pair — not independently re-verified here since it requires opening `.env`, which this audit avoided per instructions.
- `nova_integrations/secrets.py` exists as a dedicated module (uses `keyring`, per `requirements.txt`) for OAuth-token-style secrets separate from the `.env` static-key flow — consistent with Gmail/Outlook needing per-account OAuth rather than a single static key.

## 8. Startup/shutdown flow

- Voice agent: `agents.cli.run_app(server)` (LiveKit's own process lifecycle) → per-session `my_agent` job starts `dashboard_bridge_loop` as an `asyncio.Task` and registers `ctx.add_shutdown_callback(lambda: stop_dashboard_bridge(bridge_task))`, which cancels the task and awaits it — the bridge always deregisters its heartbeat (`store.clear_heartbeat`) in a `finally` block even on cancellation.
- Standby supervisor (`nova_startup.py`): Windows named-mutex single-instance guard (`Local\NOVAStandbySupervisor`) → starts `nova_guardian` runtime + `nova_integrations` supervisor → writes `logs/nova_status.json` every 10s → on any exit path (`CancelledError`, exception, or normal) always calls `stop_integrations_safely()` then `runtime.stop()` in a `finally` block, and releases the mutex handle in an outer `finally`.
- Dashboard backend: `aiohttp` `cleanup_ctx` (`start_background`) launches all 12 loops as tasks on startup and cancels them all on app shutdown (no explicit awaiting/join shown, standard aiohttp cleanup-context cancel pattern).
- `Start-NOVA.ps1` only *starts* processes (checks for an already-running agent via WMI command-line match, checks for a running `NOVA` process by name); it has no corresponding stop script.

## 9. Duplicate / competing architectures found

1. **`core/` vs `nova_core/`** — `core/router.py`/`task.py`/`orchestrator.py` predate `nova_core/`, are imported by nothing (verified by grep), and are dead code left in place. Low risk (inert), but noise for anyone reading the tree.
2. **Specialist-model routing: `tools/models.py` vs `nova_core`+`providers`+`tools/specialist.py`** — two independent implementations of "ask a specialist model" exist; per §4, **neither is currently reachable from the live voice agent** because `Assistant.tools=[...]` in `agent.py` omits `ask_specialist`, `ask_gpt56`, `ask_groq`, and `ask_ollama` alike, despite `ask_specialist` being imported. This is the most actionable finding — it's not stale documentation, it's a real functional gap in the code as it stands right now.
3. **`providers/groq_provider.py`** — written, but not exported from `providers/__init__.py` and not referenced by `nova_core/provider_registry.py` or anywhere else. Orphaned relative to the new router even though `tools/models.py`'s older `ask_groq` still works independently (per `DEVELOPMENT.md`).
4. **`Dashboard/app_icons.py` vs `Dashboard/appicons.py`** — `app_registry.py` imports `app_icons` (`icon_data_uri`, `save_cache`); `appicons.py` is unreferenced anywhere in the repo. Likely an earlier draft left behind.
5. **`requirements.txt` vs `requirements-email-calendar.txt`** — the latter's package list is now a strict subset already folded into the former (both list identical `google-auth`/`google-auth-oauthlib`/`google-api-python-client`/`msal`/`keyring`/`winotify`/`tzdata` pins); kept separately per its own header comment as an optional standalone installer, not a version mismatch.
5b. **Dashboard's Tauri wrapper is a thin shell, not a self-contained app** — `nova-app`'s `tauri.conf.json` points `frontendDist` at the *same* `Dashboard/web/` folder `server.py` serves, and ships no embedded Python process. Running the built `NOVA.exe` alone (as `Start-NOVA.ps1` does when it finds that exe) gives you the design shell with **no live data** unless `Dashboard/server.py` is separately running — `Start-NOVA.ps1` does not start it.
6. **Gitignored in-place backup snapshots** — `.nova-patch-backup/` and `.nova_integration_backup/` hold multiple dated (`20260721-...`, `20260722-...`) full/partial copies of `Dashboard/`, `agent.py`, `nova_startup.py`, `tools/`, `nova_integrations/`, etc. These are evidence of repeated in-place patch-and-restore cycles very recently, consistent with the current working tree being mid-integration (uncommitted) rather than a clean, reviewed drop.

## 10. Notes / things NOT independently re-verified in this pass

- Whether `nova_startup.py`'s Guardian runtime is ever started as part of the normal `Start-NOVA.ps1` flow — it is not; Guardian only runs if `nova_startup.py` (or something importing it) runs separately. Not flagged as a bug, just worth knowing when tracing "is Guardian actually watching right now."
- The exact contents of `nova_policy/engine.py`'s `PermissionEngine` (only its exports were inspected, not full internal logic) — out of scope for a structure inventory but relevant to a security-focused follow-up pass.
- `.env`'s actual contents (by design — not opened).
