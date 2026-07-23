# NOVA Feature Audit — AI Routing, Tools, Permissions

Read-only code audit. Repo root: `C:\Users\ahmed\OneDrive\Desktop\AI Agent`.
Method: traced actual imports and call sites (not comments/docs). `.env` was
never opened; only variable *names* referenced via existing code reads.

Status legend: Working / Partially working / Present but not wired / Mocked
or simulated / Broken / Missing / Dead or unused / Security risk / Needs
manual verification.

---

## Section 1 — AI and Model Routing

### 1.1 `agent.py` — Gemini Realtime wiring

- Claimed behavior: LiveKit `AgentSession` on Gemini Realtime, voice-first.
- Entry point: `agent.py:222` `@server.rtc_session` → `my_agent(ctx)`.
- Config actually set, `agent.py:224-248`:
  - `model="gemini-2.5-flash-native-audio-preview-12-2025"` (hardcoded, not
    read from `NOVA_REALTIME_MODEL`)
  - `voice="Puck"`, `temperature=0.5` (hardcoded, not read from
    `NOVA_VOICE`/`NOVA_TEMPERATURE`)
  - `thinking_config`: `thinking_budget=0`, `include_thoughts=False`
  - `realtime_input_config.activity_handling =
    START_OF_ACTIVITY_INTERRUPTS`; automatic activity detection enabled,
    high start/end sensitivity, `prefix_padding_ms=200`,
    `silence_duration_ms=350` — real barge-in/VAD config, not a stub.
  - Turn handling (`agent.py:76-93`, `CONVERSATION_MODE_TURN_HANDLING`):
    `turn_detection="realtime_llm"`, interruption enabled
    (`min_duration=0.35`), `preemptive_generation` enabled
    (`preemptive_tts=False`, `max_speech_duration=8.0`). This *is* real
    session-level barge-in/interruption config, passed into
    `AgentSession(turn_handling=..., aec_warmup_duration=0.8, llm=...)` at
    `agent.py:224-226`.
  - `room_io.RoomOptions(video_input=False, audio_input=... ai_coustics
    noise cancellation ...)` at `agent.py:256-263` — matches CLAUDE.md's
    "video_input OFF" claim.
- Streaming/tool-calling: tool list is passed via `Assistant.__init__`
  `tools=[...]` (`agent.py:161-215`) to the `Agent` base class, which
  LiveKit wires into the Gemini Realtime tool-calling loop. This part is
  real and functional (LiveKit's own mechanism, not app code).
- Required env: `GOOGLE_API_KEY` (implicit, via `google.realtime.RealtimeModel`).
- Error handling: none explicit around session/model construction; relies on
  LiveKit's own retry/error surfacing.
- Registered/reachable: yes, this is the live session.
- Status: **Working** (per CLAUDE.md's own verification history; not
  re-verified live in this audit — no code path issue found).
- Evidence: `agent.py:76-93`, `agent.py:157-217`, `agent.py:222-276`.
- Recommended fix: none required. Note only: `NOVA_REALTIME_MODEL`,
  `NOVA_VOICE`, `NOVA_TEMPERATURE` exist in `.env.example` but are dead
  (unread) — CLAUDE.md already documents this as intentional (Ahmed's
  tuning). No action needed unless Ahmed asks to wire them up.
- Difficulty: N/A (informational).

### 1.2 THREE parallel model-routing systems — none of the new ones reach the live agent

This is the most important Section-1 finding. There are now three
independent systems for routing a text prompt to a specialist LLM, and the
live agent (`agent.py`) uses **none** of them:

**System A — `tools/models.py` direct functions (`ask_gpt56`, `ask_groq`,
`ask_ollama`)**
- Claimed behavior (CLAUDE.md): three opt-in specialist tools, each a thin
  wrapper around an `AsyncOpenAI`-compatible client (OpenAI Responses API,
  Groq via OpenAI-compatible endpoint, local Ollama via OpenAI-compatible
  endpoint).
- Backend: `tools/models.py:368-465` (`ask_groq`, `ask_ollama`, `ask_gpt56`
  `@function_tool()` wrappers around `run_groq`/`run_ollama`/`run_gpt56`,
  `tools/models.py:158-299`).
- Exported: `tools/__init__.py:2,108-110` (`ask_gpt56, ask_groq, ask_ollama`
  in `__all__`).
- **Registered in agent.py: NO.** `agent.py`'s `from tools import (...)`
  block (`agent.py:15-70`) does not import `ask_gpt56`, `ask_groq`, or
  `ask_ollama` at all, and `Assistant.tools=[...]` (`agent.py:161-215`)
  does not reference them either.
- Reachable: **no** — dead export, never imported by the running app.
- Error handling: good (per-exception messages, no crashes) — but moot
  since unreachable.
- Status: **Present but not wired** (regression from a prior working state
  — CLAUDE.md's "Non-obvious facts" section still describes these as live
  opt-in tools, which is now stale).
- Evidence: `agent.py:15-70` (import list), `agent.py:161-215` (tool list),
  `tools/models.py:368-465`.

**System B — `nova_core` + `providers/` router, exposed as `ask_specialist`**
- Claimed behavior: unified specialist router (`tools/specialist.py`) that
  picks a provider (OpenAI or Ollama) per role (`reasoning`/`coding`/
  `private`) via `nova_core.ModelRouter`, with cloud-budget gating
  (`nova_core/cloud_budget.py`) and provider fallback.
- Backend: `tools/specialist.py:153-174` (`ask_specialist`
  `@function_tool()`) → `route_specialist_request` →
  `nova_core.router.ModelRouter.route`/`route_private`
  (`nova_core/router.py:161-375`).
- **Imported into agent.py: YES** (`agent.py:16`, `ask_specialist,`).
- **Registered in the tools list passed to the LLM: NO.**
  `Assistant.tools=[...]` (`agent.py:161-215`) omits `ask_specialist` even
  though it is imported. This is the *only* name imported at the top of
  `agent.py` that never appears in the `tools=[...]` list — a dead import.
- Reachable: **no** — imported but never given to the LLM session, so the
  model can never call it.
- Provider registry gap: `nova_core/provider_registry.py:260-284`
  (`create_provider_registry`) registers **only** `OpenAIProvider` and
  `OllamaProvider`. It never registers a Groq provider, even though
  `nova_core/configuration.py:560-584` defines a full `ProviderName.GROQ`
  configuration block and `nova_core/configuration.py:23-29` lists `GROQ`
  as a valid provider. `providers/groq_provider.py` **is an empty file**
  (0 bytes) and `providers/__init__.py:3-13` never imports or exports a
  `GroqProvider` class. If a caller ever requested `role="groq"` or a
  profile that defaulted to Groq, `ModelRouter.route` would treat it as
  `not_registered` (`nova_core/router.py:199-209`) and fall through to
  Ollama — silent degradation, not a crash, but the Groq path is
  effectively vestigial/unimplemented in this system.
- Error handling: good (typed exceptions, graceful fallback text).
- Status: **Present but not wired** for the tool itself (unreachable from
  the live agent); the Groq provider inside it is **Missing**
  (`providers/groq_provider.py` is empty).
- Evidence: `agent.py:16` vs `agent.py:161-215`; `providers/groq_provider.py`
  (empty); `providers/__init__.py:3-13`;
  `nova_core/provider_registry.py:260-284`.
- Recommended fix: add `ask_specialist` to `Assistant.tools=[...]` in
  `agent.py` (one line) if this new router is meant to replace System A: it
  is a straightforward CLAUDE.md-required "smallest safe change" — but
  Ahmed should be asked which of System A or System B he wants live, since
  right now the net effect is **zero specialist-model capability reachable
  from voice**, a real capability regression versus what CLAUDE.md
  describes as working. Also either implement `providers/groq_provider.py`
  or drop `ProviderName.GROQ` from `nova_core/configuration.py` to avoid a
  provider that is configured but never actually registered.
- Difficulty: Small (wiring `ask_specialist` in) / Medium (implementing
  `GroqProvider` properly, mirroring `OpenAIProvider`).

**System C — `core/` (task.py, router.py, orchestrator.py) — old scaffolding**
- Verified per CLAUDE.md's existing claim ("not imported anywhere yet"):
  still true. `grep -rn "import core\b" --include=*.py .` and
  `grep -rln "from core"` (excluding `__pycache__`) return **no matches**
  anywhere outside `core/` itself.
- `core/orchestrator.py:4` still imports `tools.models.run_groq,
  run_ollama` directly (System A's internals), so even if wired up later it
  would bypass both `nova_core` and `tools/specialist.py` — a third,
  independently-coupled routing path.
- Status: **Dead or unused** (confirmed unchanged from CLAUDE.md's prior
  finding).
- Evidence: `core/orchestrator.py:1-111`, `core/router.py:1-47`,
  `core/task.py:1-42`; empty grep results for any importer.
- Recommended fix: either delete `core/` (superseded by `nova_core/` +
  `providers/`) or explicitly document it as an intentionally-parked
  alternative design. Leaving three unreconciled routing systems in the
  tree is a maintenance hazard.
- Difficulty: Small (delete) / ask Ahmed first per CLAUDE.md's own rule
  ("don't delete; wire it up or ask Ahmed").

### Section 1 summary table

| Component | Imported by agent.py | In LLM tool list | Reachable | Status |
|---|---|---|---|---|
| Gemini Realtime session | n/a (native) | n/a | yes | Working |
| `ask_gpt56`/`ask_groq`/`ask_ollama` (tools/models.py) | No | No | **No** | Present but not wired |
| `ask_specialist` (nova_core router) | Yes | **No** | **No** | Present but not wired |
| Groq provider inside nova_core | — | — | — | Missing (empty file) |
| `core/` orchestrator (old) | No | No | No | Dead or unused |

---

## Section 2 — Agent Tools

### 2.1 Actual tool count vs. claimed "38 tools"

`Assistant.tools=[...]` in `agent.py:161-215` lists **53** function tools
actually registered with the live LiveKit session (counted directly from
the list). CLAUDE.md's `tools/` docstring still says "38 function tools" —
that count predates the `email_calendar.py`, `guardian.py`, `permissions.py`
modules and is stale. Additionally, 4 more tool functions exist in the
codebase but are **not** reachable (`ask_gpt56`, `ask_groq`, `ask_ollama`,
`ask_specialist` — see Section 1.2), so the tools/ directory defines 57
`@function_tool()`s total, 53 of which are live.

### 2.2 Per-module registration table

| Module | Tools exported (`tools/__init__.py`) | In `agent.py` tools list | Notes |
|---|---|---|---|
| `vision.py` | `capture_screen`, `analyze_screen_with_gpt56` | Both yes | See 3.x — no permission-engine gate despite a registered policy |
| `models.py` | `ask_gpt56`, `ask_groq`, `ask_ollama` | **None** | Dead export, see 1.2 |
| `obsidian.py` | `read_memory_note`, `save_memory_note`, `search_memory` | All yes | Sandboxed to `<vault>/NOVA/`; blocks secret-like content (`tools/obsidian.py:152-154,209-210`) |
| `conversations.py` | `read_conversation_history`, `search_conversation_history` | Both yes | Sandboxed to `conversation_logs/` |
| `specialist.py` | `ask_specialist` | **No** (imported, not registered) | See 1.2 |
| `email_calendar.py` | 8 tools (list/sync/unread/read/agenda/next/conflicts/briefing) | All yes | Real OAuth connectors (Google/Microsoft), read-only scopes; `read_email` body-fetch gated by `permission_engine` |
| `permissions.py` | `approve_action`, `deny_action`, `list_pending_actions`, `set_nova_safe_mode` | All yes | Thin wrappers over `nova_policy.permission_engine` |
| `desktop.py` | `close_app`, `control_window`, `is_app_running`, `manage_virtual_desktop`, `open_app`, `open_notifications`, `open_quick_settings`, `open_website`, `restart_app` | All yes | `close_app`/`restart_app` correctly gated; app/close lists are whitelists, not free text |
| `files.py` | `create_desktop_file`, `create_desktop_folder`, `create_file`, `find_user_file`, `list_files`, `open_file_or_folder`, `read_course_material`, `read_file`, `read_notes`, `save_note` | All yes | All path resolution goes through `resolve_safe_path`/`resolve_course_material_path` (`tools/common.py:75-127`); `create_file`/`create_desktop_file`/`create_desktop_folder` refuse to overwrite (no delete/move/overwrite tool exists at all) |
| `information.py` | `get_system_info`, `get_time`, `get_weather`, `search_web` | All yes | Read-only, no risk |
| `media.py` | `change_volume`, `control_music`, `get_current_song`, `play_spotify_song`, `play_youtube_song` | All yes | Graceful "not configured" message when `SPOTIFY_CLIENT_ID/SECRET` missing (`tools/media.py:81-85,111-115`) — no crash |
| `guardian.py` | `check_guardian_security`, `get_guardian_alerts`, `get_guardian_status`, `look_at_screen_locally`, `start_guardian_vision`, `stop_guardian_vision` | All yes | See Section 3.3 — no permission-engine gate on any of these |

### 2.3 Input validation / hardcoded paths / missing-env behavior (spot findings)

- `tools/desktop.py`: `open_app`/`close_app`/`restart_app` use hardcoded
  whitelists (`APP_WHITELIST`, `CLOSE_APP_PROCESS_MAP`,
  `tools/desktop.py:16-71`) — good input validation, rejects anything not
  on the list with a clear message rather than shelling out arbitrary text.
- `tools/common.py:37-42`: `DEFAULT_DESKTOP_PATH` and `SAFE_DIRS` are built
  from `Path.home()`, not hardcoded to Ahmed's literal username — portable,
  not a hardcoded-path issue. `PROJECT_ROOT` is derived from `__file__`.
  No literal `C:\Users\ahmed\...` strings found in `tools/` (only in
  `models.py`/`obsidian.py`/`media.py` match was `os.getenv`, not hardcoded
  paths — the earlier grep for `C:\\Users` had zero hits in those files).
- `tools/models.py` / OpenAI/Groq/Ollama clients: all three gracefully
  return `None`/raise a caught `ModelUnavailableError` when their API key
  env var is missing or is a known placeholder value
  (`_configured_env_value`, `tools/models.py:42-56`) — no crash on missing
  config, by design.
- `tools/obsidian.py:30-46` (`get_obsidian_vault_path`): raises
  `ObsidianConfigurationError` if `OBSIDIAN_VAULT_PATH` is unset or does not
  exist, and every caller (`search_memory`, `read_memory_note`,
  `save_memory_note`) catches this and returns a spoken error string rather
  than crashing the tool call.
- `tools/email_calendar.py`: depends on `nova_integrations` config/OAuth
  state (`nova_integrations/config.py`, `secrets.py` — keyring-backed).
  Backend is real (installed-app OAuth flow against Google/Microsoft Graph,
  read-only scopes: `gmail.readonly`/`gmail.metadata`,
  `calendar.events.readonly`; see
  `nova_integrations/connectors/google_workspace.py:1-99`). If no accounts
  are connected, tools return "No ... accounts are connected" rather than
  failing — real data, not simulated, but requires the user to have run
  the connector's OAuth flow out-of-band (not exercised in this audit).

---

## Section 3 — Permission and Safety System

### 3.1 The permission engine itself

- `nova_policy/engine.py:58-436` (`PermissionEngine`) is a real, working
  confirmation/audit system: 4-tier `PermissionLevel`
  (`READ_ONLY`/`REVERSIBLE`/`SENSITIVE`/`RESTRICTED`), per-action
  `ActionPolicy` registration, pending-action expiry (default 45-60s),
  once/session approval scopes, a `safe_mode` kill switch that blocks
  everything above `READ_ONLY`, and append-only JSONL audit logging to
  `audit_logs/nova_actions.jsonl` with secret-term redaction
  (`_safe_summary`, `nova_policy/engine.py:537-569`).
- Default policies registered at import time
  (`nova_policy/engine.py:617-690`): `close_app`, `restart_app`,
  `capture_screen`, `analyze_screen_with_gpt56` (SENSITIVE);
  `send_to_recycle_bin`, `send_email` (SENSITIVE, but **no tool implements
  either action** — these are forward-declared policies with nothing
  wired to them, harmless but currently vestigial); `permanent_delete`,
  `arbitrary_shell_command`, `install_software`, `disable_security`
  (RESTRICTED, always denied — also no tool currently exercises these).
- Status: **Working**, well designed, real gating logic when actually
  invoked (see 3.2 for who invokes it and who doesn't).
- Evidence: `nova_policy/engine.py:58-696`.

### 3.2 Sensitive-action gating — actual call sites (real gate vs. bypass)

| Sensitive action | Tool | Calls `permission_engine.run(...)`? | Verdict |
|---|---|---|---|
| Close application | `close_app` (`tools/desktop.py:551-567`) | **Yes** (`action_name="close_app"`) | Real gate |
| Restart application | `restart_app` (`tools/desktop.py:570-603`) | **Yes** (`action_name="restart_app"`) | Real gate |
| Full email body fetch (cloud) | `read_email` (`tools/email_calendar.py:103-161`) | **Yes** (`action_name="read_email_body_cloud"`, registered right there at `tools/email_calendar.py:17-28`) | Real gate |
| Screen capture (all screens, saved to disk) | `capture_screen` (`tools/vision.py:22-53`) | **No.** A policy named `"capture_screen"` exists in `nova_policy/engine.py:636-645` with a real confirmation message, but the tool never calls `permission_engine.run()` — it grabs and saves the screenshot immediately on every invocation. | **Bypass — policy is registered but dead** |
| Screen capture + send to OpenAI | `analyze_screen_with_gpt56` (`tools/vision.py:56-107`) | **No** engine call. There is a *manual* boolean parameter `user_confirmed_screen_share: bool = False` (`tools/vision.py:60`) that the tool checks before proceeding — but this flag is entirely LLM-supplied, not validated against any user-facing confirmation UI, not audited, not expiring, and not tied to `nova_policy` at all. A policy named `"analyze_screen_with_gpt56"` also exists in `nova_policy/engine.py:646-655` and is likewise never referenced from `tools/vision.py`. | **Bypass — the real permission engine is never consulted; only a self-reported LLM flag gates this** |
| Start ambient/local vision monitoring | `start_guardian_vision` (`tools/guardian.py:173-235`) | **No.** No `ActionPolicy` exists for this action name at all, and the tool calls `runtime.start_vision()` directly. Mitigated somewhat by: local-only Ollama processing (never leaves the machine when `local_vision_only=True`, default True), auto-expiry (max 30 min), sensitive-window pausing, and password-manager process exclusion (see 3.3) — but there is still no code-enforced confirmation step, only the tool's docstring instructing the model to ask first. | **No gate at all (undocumented in nova_policy); relies purely on prompt-level trust** |
| One-shot local screen look | `look_at_screen_locally` (`tools/guardian.py:116-170`) | No | Same as above; lower risk since local-only and non-persistent, but still no code gate |
| Defensive security scan | `check_guardian_security` (`tools/guardian.py:273-304`) | No | Read-only (process/firewall/Defender status only); appropriately ungated |
| File/desktop creation | `create_file`, `create_desktop_file`, `create_desktop_folder` (`tools/files.py`) | No | Appropriately ungated — these tools structurally refuse to overwrite (`tools/files.py:521-525,575-576,600-601`), so they are non-destructive by construction; no `ActionPolicy` needed |
| File/note deletion or move | — | n/a | **No such tool exists anywhere in `tools/`.** `permanent_delete` and `send_to_recycle_bin` policies exist in `nova_policy` for a feature that was never built. Not a current risk, just unfinished plumbing. |
| Send email | — | n/a | **No such tool exists.** `email_calendar.py` is read-only end to end (list/sync/read/agenda only). The `"send_email"` policy is dead. |
| System settings changes | — | n/a | No tool changes system/security settings; `open_quick_settings`/`open_notifications` only send `Win+A`/`Win+N` keystrokes to open Windows' own panels, they don't change settings themselves |

**Single most concerning finding:** `capture_screen` and
`analyze_screen_with_gpt56` are the two actions the developer explicitly
registered `SENSITIVE`-level `ActionPolicy` objects for in
`nova_policy/engine.py` (with real confirmation copy, ready to use), but
the actual tool implementations in `tools/vision.py` never call
`permission_engine.run()`. `capture_screen` fires immediately, every
single time it's called, with zero confirmation — it silently
grabs and permanently saves a full-desktop screenshot (all connected
monitors) to `screenshots/` on disk on every call. `analyze_screen_with_gpt56`
additionally uploads that screenshot to OpenAI, gated only by a
model-controlled boolean the LLM itself decides how to set — which is not
a security boundary (a sufficiently adversarial prompt, e.g. text visible
on-screen or injected into the conversation, could influence the model to
set `user_confirmed_screen_share=True` without genuine user consent, since
there is no independent confirmation channel). This is a real, currently
shippable **Security risk**, and it's an easy fix: both tools should call
`permission_engine.run(action_name="capture_screen"/"analyze_screen_with_gpt56", ...)`
around their capture logic exactly the way `close_app`/`restart_app`/
`read_email` already do correctly.

### 3.3 `nova_guardian/` — ambient/window/security monitoring (privacy-sensitive area)

What it actually does (verified by reading every file, not the module
docstrings):

- **Not a camera.** There is no webcam/microphone capture anywhere in
  `nova_guardian/`. `ambient_vision.py` captures the **foreground window's
  screen region** (or full screen if window bounds can't be read) via
  `PIL.ImageGrab`, in memory only.
- **Local-only by default and by design**: images are sent only to a local
  Ollama server (`ambient_vision.py:482-570`, POST to
  `{ollama_base_url}/api/chat`); never to a cloud provider from this
  module. `analyze_once` refuses to run at all unless
  `configuration.local_vision_only` is True (default True,
  `nova_guardian/config.py:342-345`) — i.e. it is architecturally
  incapable of sending frames to OpenAI/Gemini/Groq; only
  `analyze_screen_with_gpt56` (a separate, explicit tool in `vision.py`)
  does cloud vision.
- **Disabled by default**: `GuardianConfiguration.enabled` defaults to
  `False` (`nova_guardian/config.py:326-329`, env var
  `NOVA_GUARDIAN_ENABLED`) and `vision_mode` defaults to `VisionMode.OFF`
  (`config.py:338-341`). Whether it is *currently* enabled on Ahmed's
  machine depends on `.env`/`.env.local` values this audit did not read —
  flagged as **Needs manual verification**.
- **Not auto-started by `agent.py`.** Nothing in `agent.py` calls
  `GuardianRuntime.start()`, `start_vision()`, or imports
  `nova_guardian` directly. The only entry points are the six
  `tools/guardian.py` function tools, all of which are voice/LLM-triggered
  (i.e., background monitoring only begins if the model calls
  `check_guardian_security`, `look_at_screen_locally`, or
  `start_guardian_vision` during a live conversation — `GuardianRuntime.start()`
  is invoked lazily inside those tool calls, e.g.
  `guardian.py:141,203,287` → `runtime.start()`/`scan_security_once()`
  internally call `self.state.start()`).
- **Self-protective defaults**: excludes password-manager processes by
  name (`1password`, `bitwarden`, `keepass`, etc.,
  `config.py:288-298`) and pauses on sensitive window titles
  (password/login/payment/banking/OTP/API-key keywords,
  `config.py:300-319`, `pause_on_sensitive_windows` default True). Screens
  are not stored to disk by default (`store_screenshots` default False,
  `config.py:360-363`); frames only ever exist as in-memory `PIL.Image`
  objects, discarded after each analysis.
- Session auto-expiry: `start_guardian_vision` caps duration at 30 minutes
  and self-stops (`nova_guardian/runtime.py:222-298`).
- Gap versus 3.2: as noted, starting a vision session has no
  `permission_engine` confirmation gate — the safeguards above are
  configuration/architecture-level (good), not consent-flow-level (missing).
- `security_monitor.py`/`window_monitor.py` were read at a high level via
  `runtime.py`'s orchestration; they run local process/firewall/Defender
  checks and window-title tracking respectively — no evidence of any
  network exfiltration path; all output goes through `_safe_value` /
  `safe_summary()` sanitizers before being returned to the LLM
  (`tools/guardian.py:15-93`).
- Status: **Present, correctly defaulted to off, architecturally
  privacy-conscious** — but flagged per instructions as a privacy-sensitive
  area regardless: it is real, working code capable of periodic screen
  analysis once enabled, with no confirmation-engine gate on
  session start, and its exact current on/off state depends on `.env`
  values not inspected here. **Needs manual verification** of the current
  `NOVA_GUARDIAN_ENABLED`/`NOVA_VISION_MODE` values, and recommend adding
  it to `nova_policy` policies for defense in depth even though the
  existing safeguards are reasonable.
- Evidence: `nova_guardian/config.py:322-386`, `nova_guardian/runtime.py:1-487`,
  `nova_guardian/ambient_vision.py:1-936`, `tools/guardian.py:1-365`.
- Recommended fix: register `start_guardian_vision` (and arguably
  `look_at_screen_locally`) as `ActionPolicy` entries in
  `nova_policy/engine.py` and route them through `permission_engine.run()`,
  matching the pattern already used for `close_app`/`restart_app`/
  `read_email`. Small, mechanical change.
- Difficulty: Small.

### 3.4 Dashboard bridge — does it bypass permissions?

`nova_agent_bridge.py:17-44` (`dispatch_dashboard_command`) was checked
because it's a second entry point into the live agent process (from
`Dashboard/`'s local command inbox). Findings:
- `"delegate"` commands are injected as a normal user turn via
  `session.generate_reply(user_input=text, ...)` — this re-enters the
  standard LLM+tool-calling path, so any tool call it triggers is still
  subject to whatever gating that tool has (including the gaps above).
- `"approve"`/`"deny"` dashboard actions call `permissions.approve(...)`/
  `permissions.deny(...)` directly on the same shared `permission_engine`
  singleton used by voice — no separate, weaker approval path.
- Status: **Working**, no bypass identified.
- Evidence: `nova_agent_bridge.py:17-44`.

---

## Summary

- **Tool count**: 53 tools are actually registered with the live LiveKit
  session (`agent.py:161-215`), versus the "38 tools" figure in CLAUDE.md's
  layout description — that figure is stale (predates
  `email_calendar.py`/`guardian.py`/`permissions.py`). A further 4 tool
  functions exist in code but are unreachable (`ask_gpt56`, `ask_groq`,
  `ask_ollama`, `ask_specialist`), meaning NOVA currently has **zero**
  reachable specialist/reasoning-model tool despite three separate routing
  systems existing in the repo (`tools/models.py` direct calls,
  `nova_core`+`providers/` router via `ask_specialist`, and the older
  unused `core/` scaffolding).
- **Single most concerning permission/safety gap**: `capture_screen` and
  `analyze_screen_with_gpt56` (`tools/vision.py`) have real, ready-to-use
  `SENSITIVE`-level confirmation policies already registered in
  `nova_policy/engine.py`, but the tool implementations never call
  `permission_engine.run()`. `capture_screen` executes immediately with no
  confirmation of any kind on every call; `analyze_screen_with_gpt56`
  uploads a screenshot to OpenAI gated only by a boolean parameter the LLM
  itself supplies, with no independent user-confirmation channel, audit
  trail, or expiry. This is inconsistent with the correctly-gated pattern
  already used elsewhere in the same codebase for `close_app`, `restart_app`,
  and `read_email`'s full-body fetch — and is a straightforward fix
  (wrap both tool bodies in `permission_engine.run(...)`, same as the
  working examples).
