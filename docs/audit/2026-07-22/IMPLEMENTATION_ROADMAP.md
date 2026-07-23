# Implementation Roadmap — 2026-07-22

Built from `ISSUES.md`, `FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md`,
`DASHBOARD_AND_INTEGRATIONS_AUDIT.md`, `FEATURE_REALITY_CHECK.md`, and
`CLEANUP_PLAN.md`. Every task cites the finding that justifies it.

Format: `Priority | Dependency | Files/Components | Risk | Verification | Suggested Commit`

## Stage 1 — Repository Stabilization

| Task | Priority | Dependency | Files/Components | Risk | Verification | Suggested Commit |
|---|---|---|---|---|---|---|
| Install missing email/calendar deps into venv (`tzdata`, `keyring`, `msal`, `google-auth-oauthlib`, `google-api-python-client`, `winotify`) | **P0** | None | `requirements-email-calendar.txt` | Low (additive install) | Re-run `tests/` + `Dashboard/tests/` suites; both should go 14/14 and 34/34 | "Install email/calendar runtime dependencies" |
| Wrap `capture_screen`/`analyze_screen_with_gpt56` in `permission_engine.run(...)` (NOVA-013) | **P0** | None | `tools/vision.py` | Low (mechanical, matches existing pattern) | Manual `driver.py chat` invocation; confirm approval entry appears in `audit_logs/nova_actions.jsonl` | "Gate screen-capture tools through the permission engine" |
| Decide and wire ONE specialist-model path into `agent.py`'s live tool list — either add `ask_specialist` to `Assistant.tools=[...]`, or import `ask_gpt56`/`ask_groq`/`ask_ollama` | **P0** (needs Ahmed's decision first) | Ahmed picks System A vs System B | `agent.py:15-70,161-215` | Low once decided | `driver.py tools` then `driver.py chat "ask gpt for..."` | "Wire specialist-model tool into live agent session" |
| Remove duplicate unconditional `tzdata` line (NOVA-010) | P2 | Bundle with dep install task | `requirements.txt:26` | Trivial | `pip install -r requirements.txt` clean | fold into dep-install commit |
| Fix `Dashboard/appicons.py` raw-string path bug OR delete the file (it's dead code per CLEANUP_PLAN.md) | P2 | None | `Dashboard/appicons.py` | Trivial | n/a if deleted; else `driver.py`/dashboard smoke test | "Remove dead Dashboard/appicons.py duplicate" |
| Defer `openai` SDK import to first-use in `providers/openai_provider.py`/`ollama_provider.py` (NOVA-002) | P1 | None | `providers/*.py` | Low | Re-time `import providers`; confirm sub-second | "Defer openai SDK import in providers" |
| Baseline tests: none needed to *add* — both suites already exist and mostly pass; just get them to 100% via the dep-install task above | P1 | Depends on dep install | `tests/`, `Dashboard/tests/` | n/a | Full suite run | n/a |

## Stage 2 — Dashboard Foundation

Per `DASHBOARD_AND_INTEGRATIONS_AUDIT.md` §1, the Tauri shell is already
substantially real (frameless/transparent window, tray, click-through,
always-on-top, autostart, single-instance, close-to-tray all confirmed
working). Remaining gaps:

| Task | Priority | Dependency | Files/Components | Risk | Verification | Suggested Commit |
|---|---|---|---|---|---|---|
| Add backend crash-detection + auto-restart for the Python child process | P1 | None | `Dashboard/nova-app/src-tauri/src/lib.rs` | Medium (process-management code) | Kill `server.py` manually, confirm Tauri respawns it within N seconds | "Add backend health-check and auto-restart" |
| Either wire `window-vibrancy` (`apply_blur`/`apply_acrylic`) or remove the unused Cargo dependency | P2 | None | `Cargo.toml`, `lib.rs` | Low | Visual check in a Tauri dev build | "Apply real window vibrancy or drop the dependency" |
| Set an explicit Tauri CSP instead of `"csp": null` (NOVA-011) | P2 | None | `tauri.conf.json` | Low-Medium (may need `unsafe-inline` for existing styles) | Tauri dev build, confirm no CSP console errors, dashboard still renders | "Set explicit Content-Security-Policy for Tauri webview" |
| Locate or build the custom title-bar min/max/close buttons the README describes (currently unconfirmed in `index.html`) | P3 | None | `Dashboard/web/index.html` | Low | Visual check | "Add/confirm custom title bar controls" |
| Persist widget layout to a small backend-side file (optional upgrade from localStorage-only) | P3 | None | `Dashboard/server.py`, `layout-engine.js` | Medium | Manual layout-change + restart test | "Persist dashboard layout server-side" |

## Stage 3 — Icon and App Wiring

Per the wiring matrix in `DASHBOARD_AND_INTEGRATIONS_AUDIT.md` §1.11, 10 of
13 traced elements already work end-to-end. This stage is smaller than
originally scoped:

| Task | Priority | Dependency | Files/Components | Risk | Verification | Suggested Commit |
|---|---|---|---|---|---|---|
| Add a Codex `KNOWN_PROCESSES`/dock entry — currently entirely unwired | P1 | None | `Dashboard/app_registry.py`, `Dashboard/web/index.html` | Low | Click the new tile, confirm Codex launches | "Add Codex to the app registry and dock" |
| Relabel or re-point the "Search" dock tile (currently opens NOVA's own command palette, not Windows Search) | P2 | Ahmed's call on intended behavior | `Dashboard/web/index.html` | Trivial | Visual check | "Clarify Search tile behavior" |
| Document (in `Dashboard/README.md`) that the offline/demo Start-menu grid's ~60 hardcoded names are cosmetic placeholders, not a real app catalog | P3 | None | `Dashboard/README.md` | None | Doc-only | "Document offline demo app list as cosmetic" |
| Update `Dashboard/README.md`'s stale "Calendar page is still design demo data" line — it's now wired (see §1.12) | P2 | None | `Dashboard/README.md` | None | Doc-only | "Correct stale calendar-integration doc note" |

The centralized app registry Ahmed asked for **already exists**
(`Dashboard/app_registry.py`) and is real — see `DASHBOARD_WIRING_PLAN.md`
for its actual schema (differs from the hypothetical schema in the audit
prompt) rather than proposing a new one.

## Stage 4 — Real Dashboard Data

Per `DASHBOARD_AND_INTEGRATIONS_AUDIT.md`, **this stage is essentially
already done** for every item Ahmed listed except email/calendar (blocked
on Stage 1's dependency install) and Guardian isn't in this list but is
relevant:

| Feed | Status | Task remaining |
|---|---|---|
| NOVA event stream (activity/tool log) | Working | None |
| System statistics (psutil) | Working | None |
| Spotify | Working | None |
| Obsidian notes | Working | None |
| Notifications (dashboard in-app) | Working | Clarify vs. real Windows toasts (see NOVA-004-adjacent finding in dashboard audit §2.7) |
| Weather | Working | None |
| Calendar | Working once synced | Blocked on Stage 1 dep install; **not** blocked on new code |
| Email | Working once synced | Same |
| Agent status | Working | None |
| Model-routing status | **Blocked on Stage 1's routing decision** — nothing to show if no specialist tool is reachable | Resolve Stage 1 P0 routing task first |

| Task | Priority | Dependency | Files/Components | Risk | Verification |
|---|---|---|---|---|---|
| Add `logging` to `Dashboard/feeds.py`'s three silent except blocks (NOVA-004) | P1 | None | `Dashboard/feeds.py` | Low | Break Spotify/weather deliberately, confirm log line appears |
| Add real Windows Action Center toasts for dashboard-originated events, if desired (currently only the broken email path uses `winotify`) | P3 | Stage 1 dep install | `Dashboard/actions.py` | Low | Manual notification trigger |

## Stage 5 — Email and Calendar

Per `DASHBOARD_AND_INTEGRATIONS_AUDIT.md` §2.3, this is **substantially
built already** — real OAuth (Google `InstalledAppFlow`, Microsoft MSAL
public-client, no secrets), real incremental sync (Gmail History API,
Graph delta query), real FGCU admin-consent handling, real keyring-backed
token storage, real prompt-injection defenses on untrusted email content,
and full wiring into both `agent.py`'s live tools and the dashboard UI.

| Task | Priority | Dependency | Files/Components | Risk | Verification |
|---|---|---|---|---|---|
| Install runtime deps (see Stage 1 P0) | **P0** | — | venv | Low | `get_runtime()` succeeds |
| Place a real `google_oauth_desktop_client.json` at `%LOCALAPPDATA%\NOVA\integrations\` (Ahmed's own Google Cloud OAuth client, out-of-band) | **P0**, Ahmed-only action | Stage 1 P0 | N/A (not in repo) | N/A (Ahmed's own credential) | `list_connected_accounts` shows a connectable Google option |
| Connect a first real account (Microsoft/FGCU or Google) and verify one real sync cycle end-to-end | P1 | Above two | `nova_integrations/cli.py accounts connect` | Low (read-only scopes) | Dashboard Calendar/Mail pages show real data instead of the demo badge |
| Wire `nova_startup.py`'s background supervisor into the actual launch path (currently only on-demand sync runs from `Start-NOVA.ps1`) | P2 | None | `Start-NOVA.ps1` or `nova-app/src-tauri/src/lib.rs` | Medium (new always-running behavior) | Confirm periodic sync happens without a manual "Sync Now" click |
| Fix the `local_timezone` → `ZoneInfo` fragility (NOVA-001's longer-term fix) so one bad timezone name degrades gracefully instead of killing the whole runtime | P2 | None | `nova_integrations/services.py:59` | Low | Unit test with a deliberately invalid timezone |

## Stage 6 — Voice Recognition

**Not started.** No speaker-verification/enrollment code was found anywhere
in this audit (not in `nova_guardian/`, not in `tools/`, not referenced by
`nova_wakeword.py`, which is a wake-word *detector*, not a speaker
*verifier* — a meaningfully different feature). This is genuinely new work.

| Task | Priority | Dependency | Notes |
|---|---|---|---|
| Scope enrollment UX (voice sample capture, storage format) | P3 | Ahmed's priority call | Needs a design decision before code |
| Choose a local speaker-embedding approach (fully offline, per CLAUDE.md's privacy posture) | P3 | Above | Large — new dependency, new model, new code |
| Define unknown-speaker behavior and confidence threshold | P3 | Above | Security-relevant — should mirror `nova_guardian`'s existing "fail closed, don't auto-punish" philosophy |

Estimated difficulty: **Large**. Recommend treating as its own dedicated
implementation pass, not squeezed into a broader session, given zero
existing scaffolding to build on.

## Stage 7 — Face Recognition

**Not started**, same situation as Stage 6 — `nova_guardian/ambient_vision.py`
does screen analysis, not face/person recognition; no face-embedding or
enrollment code exists anywhere in the repo.

| Task | Priority | Dependency | Notes |
|---|---|---|---|
| Explicit privacy/consent design (local encrypted embeddings, enrollment flow, camera indicator) | P3 | Ahmed's priority call | Should reuse `nova_guardian`'s existing privacy-first patterns (local-only processing, sensitive-window pausing, no persistence by default) as the template |
| Camera capture pipeline (net-new — `nova_guardian` currently only does *screen* capture via `PIL.ImageGrab`, never a webcam) | P3 | Above | Large — new OS integration surface |
| Lock-command / remote-alert integration | P3 | Above, plus Stage 6 | Depends on both recognition features existing first |

Estimated difficulty: **Large**. Same recommendation as Stage 6 — dedicated
pass, not incremental.

## Stage 8 — Testing and Release

| Task | Priority | Dependency | Files/Components | Risk | Verification |
|---|---|---|---|---|---|
| Fix NOVA-001 so both existing suites hit 100% (14/14, 34/34) | P0 | Stage 1 dep install | `tests/`, `Dashboard/tests/` | Low | Suite re-run |
| Add unit tests for `nova_policy/engine.py`'s gating (there currently appear to be none dedicated to the permission engine itself — only consumers are tested indirectly) | P2 | None | New `tests/test_permission_engine.py` | Low | New tests pass |
| Add a regression test asserting `agent.py`'s `Assistant.tools=[...]` list matches its import list (would have caught the `ask_specialist` gap automatically) | P1 | None | New test in `.claude/skills/run-ai-agent/` or `tests/` | Low | Test fails today (proving it would have caught NOVA-current gap), passes after Stage 1's routing fix |
| Fix the circular `nova_core`↔`providers` import (NOVA-005) before it causes a real break | P2 | None | `nova_core/configuration.py`, `providers/base.py` | Medium (refactor, needs care) | Re-run import validation in varied import orders |
| Offline/demo-mode vs. production-mode separation | Already exists | — | `Dashboard/web/index.html`'s `connectLive()` fallback to `support.js` | — | Already verified working per structure audit |

## Stage 9 — GitHub Presentation

| Task | Priority | Dependency | Notes |
|---|---|---|---|
| Clean README pass incorporating this audit's corrections (stale calendar-demo-data line, tool count 38→53+, etc.) | P1 | Audit complete (now) | `README.md`, `Dashboard/README.md` |
| Architecture diagram | P2 | None | Could be generated from `PROJECT_STRUCTURE.md`'s existing narrative |
| Feature-status table | P1 | Audit complete | `FEATURE_REALITY_CHECK.md`/`FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md` already contain the raw material |
| Security notes | P1 | Audit complete | `SECURITY_REPORT.md` + `docs/SECURITY_MODEL.md` (already exists) |
| Demo video / demo link | P3 | Ahmed's own capture | Outside code scope |
| Release ZIP | Done this pass | — | `NOVA-Safe-Source-20260722-202831.zip` — note this is an *audit* safe-copy, not necessarily the polished public release artifact |

## Stage 10 — Portfolio and GitHub Profile

Outside this audit's code scope entirely — no repo action needed. Noting
only that `HACKATHON_SUBMISSION.md`/`HACKATHON_LOG.md` already exist and,
per `FEATURE_REALITY_CHECK.md`, are largely honest about current
limitations (a genuine asset for a portfolio narrative — "built it, found
real gaps via a full audit, fixed them" is a stronger story than claiming
everything already worked).

---

## Priority-ordered punch list (top 8, cross-stage)

1. Install `requirements-email-calendar.txt` into `venv\` (unblocks Stages 4, 5, 8 simultaneously — single highest-leverage fix).
2. Decide + wire one specialist-model path into `agent.py` (Stage 1) — currently a real capability regression.
3. Gate `capture_screen`/`analyze_screen_with_gpt56` through `permission_engine` (Stage 1) — real, currently shippable privacy gap.
4. Place Ahmed's Google OAuth desktop client JSON + connect one real account (Stage 5).
5. Add logging to `Dashboard/feeds.py`'s silent excepts (Stage 4).
6. Delete `Dashboard/appicons.py` (Stage 1/3, trivial).
7. Add Codex to the app registry (Stage 3).
8. Defer `openai` import in `providers/*.py` for faster cold starts (Stage 1).
