# NOVA Code-Quality Audit — 2026-07-22

Read-only audit of `C:\Users\ahmed\OneDrive\Desktop\AI Agent` (NOVA, Python 3.14
LiveKit voice agent + `Dashboard/` Node/Tauri desktop shell). All commands
below were actually executed in this environment (venv Python 3.14.6, Node
v24.18.0, npm 11.16.0); no packages were installed, no source files were
modified, no destructive commands were run, and no secret values are printed
anywhere in this report.

## Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 3 |
| Medium | 4 |
| Low | 4 |
| Informational | 4 |
| **Total** | **15** |

> **NOVA-013 added post-hoc**: the parallel AI-routing/permissions audit
> (`FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md`) surfaced a permission-engine
> bypass that belongs in this severity-ranked issue list; folded in below
> to keep one authoritative issue tracker rather than splitting security
> findings across two documents.

Headline result: all 71 files under `tools/`, `nova_core/`, `nova_guardian/`,
`nova_integrations/`, `nova_policy/`, `providers/`, `core/`, `Dashboard/*.py`
compile cleanly (`py_compile`, exit 0) and all five new top-level packages
(`nova_core`, `nova_guardian`, `nova_integrations`, `nova_policy`,
`providers`) **import without error**. The two High findings are a missing
runtime dependency that silently disables the whole email/calendar
integration feature, and a very slow (10-50s) cold import chain triggered by
`providers`/`nova_core` that is not a code defect per se but is a real
startup-latency risk worth fixing regardless of its (likely OneDrive/AV)
root cause.

---

## Section 1 — Python syntax/compile check

Command:
```
& ".\venv\Scripts\python.exe" -m py_compile agent.py prompts.py nova_bridge.py nova_agent_bridge.py nova_startup.py nova_wakeword.py offline_agent.py
& ".\venv\Scripts\python.exe" -m py_compile <all 71 files under tools/, nova_core/, nova_guardian/, nova_integrations/, nova_policy/, providers/, core/, Dashboard/*.py>
```
Result: **exit 0, zero output, zero syntax errors** in both passes (78 files
total). No findings in this section.

## Section 2 — Import validation

Command (one subprocess per package, generous per-package timeout):
```python
import time, importlib
for pkg in ['nova_core', 'nova_guardian', 'nova_integrations', 'nova_policy', 'providers']:
    t0 = time.time()
    importlib.import_module(pkg)
    print(f'{pkg}: OK {time.time()-t0:.2f}s')
```
Actual output:
```
nova_core: OK 37.04s
nova_guardian: OK 2.38s
nova_integrations: OK 0.27s
nova_policy: OK 0.06s
providers: OK 0.00s
```
All five packages import **without any exception, no ImportError, no
circular-import failure**. See Issue NOVA-002 (High) for the 37-second
`nova_core` cold-import time, and Issue NOVA-005 (Medium) for the circular
import pattern that makes this import graph fragile even though it currently
resolves successfully.

## Section 3 — Lint/type/test config and test runs

- No `pyproject.toml`, `ruff.toml`, `.flake8`, `mypy.ini`, or
  `pyrightconfig.json` exists anywhere in the repo root — confirmed absent,
  nothing was installed or run for these.
- `pytest` is **not** in `requirements.txt` and **not** installed in
  `venv\` (`pip show pytest` → `WARNING: Package(s) not found: pytest`). Per
  instructions, it was not installed. Both `tests/` and `Dashboard/tests/`
  are written against the stdlib `unittest` module (confirmed by reading
  `tests/test_email_calendar_privacy.py` and
  `Dashboard/tests/run-python-tests.mjs`, which itself shells out to
  `python -m unittest discover`), so they were run that way instead:
  - `venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`
    → **13/14 passed, 1 error** (Issue NOVA-001).
  - `venv\Scripts\python.exe -m unittest discover -s Dashboard/tests -p "test_*.py" -v`
    → **33/34 passed, 1 failure** (same root cause as NOVA-001).
- `Dashboard/package.json` scripts, all run successfully:
  - `npm run lint` → exit 0 (eight `node --check` calls over `web/*.js` and
    `scripts/verify-build.mjs`/`tests/run-python-tests.mjs`, all pass).
  - `npm run build` → exit 0, prints `Static dashboard build verified:
    offline assets, five clipped canvases, secure apps, Desktop Mode, and
    live email/calendar wiring are present.` — confirms the "verified
    2026-07-20" build claim in `DEVELOPMENT.md` still holds today.
  - `npm test` (via `node --test tests/*.test.js`) → **16/16 passed**
    (Dashboard JS suite: desktop-mode-state, email-calendar-wiring,
    layout-engine).
- `Dashboard/nova-app/package.json` has a `"build": "tauri build"` script;
  this was **not run** (requires the Rust toolchain — out of scope for a
  read-only audit and not something to install per instructions). Config
  files were inspected instead (Section 5).
- `.agents\skills\run-ai-agent\driver.py tools` (per `DEVELOPMENT.md`'s mandated
  post-change check) → **33/33 checks OK**, matching the count `DEVELOPMENT.md`
  already records for 2026-07-20. `chat`/`console-check` were **not** run
  (they call live Gemini/speak aloud, explicitly excluded by the task).

---

## Issues

### NOVA-001 — Missing `tzdata` dependency breaks the entire email/calendar integration runtime
- **Severity:** High
- **File:line:** `requirements.txt:25-26`, `nova_integrations/services.py:59`,
  `nova_integrations/runtime.py:61`, `nova_integrations/config.py:57`
- **Description:** `requirements.txt` lists `tzdata` twice (once
  Windows-conditional on line 25, once unconditionally on line 26), but the
  package is **not actually installed** in `venv\` (`pip show tzdata` →
  `WARNING: Package(s) not found: tzdata`). Windows' `zoneinfo` module has no
  built-in IANA database and requires the `tzdata` PyPI package to resolve
  any timezone name. `IntegrationConfig.local_timezone` defaults to
  `"America/New_York"` (`nova_integrations/config.py:57`), and
  `build_runtime()` (`nova_integrations/runtime.py:61`) unconditionally
  constructs `CalendarService(database, accounts, config.local_timezone)`,
  which calls `ZoneInfo(local_timezone)` at `nova_integrations/services.py:59`
  with no try/except around it. Because `CalendarService` is one field of
  the single `IntegrationRuntime` dataclass built by `build_runtime()`, this
  exception fails construction of the **entire** integration runtime object
  (mail, calendar, briefing, sync, supervisor together), not just calendar.
- **User impact:** On this machine, as currently provisioned, the whole
  email/calendar feature (a major, recently-added capability per git status
  — `tools/email_calendar.py`, the `NOVA-Email-Calendar-Integration-for-
  development assistant.zip`, etc.) is non-functional. It degrades gracefully everywhere it
  is called from production code (`nova_integrations/startup_hook.py:18-20`,
  `Dashboard/actions.py:146-169`, `Dashboard/integration_feeds.py` all wrap
  `get_runtime()`/the sync call in `except Exception:`), so NOVA does not
  crash — but the user sees "Synchronization failed" / a calendar
  `status: "error"` payload with no actual mail sync, calendar events, or
  briefings, and no obvious pointer to "install tzdata" in the error text.
- **Technical cause:** dependency declared in `requirements.txt` but the
  provisioned `venv\` is out of sync with it (drifted after `pip install
  -r requirements.txt` was last run, or `tzdata` was never actually
  installed even though the file lists it).
- **Evidence:**
  ```
  $ venv\Scripts\python.exe -c "import tzdata"
  ModuleNotFoundError: No module named 'tzdata'
  $ venv\Scripts\python.exe -m pip show tzdata
  WARNING: Package(s) not found: tzdata

  $ venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
  ERROR: test_calendar_sort_conflicts_all_day_and_cancelled (test_email_calendar_storage.StorageIsolationTests...)
  ...
  File "...\nova_integrations\services.py", line 59, in __init__
      self.timezone = ZoneInfo(local_timezone)
  zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key America/New_York'
  Ran 14 tests in 4.151s
  FAILED (errors=1)

  $ venv\Scripts\python.exe -m unittest discover -s Dashboard/tests -p "test_*.py" -v
  FAIL: test_calendar_payload_builds_month_and_upcoming (test_integration_feeds...)
  AssertionError: 'error' != 'connected'
   : Calendar payload: {'type': 'calendar', 'available': True, 'status': 'error', ...,
     'error': "'No time zone found with key America/New_York'"}
  Ran 34 tests in 6.238s
  FAILED (failures=1)
  ```
- **Proposed fix:** Run `venv\Scripts\python.exe -m pip install -r
  requirements.txt` to bring the venv back in sync (or specifically `pip
  install tzdata`), then remove the redundant unconditional `tzdata` line
  (`requirements.txt:26`) and keep only the platform-conditional one (line
  25) to avoid the duplicate-line confusion. Longer term, consider wrapping
  the `ZoneInfo(local_timezone)` call in `CalendarService.__init__` with a
  fallback (e.g. to `timezone.utc`) plus a logged warning, so a single bad
  or missing timezone name degrades one service instead of failing to build
  the whole `IntegrationRuntime`.
- **Verification steps:** After installing `tzdata`, re-run both suites:
  `venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`
  and `... -s Dashboard/tests ...` and confirm 14/14 and 34/34 pass with no
  `ZoneInfoNotFoundError`.

---

### NOVA-002 — `providers`/`nova_core` cold import takes 10-50 seconds via the `openai` SDK
- **Severity:** High
- **File:line:** `providers/openai_provider.py:6-13`,
  `providers/ollama_provider.py:5-9`, `tools/models.py:6-13`
- **Description:** `providers/openai_provider.py` and
  `providers/ollama_provider.py` both `from openai import (...)` at module
  top level (not deferred into a function). `providers/__init__.py`
  unconditionally imports both, and `nova_core/router.py:9` /
  `nova_core/provider_registry.py:8` import `from providers import (...)`,
  so importing `nova_core` — or `providers` on its own, or `tools` (which
  imports `tools.models`, which also imports `openai` at
  `tools/models.py:6`) — always pays the cost of importing the `openai`
  Python SDK and its transitive dependency tree (`httpx`, `httpx-sse`,
  `pydantic` 2.13.4 / `pydantic_core` 2.46.4, `pydantic-settings`, etc.).
  On this machine that import alone measured between roughly 9 and 50
  seconds across repeated runs in the same session (not a one-time
  compile-cache effect — it was re-measured cold and warm with
  inconsistent but consistently slow results).
- **User impact:** Anything that imports `nova_core`, `providers`, or the
  `tools` package pays this multi-second-to-tens-of-seconds tax on process
  start. `agent.py`'s tool registration already imports `tools` (which
  imports `tools.models`), so this latency is likely already present in
  today's agent startup independent of the new packages, but `nova_core`'s
  own import (used nowhere yet per `DEVELOPMENT.md`'s note that `core/` model
  routing scaffolding "is written but not imported anywhere") would add a
  *second*, separate ~30-50s hit the moment anything starts importing it,
  and repeated smoke-test/import-validation runs in this session
  demonstrated the delay is not a one-off fluke.
- **Technical cause:** Most likely environmental rather than a NOVA code
  defect — the whole repo (including `venv\`) lives inside
  `C:\Users\ahmed\OneDrive\Desktop\AI Agent`, a OneDrive-synced folder,
  where on-demand file materialization and/or Windows Defender real-time
  scanning of the large `httpx`/`pydantic_core` (compiled) dependency tree
  is a well-known source of multi-second-to-multi-minute first-touch import
  latency on Windows. Regardless of root cause, importing `openai` at
  module scope in a file that is imported unconditionally (rather than
  lazily inside the function that actually needs it) turns an
  environmental slowdown into a startup-blocking one for every caller of
  `providers`/`nova_core`/`tools`, even callers that never use OpenAI or
  Ollama.
- **Evidence:**
  ```
  $ venv\Scripts\python.exe -u -c "import time; t=time.time(); import providers; print(...)""
  (timed out after 20s under `timeout 20 ...`, confirmed not a shell-wrapper artifact
   by re-testing with -u unbuffered output showing 'start' printed before the hang)

  $ venv\Scripts\python.exe -u -c "import time; t=time.time(); import openai; print('openai import', time.time()-t)"
  openai import 30.460467100143433
  $ venv\Scripts\python.exe -u -c "... same again ..."
  openai import run2 9.434501647949219

  $ venv\Scripts\python.exe -u -c "import time; t=time.time(); import nova_core; print(...)"
  nova_core imported 49.9823043346405
  (repeat run) nova_core imported 41.49302864074707

  Final clean pass, all 5 packages in one process:
  nova_core: OK 37.04s
  nova_guardian: OK 2.38s
  nova_integrations: OK 0.27s
  nova_policy: OK 0.06s
  providers: OK 0.00s   (already imported transitively by nova_core above)
  ```
- **Proposed fix:** Move `from openai import (...)` inside
  `OpenAIProvider._get_client()`/`OllamaProvider._get_client()` (lazy
  import on first actual use) instead of at module top level in
  `providers/openai_provider.py` and `providers/ollama_provider.py`, so
  importing `providers`/`nova_core` for type/config purposes does not force
  the SDK import. Separately (outside this audit's scope to fix, but worth
  flagging to Ahmed): confirm whether the venv or repo should be moved out
  of the OneDrive-synced path, or added to Windows Defender's exclusion
  list, since this affects every cold Python process in the project, not
  just these packages.
- **Verification steps:** After deferring the import, re-run
  `venv\Scripts\python.exe -u -c "import time; t=time.time(); import
  providers; print(time.time()-t)"` and confirm the timing drops to
  sub-second; confirm `OpenAIProvider`/`OllamaProvider` still work when
  actually invoked (their own `_get_client()` still imports and functions
  correctly).

---

### NOVA-003 — Blocking `time.sleep()` calls run directly on the LiveKit agent's event loop
- **Severity:** Medium
- **File:line:** `tools/desktop.py:126,134` (`_press_combo`),
  `tools/desktop.py:287` (`_focus_window`); called from `async def`
  tool functions at `tools/desktop.py:652,673,682` (`control_window`),
  `tools/desktop.py:715` (`open_notifications`),
  `tools/desktop.py:745` (`open_quick_settings`),
  `tools/desktop.py:840` (`manage_virtual_desktop`)
- **Description:** `_press_combo()` calls `time.sleep(0.02)` twice per key
  (once per key-down, once per key-up); `_focus_window()` calls
  `time.sleep(0.12)`. Both are plain synchronous `def` functions called
  **directly** (no `await asyncio.sleep()`, no `asyncio.to_thread()`, no
  executor) from `async def` LiveKit `@function_tool()` functions such as
  `control_window`, `open_notifications`, `open_quick_settings`, and
  `manage_virtual_desktop`.
- **User impact:** Each call to these tools blocks the single asyncio event
  loop that LiveKit's real-time voice session runs on for roughly 0.04s to
  0.2s+ (more for multi-key combos, e.g. virtual-desktop switching sends
  multiple keys through `_press_combo`). In a latency-sensitive
  speech-to-speech agent this is small per call but is a real,
  measurable stall on the same loop that is also feeding/receiving audio
  frames — worth fixing before it compounds with other tools.
- **Technical cause:** Synchronous blocking calls inside async tool
  functions without offloading to a thread/executor.
- **Evidence:**
  ```
  tools/desktop.py:124-134
      for key in keys:
          _press_key(key)
          time.sleep(0.02)
      for key in reversed(keys):
          _press_key(key, key_up=True)
          time.sleep(0.02)

  tools/desktop.py:715-716 (inside `async def open_notifications`)
      _press_combo(
          ...

  tools/desktop.py:283-287
      user32.SetForegroundWindow(hwnd)
      time.sleep(0.12)
  ```
  Contrast with the correct pattern already used elsewhere in the same
  codebase, `nova_guardian/ambient_vision.py:703-708`, which wraps its own
  blocking call in `asyncio.to_thread`:
  ```python
  text = await asyncio.to_thread(
      self._call_local_vision_model,
      image=resized_frame,
      question=cleaned_question,
  )
  ```
- **Proposed fix:** Wrap the calls to `_press_combo`/`_focus_window` (and
  the whole `_focus_window`+`_press_combo` sequence in `control_window`'s
  snap-window branch) in `await asyncio.to_thread(...)`, matching the
  pattern already established in `nova_guardian/ambient_vision.py`. The
  `time.sleep()` calls themselves can stay unchanged since they run on the
  worker thread once offloaded.
- **Verification steps:** After the change, run
  `.agents\skills\run-ai-agent\driver.py tools` and confirm the
  `control_window`, `open_notifications`, `open_quick_settings`, and
  `manage_virtual_desktop` checks (currently passing at 33/33) still pass;
  ideally add a timing assertion or manual test that these no longer block
  a concurrently-running asyncio task.

---

### NOVA-004 — `Dashboard/feeds.py` silently swallows Spotify/weather errors with no logging
- **Severity:** Medium
- **File:line:** `Dashboard/feeds.py:179-181, 208-209, 249-250`
- **Description:** `Dashboard/feeds.py` has **no `import logging`
  anywhere in the file** (confirmed by reading its full import block,
  `feeds.py:10-25`). Three `except Exception:` blocks swallow all errors
  with no logging at all: Spotify OAuth client construction
  (`_spotify_api_client`, lines 179-181, sets a failure flag but never logs
  *why* it failed), the Spotify now-playing fetch (`spotify_message`, lines
  208-209, bare `pass`), and the wttr.in weather fetch (`weather_message`,
  lines 249-250, returns `None` with no record of the actual exception).
- **User impact:** When Spotify or weather data silently stops showing on
  the dashboard, there is currently no way to tell from `nova_tools.log` or
  any other log file *why* — was it a bad token, a network timeout, a
  malformed response, rate limiting? The user (or a future debugger) has no
  breadcrumb to follow.
- **Technical cause:** Missing logging in exception handlers; likely an
  oversight rather than a deliberate design choice (contrast with
  `tools/*.py`, which consistently pair `except Exception:` with
  `logger.exception(...)` before returning a friendly message — see the 30+
  matches for that pattern across `tools/desktop.py`, `tools/media.py`,
  `tools/files.py`, etc. during this audit's grep).
- **Evidence:**
  ```
  Dashboard/feeds.py:10-25 (full import block, no `import logging`)
  ...
  Dashboard/feeds.py:179-181
      except Exception:
          _spotify_client_failed = True
          _spotify_client = None
  Dashboard/feeds.py:208-209
          except Exception:
              pass
  Dashboard/feeds.py:249-250
      except Exception:
          return None
  ```
- **Proposed fix:** Add `import logging` and a module logger
  (`logger = logging.getLogger("nova.dashboard.feeds")`), then replace the
  three bare/silent `except Exception:` blocks with
  `logger.exception("...")` (or at minimum `logger.warning("...: %s", exc)`
  for the expected-to-happen-often weather timeout case) before returning
  the existing fallback values, mirroring the pattern already used
  throughout `tools/`.
- **Verification steps:** After the change, temporarily break
  `SPOTIFY_CLIENT_ID` or disconnect network access, confirm a log line
  appears (in whatever log sink `Dashboard/server.py` configures) instead
  of silent failure, then re-run `npm test` in `Dashboard/` to confirm the
  existing 16 JS tests and the mirrored Python suite still pass.

---

### NOVA-005 — Circular import between `nova_core` and `providers`
- **Severity:** Medium
- **File:line:** `nova_core/router.py:9`, `nova_core/provider_registry.py:8`
  (both `from providers import (...)`) vs.
  `providers/openai_provider.py:16`, `providers/ollama_provider.py:12`
  (both `from nova_core.configuration import ProviderConfiguration`)
- **Description:** `nova_core` imports from `providers`, and `providers`
  imports from `nova_core.configuration`. This currently resolves without
  error only because `providers` submodules import the narrower
  `nova_core.configuration` submodule (not the full `nova_core` package)
  and Python's import system happens to have `nova_core.configuration`
  fully initialized by the time `providers` needs it, given the specific
  order `nova_core/__init__.py` lists its own sub-imports
  (`.configuration` first, then `.provider_registry`/`.router`, which are
  the ones that reach into `providers`). This was verified working (import
  validation passed with no `ImportError`/`AttributeError`), but it is
  fragile: reordering the imports in `nova_core/__init__.py`, or having
  something import `providers` *before* `nova_core.configuration` has
  finished initializing, would raise `ImportError`/`AttributeError` on a
  partially-initialized module.
- **User impact:** No current user-visible impact (it works today), but
  this is a latent trap for the next change to either package's import
  order.
- **Technical cause:** Layering violation — `providers` (meant to be a
  low-level adapter layer) depends back on `nova_core` (meant to be the
  higher-level configuration/routing layer) for a single dataclass type
  (`ProviderConfiguration`).
- **Evidence:**
  ```
  $ grep -n "from providers import" nova_core/router.py nova_core/provider_registry.py
  nova_core/router.py:9:from providers import (
  nova_core/provider_registry.py:8:from providers import (

  $ grep -n "from nova_core" providers/openai_provider.py providers/ollama_provider.py
  providers/openai_provider.py:16:from nova_core.configuration import ProviderConfiguration
  providers/ollama_provider.py:12:from nova_core.configuration import ProviderConfiguration
  ```
- **Proposed fix:** Move `ProviderConfiguration` (and the small
  `ProviderName` enum it depends on) into `providers/base.py` (or a new
  shared `providers/config.py`) so `providers` has zero dependency on
  `nova_core`, and have `nova_core.configuration` import/re-export it
  instead. This makes the dependency strictly one-directional
  (`nova_core` → `providers`, never the reverse).
- **Verification steps:** After refactoring, re-run the import-validation
  pass (`importlib.import_module` on all five packages individually and in
  different orders) and confirm no `ImportError`; run
  `.agents\skills\run-ai-agent\driver.py tools` to confirm nothing that
  depends on these packages broke.

---

### NOVA-013 — `capture_screen` and `analyze_screen_with_gpt56` bypass the permission engine
- **Severity:** High (Security risk)
- **File:line:** `tools/vision.py:22-53` (`capture_screen`), `tools/vision.py:56-107`
  (`analyze_screen_with_gpt56`); policies registered but unused at
  `nova_policy/engine.py:636-655`
- **Description:** `nova_policy/engine.py` already registers real,
  ready-to-use `SENSITIVE`-level `ActionPolicy` entries named
  `"capture_screen"` and `"analyze_screen_with_gpt56"`, with real
  confirmation copy — but neither tool implementation ever calls
  `permission_engine.run(...)`. `capture_screen` grabs and saves a
  full-desktop screenshot (all monitors) to `screenshots/` on every
  invocation with zero confirmation. `analyze_screen_with_gpt56` additionally
  uploads that screenshot to OpenAI, gated only by a
  `user_confirmed_screen_share: bool = False` parameter that the calling LLM
  itself sets — not validated against any independent user-facing
  confirmation, not audited, not expiring, and not routed through
  `nova_policy` at all. This is inconsistent with the correctly-gated pattern
  already used in the same codebase for `close_app`, `restart_app`, and
  `read_email`'s full-body fetch, all of which do call
  `permission_engine.run(...)`.
- **User impact:** A user (or a sufficiently adversarial prompt/on-screen
  text) could trigger a full-desktop screenshot, and potentially its upload
  to OpenAI, without the independent confirmation step the developer clearly
  intended to require (evidenced by the dead policy registrations sitting
  right next to the tool code). This is a real, currently shippable privacy
  gap, not a hypothetical.
- **Technical cause:** The two tools were written before/without wiring into
  `nova_policy`, or the wiring was dropped during a refactor; the policy
  registrations were kept but never connected.
- **Evidence:** see `docs/audit/2026-07-22/FEATURE_AUDIT_AI_TOOLS_PERMISSIONS.md`
  §3.2 for full file:line citations and side-by-side comparison against the
  working `close_app`/`restart_app`/`read_email` gate pattern.
- **Proposed fix:** Wrap both tool bodies in
  `permission_engine.run(action_name="capture_screen", ...)` /
  `permission_engine.run(action_name="analyze_screen_with_gpt56", ...)`
  exactly like the three working examples already in the codebase. Small,
  mechanical, high-value fix.
- **Verification steps:** After wiring, manually invoke both tools via
  `driver.py chat` and confirm a pending-approval entry appears in
  `audit_logs/nova_actions.jsonl` and the Dashboard's Approve/Deny queue
  before the screenshot is taken/uploaded; re-run `driver.py tools`.

---

### NOVA-006 — Raw-string Windows path literal doubles a backslash
- **Severity:** Low
- **File:line:** `Dashboard/appicons.py:101`
- **Description:** `os.environ.get("WINDIR", r"C:\\Windows")` uses a raw
  string (`r"..."`) containing `\\`. Because raw strings do not process
  escape sequences, `r"C:\\Windows"` evaluates to the literal 12-character
  string `C:\\Windows` (two backslash characters between `C:` and
  `Windows`), not the intended single-backslash `C:\Windows`. Confirmed
  directly: `python -c "print(repr(r'C:\\Windows'))"` → `'C:\\Windows'`
  (repr's `\\` denotes one real backslash each, i.e. two real backslashes
  in the actual string).
- **User impact:** Only reachable when the `WINDIR` environment variable is
  unset — which is extremely rare on Windows (it is a standard system
  variable almost always present) — so real-world impact is low. If it
  ever did trigger, `os.path.join("C:\\Windows", "explorer.exe")` would
  produce `C:\\Windows\explorer.exe`, which Windows path APIs often
  tolerate but is not guaranteed to resolve correctly in every icon-loading
  code path.
- **Technical cause:** Misunderstanding of raw-string escaping — the author
  likely intended `r"C:\Windows"` (single backslash, correct) or
  `"C:\\Windows"` (non-raw, also correct) but combined both conventions.
- **Evidence:**
  ```python
  >>> print(repr(r'C:\\Windows'))
  'C:\\Windows'   # i.e. the actual string contains two backslashes
  ```
  ```
  Dashboard/appicons.py:100-101
      if lowered == "explorer" or lowered.endswith("explorer.exe"):
          return os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "explorer.exe")
  ```
- **Proposed fix:** Change to `os.environ.get("WINDIR", r"C:\Windows")`
  (single backslash) or use `Path("C:/Windows")` for a
  platform-normalized literal.
- **Verification steps:** `python -c "import os; print(os.environ.get('WINDIR', r'C:\Windows'))"`
  should print `C:\Windows`; unset `WINDIR` in a test environment (or
  patch `os.environ` in a unit test) and confirm `_icon_source("explorer")`
  resolves to a real, existing `explorer.exe` path.

---

### NOVA-007 — `providers/groq_provider.py` is an empty, unwired stub
- **Severity:** Low
- **File:line:** `providers/groq_provider.py` (0 bytes)
- **Description:** The file exists but is completely empty — no `class
  GroqProvider`, no imports, nothing. It is not imported by
  `providers/__init__.py` (which only exports `OllamaProvider` and
  `OpenAIProvider`), and a repo-wide grep for `GroqProvider` found zero
  references anywhere. Meanwhile, a fully working Groq integration already
  exists and is documented in `DEVELOPMENT.md` as `ask_groq` in
  `tools/models.py`, implemented directly against the OpenAI-compatible
  client (`GROQ_BASE_URL`/`DEFAULT_GROQ_MODEL` at
  `tools/models.py:17-18`).
- **User impact:** None today (dead code, not imported, not exercised by
  anything). Risk is future confusion: a contributor extending the
  `providers.*`-based `nova_core` routing layer might reasonably assume
  Groq support already exists there, or might not realize
  `tools.models.ask_groq` is the actual, working implementation.
- **Technical cause:** Unfinished scaffolding — same pattern already noted
  in `DEVELOPMENT.md`'s "Known issues" for `core/` ("written but not imported
  anywhere yet").
- **Evidence:**
  ```
  $ Read providers/groq_provider.py
  Warning: the file exists but the contents are empty.

  $ grep -rn "GroqProvider" --include=*.py .
  (no matches)
  ```
- **Proposed fix:** Either implement `GroqProvider` (mirroring
  `providers/openai_provider.py`'s structure, pointed at
  `https://api.groq.com/openai/v1`) and wire it into
  `providers/__init__.py` + `nova_core/provider_registry.py`, or delete the
  empty file until it's actually needed, to avoid the dead-stub confusion.
  This is a design decision for Ahmed, not something to change unilaterally
  per `DEVELOPMENT.md`'s "ask Ahmed" guidance for the `core/` scaffolding.
- **Verification steps:** N/A until a decision is made; if implemented,
  verify via `driver.py tools` and a manual `ask_groq`-equivalent smoke
  test through the new provider.

---

### NOVA-008 — Dead `AmbientVisionMonitor.health_check()` uses an un-offloaded blocking call
- **Severity:** Low
- **File:line:** `nova_guardian/ambient_vision.py:220-227`
- **Description:** `AmbientVisionMonitor.health_check()` is a plain
  synchronous `def` (not `async def`) containing a blocking
  `requests.get(..., timeout=5)` call at line 224. A repo-wide grep for
  `.health_check()` and `health_check` found this method is **never called
  anywhere** in the codebase — it is dead code. This stands in contrast to
  `_call_local_vision_model` in the same class, whose own blocking
  `requests.post` (line 527) *is* correctly wrapped in `await
  asyncio.to_thread(...)` when called from `analyze_once()` (line 704).
- **User impact:** None today — it's unused. If a future change wires this
  method into `analyze_once()`, `run()`, or any other `async def` method
  in the same class without also wrapping it in
  `asyncio.to_thread(...)`/`run_in_executor`, it would block the guardian's
  event loop for up to 5 seconds (its configured timeout) on every health
  check.
- **Technical cause:** Incomplete feature — likely written in anticipation
  of a health-check integration that hasn't landed yet.
- **Evidence:**
  ```
  $ grep -rn "health_check" --include=*.py .
  nova_guardian/ambient_vision.py:220:    def health_check(self) -> bool:
  (no other reference to AmbientVisionMonitor.health_check anywhere)
  ```
- **Proposed fix:** When this method is wired up, either make it `async
  def` and wrap the `requests.get` call in `asyncio.to_thread(...)` (same
  pattern as `_call_local_vision_model`), or convert it to use `httpx`'s
  async client if one is already a dependency.
- **Verification steps:** N/A until wired up; if/when it is, verify with
  the same technique proposed for NOVA-003.

---

### NOVA-009 — Miscellaneous silent `except Exception:` blocks without logging
- **Severity:** Low
- **File:line:** `nova_wakeword.py:395-396`,
  `nova_integrations/notifications.py:144-145`,
  `Dashboard/actions.py:162-163`, `Dashboard/app_registry.py:267-268`,
  `Dashboard/app_icons.py:46-48, 57-59`
- **Description:** Across the codebase, the overwhelming majority of
  `except Exception:` blocks correctly log via `logger.exception(...)`
  before returning a fallback (confirmed by grep: 30+ matching instances in
  `tools/*.py`, `nova_startup.py`, `nova_integrations/*.py`). A smaller set
  of blocks swallow the exception with no logging and no explanatory
  comment: `nova_wakeword.py:395-396` (bare `except Exception: pass`
  inside what appears to be cleanup code), `nova_integrations/
  notifications.py:144-145` (`except Exception: return False`, no log),
  `Dashboard/actions.py:162-163` (`except Exception: pass` around an
  `integration_feeds.snapshot_messages()` call inside the
  `sync_integrations` handler), `Dashboard/app_registry.py:267-268`
  (`except Exception: return None`), and two spots in
  `Dashboard/app_icons.py` (lines 46-48 and 57-59, both bare `pass`). Some
  other silent-except blocks in the codebase (`tools/guardian.py:39-41`,
  `nova_integrations/secrets.py:61-63`, `providers/openai_provider.py:
  161-162`, `providers/ollama_provider.py:119-120`) are deliberate,
  explained by an adjacent comment, or are health-check-style probes where
  "return False on any failure" is the intended contract — those are not
  flagged here.
- **User impact:** Low individually, but collectively this reduces
  observability when something goes wrong in wake-word cleanup,
  notification dispatch, dashboard app-icon resolution, or the
  dashboard's integration-snapshot refresh — failures in these paths leave
  no trace in any log.
- **Technical cause:** Inconsistent application of the codebase's own
  otherwise-good "log then degrade" convention.
- **Evidence:** (representative sample; see file:line list above for the
  rest)
  ```
  nova_wakeword.py:395-396
      except Exception:
          pass

  Dashboard/actions.py:158-163
      try:
          import integration_feeds
          messages.extend(integration_feeds.snapshot_messages())
      except Exception:
          pass
  ```
- **Proposed fix:** Add `logger.exception(...)`/`logger.debug(...)` (module
  already has a logger in most of these files) to each of the listed
  blocks, consistent with the pattern used everywhere else in `tools/`.
- **Verification steps:** Re-run `driver.py tools` and the JS/Python test
  suites after the change to confirm no behavior changed, only
  observability improved.

---

### NOVA-010 — Redundant duplicate `tzdata` line in `requirements.txt`
- **Severity:** Informational
- **File:line:** `requirements.txt:25-26`
- **Description:** `tzdata` is listed twice: once correctly scoped
  (`tzdata>=2026.3; platform_system == "Windows"`, line 25) and once
  unconditionally with no version pin (`tzdata`, line 26). Harmless (pip
  just treats the second as a redundant unpinned re-declaration of the
  same package) but confusing, and directly related to NOVA-001 since
  despite being listed twice, it still wasn't installed in this venv.
- **User impact:** None functionally; minor maintenance confusion.
- **Evidence:** `requirements.txt:25: tzdata>=2026.3; platform_system == "Windows"` / `requirements.txt:26: tzdata`
- **Proposed fix:** Remove line 26; keep only the conditional, version-pinned
  line 25 (or drop the platform condition entirely and keep one
  unconditional pinned line, since `tzdata` is a no-op on non-Windows
  platforms that already ship IANA data).
- **Verification steps:** `pip install -r requirements.txt` in a clean venv
  and confirm `tzdata` installs with the intended version constraint.

---

### NOVA-011 — Tauri desktop shell disables Content-Security-Policy
- **Severity:** Informational
- **File:line:** `Dashboard/nova-app/src-tauri/tauri.conf.json:29-31`
- **Description:** `"security": { "csp": null }` explicitly disables
  Tauri's Content-Security-Policy enforcement for the webview. Tauri's own
  documentation recommends always setting a CSP as defense-in-depth, even
  when the frontend is fully local/bundled (as this one is —
  `"frontendDist": "../../web"`, no dev-server URL, confirmed no
  `localhost`/`127.0.0.1`/`devUrl` anywhere in `tauri.conf.json` or
  `capabilities/default.json`). Partially mitigating this:
  `capabilities/default.json` grants only a minimal, reasonable permission
  set (`core:default`, window show/hide/minimize/maximize/focus,
  `core:event:default`, `core:app:default` — no filesystem, shell, HTTP, or
  clipboard capability grants), so the practical blast radius of an
  injected script (if one ever got in via a future XSS in the dashboard's
  own JS) is limited to window chrome control rather than full system
  access.
- **User impact:** No active exploit path identified in this audit (static,
  locally-bundled content, minimal capability grants), but it is a
  defense-in-depth gap that Tauri's own security guidance flags.
- **Evidence:**
  ```
  Dashboard/nova-app/src-tauri/tauri.conf.json:29-31
      "security": {
        "csp": null
      }
  ```
  Icons referenced in `bundle.icon` (`icons/32x32.png`, `icons/128x128.png`,
  `icons/128x128@2x.png`, `icons/icon.icns`, `icons/icon.ico`) were all
  confirmed present on disk — no missing-icon issue.
- **Proposed fix:** Set an explicit CSP appropriate for a fully-local,
  script-only dashboard, e.g. `"csp": "default-src 'self'; img-src 'self'
  data:; style-src 'self' 'unsafe-inline'"` (adjust to match what
  `web/support.js`/`web/*.js` actually need — some inline styles may
  require `'unsafe-inline'` for `style-src`).
- **Verification steps:** After setting a CSP, run the Tauri dev/build
  cycle (requires the Rust toolchain, out of scope for this audit) and
  confirm the dashboard still renders and functions with the DevTools
  console free of CSP violation errors.

---

### NOVA-012 — Hardcoded `C:\` drive assumption in system-info tool
- **Severity:** Informational
- **File:line:** `tools/information.py:117`
- **Description:** `get_system_info` calls `psutil.disk_usage("C:\\")`,
  always reporting the `C:` drive regardless of where NOVA, its data, or
  the user's files actually live.
- **User impact:** Minor — disk-usage answers from NOVA's voice assistant
  are only ever about the `C:` drive, which is likely correct for this
  single-drive Windows setup but would silently mislead on a multi-drive
  machine.
- **Evidence:** `tools/information.py:117: disk = psutil.disk_usage("C:\\")`
- **Proposed fix:** Optional — could use
  `psutil.disk_usage(os.path.splitdrive(Path.home())[0] + "\\")` or report
  multiple drives, but this is a reasonable simplification for a
  single-user, single-drive assistant and may not be worth changing.
- **Verification steps:** N/A (informational; no fix required unless Ahmed
  wants multi-drive reporting).

---

## Appendix — Raw command log (abbreviated)

```
& venv\Scripts\python.exe --version                       → Python 3.14.6
& venv\Scripts\python.exe -m py_compile <78 files>         → exit 0, no output
& venv\Scripts\python.exe -c "import nova_core"            → OK, 37-50s (repeatable)
& venv\Scripts\python.exe -c "import nova_guardian"        → OK, 2.38s
& venv\Scripts\python.exe -c "import nova_integrations"    → OK, 0.27s
& venv\Scripts\python.exe -c "import nova_policy"          → OK, 0.06s
& venv\Scripts\python.exe -c "import providers"            → OK, 0.00s (after nova_core warm)
& venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
  → Ran 14 tests, 13 ok / 1 ERROR (tzdata)
& venv\Scripts\python.exe -m unittest discover -s Dashboard/tests -p "test_*.py" -v
  → Ran 34 tests, 33 ok / 1 FAIL (tzdata)
& node --test Dashboard/tests/*.test.js                    → 16 pass, 0 fail
& npm run lint  (in Dashboard/)                             → exit 0
& npm run build (in Dashboard/)                             → exit 0, "Static dashboard build verified..."
& venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py tools
  → PASS: 33/33 checks OK
& venv\Scripts\python.exe -m pip show pytest tzdata        → both "not found"
```
