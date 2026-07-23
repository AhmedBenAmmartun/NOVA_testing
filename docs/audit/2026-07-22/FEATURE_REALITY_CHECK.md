# NOVA Feature Reality Check — Fake/Mock/Placeholder Sweep

Date: 2026-07-22
Method: read-only grep sweep for TODO/FIXME/mock/fake/dummy/simulate/hardcoded/
placeholder/`except: pass`/always-true guards etc., followed by manual reading
of the matched files to judge real problem vs. benign. Excluded: `.git`,
`node_modules`, `venv`/`.venv`, `__pycache__`, `.pytest_cache`,
`Dashboard/nova-app/src-tauri/target`, `Dashboard/web/vendor` (React/Babel
vendor bundles), `screenshots/`, `logs/`, `conversation_logs/`, `gen/schemas/`.

**Overall finding: this codebase is unusually honest.** Most areas checked
(Dashboard feeds/actions, `nova_integrations` Gmail/Outlook connectors,
`nova_guardian` vision/security monitors, `tools/*.py`, `nova_policy`
permission engine, `nova_bridge`/`nova_agent_bridge`) are real, working
implementations with genuine OS/API calls, not stubs. Where live data isn't
available the UI explicitly shows a "Demo Data" badge rather than silently
faking it. The issues below are the real gaps, not a wall of noise.

## Dashboard

| Feature | Claimed Status | Actual Status | Evidence (file:line) | Fake/Mock Indicator | Required Work |
|---|---|---|---|---|---|
| Calendar page | "Calendar" 5th page shows live agenda/month view | **Real backend exists and works**, but shows literal hardcoded demo events (`Demo prep · 4 PM`, `CS exam · 10 AM`) and a "Demo calendar" label whenever no Gmail/Outlook account is connected — which is the current state (no accounts configured yet) | `Dashboard/web/index.html:1213-1214,1243,1427-1428` (demo arrays + `'Demo calendar'` fallback label); backing implementation is real: `Dashboard/integration_feeds.py:184-265`, `nova_integrations/connectors/google_workspace.py` | `demo`/hardcoded sample events | None required — this is an honestly-labeled fallback, already tracked as a known issue in CLAUDE.md ("Calendar is still Demo Data"). Only remaining work is Ahmed completing OAuth setup; no code fix needed. Listed here for completeness, not as a bug. |
| Global dashboard demo mode | Dashboard shows real data | When `Dashboard/server.py` isn't running, the whole shell (stats, spotify, tasks, apps, everything) falls back to simulated numbers | `Dashboard/web/index.html:42-44` (`isDemo`/`isLive` badges), `Dashboard/web/nova-integration.js:16-18,41-47` | `demo` mode by design | None — this is intentional, clearly labeled ("Demo Data" badge / "LIVE" badge), not deceptive. Not a finding, noted for completeness. |
| `Dashboard/appicons.py` | Implies it's the icon-resolution module (name mirrors `app_icons.py`) | Dead file — never imported anywhere in the repo. Only `Dashboard/app_icons.py` (with underscore) is actually used by `app_registry.py` | `Dashboard/app_registry.py:20` imports `app_icons`, not `appicons`; confirmed no importer of `appicons` repo-wide | orphaned/duplicate module | Low priority: delete `Dashboard/appicons.py` (168 lines) or clarify why both exist — currently just dead weight that could confuse a future editor into changing the wrong file. |
| Dashboard/nova-app (Tauri shell) `project_root()` | Locates the NOVA install to spawn the Python backend | Falls back to a hardcoded personal path if the `NOVA_PROJECT_ROOT` env var is unset and the exe's own directory isn't the project root | `Dashboard/nova-app/src-tauri/src/lib.rs:69` — `let fallback = PathBuf::from(r"C:\Users\ahmed\OneDrive\Desktop\AI Agent");` | hardcoded absolute Windows path with username | Low priority given this is a single-user personal app (by design, per README). If the project ever moves or is shared, this silently-wrong fallback should be removed in favor of failing loudly, or read from a persisted config file written by the installer. |

## Tools (LiveKit function tools)

No fake/mock implementations found. Spot-checked `tools/media.py` (Spotify Web
API + media-key control), `tools/vision.py` (real `ImageGrab` capture +
GPT-5.6 call, gated on explicit consent), `tools/information.py` (real
`wttr.in`/DuckDuckGo/psutil calls), `tools/desktop.py` (`open_app`/
`is_app_running`/`close_app` all use real `psutil.process_iter` and a
subprocess whitelist), `tools/email_calendar.py`, `tools/specialist.py`, and
`tools/guardian.py` — all call into real backends with honest error strings
on failure (no tool returns a fabricated "success" when the underlying call
failed).

| Feature | Claimed Status | Actual Status | Evidence | Indicator | Required Work |
|---|---|---|---|---|---|
| `core/` package (`task.py`, `router.py`, `orchestrator.py`) | Present in the repo as "model routing scaffolding" | Confirmed dead code — grepped the entire repo for any `import core` / `from core.` and found zero references. Already flagged in CLAUDE.md's Known Issues | `core/router.py`, `core/orchestrator.py`, `core/task.py` — no importers anywhere | orphaned scaffolding | Already documented as a known issue (not a new finding). Either wire it up or delete it — currently it's ~pure dead weight that could mislead a reader into thinking model routing goes through it (the real router is `nova_core/router.py`, used by `tools/specialist.py`). |
| `CLAUDE.md` "38 function tools" claim | Doc says tools/ ships 38 function tools | `tools/__init__.py` actually exports 46 (`__all__` has 46 entries as of this sweep, including `tools/guardian.py` and `tools/email_calendar.py` which post-date the "38" count and aren't mentioned in CLAUDE.md's `tools/` module list at all) | `tools/__init__.py:76-134` | stale documentation, not fake code | Cosmetic — update the tool count and module list in CLAUDE.md's Layout section next time it's touched (per CLAUDE.md's own "update AGENTS.md/CLAUDE.md if... tool count... changed" rule). |

## AI / Agent core

No fake/mock implementations found. `tools/models.py` (`ask_gpt56`/`ask_groq`/
`ask_ollama`), `nova_core/router.py` + `providers/*.py` (used by
`ask_specialist`), and `nova_policy/engine.py` (permission engine: approve/
deny/expiry/audit, safe-mode gating) all do real work with real API/HTTP
calls and honest failure paths. No tool unconditionally returns success
regardless of input, and no `except: pass` block found in this area swallows
a user-facing error silently (the handful of bare `except: pass` blocks
repo-wide — `nova_bridge.py` file cleanup, `Dashboard/app_icons.py` cache
load, COM uninit in `Dashboard/safe_paths.py` — are all genuinely optional
best-effort cleanup, not error suppression that fakes a success state).

## Email/Calendar integration

| Feature | Claimed Status | Actual Status | Evidence | Indicator | Required Work |
|---|---|---|---|---|---|
| Gmail/Outlook read-only sync (`nova_integrations`) | Real OAuth-based Gmail/Outlook mail + calendar sync with local SQLite storage, notifications, and LiveKit tools (`list_connected_accounts`, `get_unread_emails`, `read_email`, `get_calendar_agenda`, etc.) | **Genuinely implemented**, not a stub: real `google-auth-oauthlib`/`googleapiclient` calls, real incremental Gmail history sync, real Google Calendar sync-token pagination, real Microsoft Graph connector, real Windows toast notifications, sensitive-content redaction, and a `read_email_body_cloud` explicit-approval gate before body content is sent to the cloud model | `nova_integrations/connectors/google_workspace.py` (492 lines, full OAuth + Gmail history API + Calendar sync-token logic), `nova_integrations/connectors/microsoft_graph.py`, `tools/email_calendar.py` | none — listed for completeness since this is exactly the kind of feature that's often faked | No code fix needed. The only real-world gap is that no Google/Microsoft account has been connected yet (OAuth not run), so `list_connected_accounts` truthfully reports zero accounts and the dashboard Calendar page shows its labeled demo fallback (see Dashboard section above). This matches CLAUDE.md's own note. |

## Guardian / vision

| Feature | Claimed Status | Actual Status | Evidence | Indicator | Required Work |
|---|---|---|---|---|---|
| `nova_guardian` ambient vision (`look_at_screen_locally`, `start_guardian_vision`) | Local-only screen understanding via Ollama, never uploads to cloud | Real implementation: captures the actual foreground window via `ImageGrab`, resizes, computes a change-detection threshold before re-analyzing, posts to a real local Ollama `/api/chat` endpoint, and returns honest `analyzed: false` results with specific reasons (`ollama_unavailable`, `ollama_timeout`, `capture_failed`, `vision_paused`, etc.) instead of ever fabricating an analysis | `nova_guardian/ambient_vision.py:220-266` (real `requests.get` health check against Ollama `/api/tags`), `:324-360` (real `ImageGrab.grab`), `:482-570` (real Ollama chat call) | none | No fix needed. Feature requires the user to actually run Ollama with a vision model (`gemma3:4b` by default) locally — if Ollama isn't running, the tool correctly reports `ollama_unavailable` rather than pretending to have looked at the screen. |
| `nova_guardian` security monitor (`check_guardian_security`) | Defensive local scan: processes, listening ports, Defender status, Firewall status | Real implementation: uses `psutil` for process/listener enumeration and real `powershell.exe Get-MpComputerStatus` / `Get-NetFirewallProfile` calls for Defender/Firewall status, not hardcoded "protected" values | `nova_guardian/security_monitor.py:510-620` | none | No fix needed. |
| `capture_screen` / `analyze_screen_with_gpt56` | Screenshot capture with confirmed GPT-5.6 analysis | Real: saves an actual `ImageGrab.grab(all_screens=True)` PNG and requires `user_confirmed_screen_share=True` before ever calling the OpenAI vision endpoint | `tools/vision.py:22-107` | none | No fix needed. |

## Summary of actionable items (ranked)

1. **Cosmetic/low-risk** — `Dashboard/appicons.py` is dead/duplicate code; either delete it or document why it coexists with `Dashboard/app_icons.py`.
2. **Cosmetic/low-risk** — `Dashboard/nova-app/src-tauri/src/lib.rs:69` has Ahmed's personal path hardcoded as a silent fallback; acceptable for a single-user app today, but should fail loudly instead of guessing if the project ever moves.
3. **Doc staleness, not a code bug** — CLAUDE.md's "38 function tools" count and `tools/` module list are out of date (46 tools now registered, `guardian.py`/`email_calendar.py`/`permissions.py`/`specialist.py` missing from the doc's module list). `core/` (task/router/orchestrator scaffolding) remains dead/unimported, as CLAUDE.md's own Known Issues section already states.
4. **Not a bug, confirmed working-as-labeled** — The dashboard Calendar page's demo events are the one place with literal hardcoded sample data, but it is clearly badged "Demo calendar" / the shell shows a "Demo Data" pill whenever the local bridge or an OAuth account isn't connected. This is the single feature area a user might currently believe is "live" when it's actually the placeholder — but the UI itself already discloses this, and both CLAUDE.md and HACKATHON_SUBMISSION.md call it out honestly.
