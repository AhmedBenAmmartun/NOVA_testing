# AGENTS.md — NOVA (LiveKit)

> **Project boundary — 2026-08-15**
>
> The legacy NOVA Dashboard has been detached from this repository/runtime.
> NOVA is the agent/AI operating layer. NOVA Vision remains part of NOVA.
> Dashboard/Valo is a separate project and may integrate later only through a
> defined external interface. Older dashboard references below may be historical.

_Last updated: 2026-09-05_

## What this is

NOVA (Neural Operations Virtual Assistant) is Ahmed's personal AI operating
assistant: voice-first, vision-capable, tool-using. This repo is the main
NOVA going forward — a LiveKit Agents app on Gemini Realtime, chosen because
its speech-to-speech voice is fast and smooth. See `ROADMAP.md` for phases;
update it whenever a feature lands.

There is an older NOVA (Flask + local voice listener) at
`C:\Users\ahmed\OneDrive\Desktop\Nova`. Don't merge them, but DO reuse its
working code when a phase overlaps (Canvas/Outlook in `nova/integrations.py`,
file sandbox `_resolve_safe_path`, vosk wake-word listener). Never run both
voice listeners at once — they will talk to each other out loud.

## Layout

```
agent.py            LiveKit AgentServer wiring: session, Gemini Realtime
                    (model gemini-2.5-flash-native-audio-preview-12-2025,
                    voice "Puck", temp 0.5, high-sensitivity VAD — Ahmed's
                    tuning), ai_coustics noise cancellation,
                    video_input=True for explicit NOVA Vision live tracks, greeting
prompts.py          SYSTEM_PROMPT (NOVA persona)
nova_bridge.py      private atomic dashboard command inbox/outbox + heartbeat
nova_agent_bridge.py  injects delegated user turns and resolves approvals
                    inside the active LiveKit agent process
tools/              function tools split into modules: common.py
                    (sandbox, logging), desktop.py (open/close/restart app,
                    website, is_app_running, window control, notifications,
                    quick settings, virtual desktops), files.py (notes +
                    file ops + file finder/open + Desktop create + course
                    materials), conversations.py (auto-saved session
                    logs + search/read tools),
                    information.py (weather, search, system info, time),
                    media.py (music/Spotify/YouTube), models.py (ask_gpt56
                    OpenAI + ask_groq cloud + ask_ollama local specialists),
                    vision.py (retired screenshot compatibility stub), obsidian.py (search_memory +
                    read_memory_note + save_memory_note over Ahmed's Obsidian vault,
                    vault-sandboxed); logging to nova_tools.log
PROJECT_TASKS.md    the task board + ready-to-run prompts. When Ahmed says
                    "do prompt N", read that file, execute exactly that
                    prompt, check it off on the task board, then follow
                    "After EVERY completed task" below.
references/         gitignored clones for studying working patterns:
                    python-agents-examples (LiveKit agent patterns),
                    openai-python (Responses API examples). Read, never
                    copy blindly, never import from here.
requirements.txt    deps (venv\ is the provisioned Python 3.14 venv; pypdf
                    powers course-material PDF extraction)
.env                secrets: LIVEKIT_URL/API_KEY/API_SECRET, GOOGLE_API_KEY,
                    OPENAI_API_KEY, SPOTIFY_CLIENT_ID/SECRET, GROQ_API_KEY,
                    OBSIDIAN_VAULT_PATH (path to the Obsidian vault)
.agents/skills/run-ai-agent/  run skill + driver.py test harness
Dashboard/          legacy/separate dashboard surface (not part of NOVA Vision)
vision-client/       standalone Tauri 2 trusted camera/mic control surface;
                    LiveKit JS publishes explicit media tracks to NOVA
vision_token.py      backend-only short-lived LiveKit token/agent-dispatch helper
Start-NOVA-Vision.ps1  launches agent worker + Vision client for development
```

## NOVA Lab development lifecycle

`nova_lab/` is NOVA's internal feature-development lifecycle, not a user-facing
mode. Experiments live on `lab/*` branches/worktrees under
`C:\Projects\NOVA-Labs\`. V1A has no model-callable production promotion,
ACTIVE retirement, restart, rollback, arbitrary shell, or direct
production-worktree write. V1B (2026-09-05, LAB checkpoint) adds an
inactive-by-default `development` NOVA OS capability exposing exactly
`lab_status`, `list_lab_features`, `get_lab_feature`, `list_lab_test_profiles`,
and `register_lab_feature` (`tools/development.py`) — inspection and
registration-metadata only, still with no test execution, transition,
promotion, retirement, restart, rollback, deletion, or approval tool.
`register_lab_feature` validates `capability_id` against
`nova_os.capabilities.CANONICAL_CAPABILITY_IDS`, the same canonical set
`nova_os.catalog` asserts its tool-wired capabilities against, so a Lab
feature can't be registered against a capability that doesn't exist. Future
release actions must go through `nova_policy`; the model never receives an
approval tool and cannot self-approve. Retired implementations are preserved
unless Ahmed explicitly approves deletion.

**Known limitation** (verified against `livekit-agents==1.6.6`,
`livekit-plugins-google==1.6.6`): activating `development` mid-conversation
does not make its tools callable within that SAME `session.run()` turn —
LiveKit snapshots the active tool list once per turn, so a chained tool call
in the same turn gets "Unknown function". Whether the tools become usable on
the FOLLOWING turn is not yet verified (blocked on Gemini free-tier quota).
See `docs/NOVA-LAB-LIFECYCLE.md` for the full root-cause trace. Do not assume
dynamic capability activation works intra-turn.

## Run & test (all verified)

```powershell
# from the project root
$env:PYTHONIOENCODING = 'utf-8'
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools           # local tools, no keys
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "..."      # full agent turn, text
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" console-check   # real app launch (SPEAKS ALOUD)
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" dev-check       # LiveKit Cloud registration
& ".\venv\Scripts\python.exe" agent.py console                                        # human path: live voice chat
```

After ANY change to `prompts.py`, `tools/`, or `agent.py`, run `tools` +
one `chat` before calling it done. Never claim something works untested.
See `.agents/skills/run-ai-agent/SKILL.md` for gotchas and troubleshooting.

## After EVERY completed task (mandatory — do not skip)

1. **Update `ROADMAP.md`**: check the item off / move it into "Current
   status" with today's date, note any bugs found, add the next recommended
   step, and bump the "Last updated" line at the top.
2. **During Build Week, add a dated entry to `HACKATHON_LOG.md`** (feature,
   files changed, how GPT-5.6/development assistant was used, verification results, commit).
3. **Keep the contribution cheat sheets current**: when the task changes the
   demo, submission story, or who/what contributed, update
   `HACKATHON_SUBMISSION.md` and any relevant README/log sections so the
   "what we did" and "what development assistant/GPT-5.6 contributed" story stays accurate.
4. Run the driver (`tools` + one `chat`, see above) and report the results
   honestly — including failures.
5. Update `AGENTS.md` and `DEVELOPMENT.md` only if the stack, layout, tool count,
   or rules changed.

## Non-obvious facts (learned the hard way)

- **Secrets**: `agent.py` loads `.env.local` first, then falls back to
  `.env`. The real file is `.env`. Keep that fallback; never print or
  commit either file; never hardcode keys.
- **Gemini models (free-tier key)**: `gemini-2.5-flash` is retired (404),
  2.0 models have zero free quota (429), and `gemini-flash-latest` 400s on
  tool calls because livekit-plugins-google keys thought_signature handling
  on the model *name* (`gemini-2.5`/`gemini-3` only). Always use explicit
  `gemini-3*` names for text LLM work; the driver uses `gemini-3.5-flash`.
- dev mode registers worker `my-agent` and needs explicit dispatch (e.g.
  LiveKit playground). Console mode is fully local, no LiveKit server.
- Music control is two-tier: media keys + Spotify window title work with no
  setup (pause/next/volume/current song); `play_spotify_song` needs
  SPOTIFY_CLIENT_ID/SECRET in `.env` and Spotify Premium for playback.
- Specialist models: `ask_gpt56` (OpenAI; OPENAI_API_KEY in `.env`, default
  gpt-5.6, override OPENAI_MODEL; opt-in only, no automatic calls),
  `ask_groq` (cloud; GROQ_API_KEY in `.env`, default
  llama-3.3-70b-versatile, override GROQ_MODEL) and `ask_ollama` (local;
  needs the Ollama app running on localhost:11434, default mistral:latest,
  override OLLAMA_MODEL/OLLAMA_BASE_URL). Both use the OpenAI client —
  Ollama needs no key. Installed local models: mistral, llama3.2.
- `analyze_screen_with_gpt56` captures and sends a screenshot to OpenAI only
  after Ahmed explicitly confirms screen sharing.
- The driver's `tools` check must patch `tools.files.NOTES_PATH` (not the
  package attribute) — patching the wrong module silently writes smoke-test
  notes into the real `notes.txt`.
- The driver's Desktop/file-search checks must patch `tools.files.SAFE_DIRS`
  and `tools.files.DEFAULT_DESKTOP_PATH`; otherwise smoke tests can touch
  Ahmed's real approved folders/Desktop.

## Rules

Do not break the working agent. Do not remove: Gemini Realtime, LiveKit,
`SYSTEM_PROMPT`, existing working tools. Video input is ON only for explicit media tracks published by the trusted
NOVA Vision client (`video_input=True`, approved 2026-08-13). Do not reintroduce
screenshot capture or automatically enable camera/microphone.

Before editing: read the relevant files, say what exists, make the smallest
safe change, one feature at a time. Prefer small functions, clear names,
docstrings, error handling on every tool. No giant files, no placeholder
implementations, no new packages unless genuinely required.

Tool safety: validate tool inputs; anything destructive (delete/overwrite/
move files, send email, purchases, shutdown/restart, system settings) must
ask Ahmed for confirmation first. `create_file` never overwrites.

## Known issues

- Phase 1 (security) is DONE as of 2026-07-09: open_app whitelisted, file
  tools sandboxed (`.env*` always blocked), notes path absolute, git repo
  initialized, GOOGLE_API_KEY renamed, deps trimmed, tool logging added.
- Phase 2 (tools/ package split) DONE 2026-07-11; the refactor broke two
  driver assertions and the notes isolation — repaired the same day.
- `play_spotify_song` is live (credentials in `.env`, OAuth cached in
  `.spotify_cache`, verified end-to-end 2026-07-09).
- `capture_screen` saves a PNG to `screenshots/`; Build Week added confirmed
  GPT-5.6 screen analysis for explicit screen-help requests.
- `read_course_material` reads PDF, Markdown, and text files only from
  `course_materials/` (gitignored except `.gitkeep`), supports PDF page
  ranges, caps output at about 15k chars, and uses `pypdf` (added 2026-07-16).
  Driver `tools` passed 17/17; full `chat` verification was blocked by
  Gemini free-tier 429 quota before tool execution.
- Study Mode / Quiz Mode is currently prompt choreography in `SYSTEM_PROMPT`,
  not a separate Python module. It should use `read_course_material`,
  `ask_gpt56`, and `save_note`; final live chat verification is blocked until
  Gemini and GPT-5.6 quotas are available again.
- Desktop/file expansion (2026-07-16): `find_user_file`,
  `open_file_or_folder`, `create_desktop_file`, `create_desktop_folder`,
  `control_window`, `open_notifications`, `open_quick_settings`, and
  `manage_virtual_desktop` are registered. Driver `tools` passed 27/27, and
  full `chat "What time is it? Answer briefly."` succeeded with a `get_time`
  tool call. Automated checks intentionally avoid moving live windows.
- Obsidian write path (2026-07-16): `save_memory_note` writes new Markdown
  notes only under `<vault>/NOVA/`, refuses obvious secrets, and never
  overwrites. Live session transcripts still save to `conversation_logs/` and
  now also mirror to `<vault>/NOVA/Conversations/YYYY/MM/` when configured.
  Driver `tools` passed 31/31; one full chat smoke check succeeded, while the
  final rerun hit Gemini-side 503/504 errors after retries.
- Dashboard status (updated 2026-07-21): the React/Vite + Tauri shell, the Tkinter
  skin, and the demo zip were removed at Ahmed's request. `Dashboard/` now
  holds the real dashboard implemented from `design_handoff_nova_desktop`
  (kept as `Dashboard/DESIGN_HANDOFF.md`): the 5-page design shell
  (`web/index.html` + `web/support.js`) with a live WebSocket bridge, served
  by `Dashboard/server.py` (aiohttp, 127.0.0.1:8787, no new dependencies)
  with `feeds.py` collectors and `actions.py` handlers. Real data: psutil
  stats, Spotify now-playing + media-key controls, wttr.in weather, Obsidian
  vault (count/recent/memories, `NOVA/Tasks.md` write-back, forget →
  `NOVA/.trash`), agent phase/activity tailed from `nova_tools.log`,
  approvals from `audit_logs/nova_actions.jsonl`, conversation bubbles from
  `conversation_logs/`, usage from `cloud_usage.json`, real app catalog /
  folders / recent files with real launches. Offline = the design's demo
  mode. Launch via `Dashboard\start_dashboard.ps1`. The private local bridge
  now sends Ctrl+K text turns to the active LiveKit session and resolves
  Approve/Deny inside the agent process. Commands are validated, atomic, and
  expire after two minutes. The calendar remains clearly marked Demo Data.
- `livekit-plugins-groq` was unused and removed from requirements.txt
  (2026-07-16); `ask_groq` calls Groq through the OpenAI client directly.
  It is still installed in the venv (harmless; gone on a fresh install).
- `mem0ai`/`langchain-community` are still installed in the venv but no
  longer in requirements.txt (harmless; gone on a fresh install).
- `.env` contains duplicate `OBSIDIAN_VAULT_PATH` and `OBSIDIAN_VAULT_NAME`
  lines (the last one wins), and `OBSIDIAN_VAULT_NAME` is not read by any
  code. Ahmed should clean this by hand — never print or edit `.env`.
- `NOVA_REALTIME_MODEL` / `NOVA_VOICE` / `NOVA_TEMPERATURE` exist in `.env`
  and `.env.example` but `agent.py` hardcodes Ahmed's tuning and ignores
  them. Wiring them up needs Ahmed's explicit OK (don't change his tuning).
- `core/` (task.py, router.py, orchestrator.py — model routing scaffolding)
  is written but not imported anywhere yet. Don't delete; wire it up or ask
  Ahmed.


## 2026-08-13 Vision architecture note

NOVA Vision is a separate small Windows surface, not the Valo dashboard. For
Phase 1 it uses Tauri 2 because the current machine snapshot has Node + Rust
but no detected .NET SDK. The media/session contract is shell-independent so a
future WinUI 3/Valo surface can reuse the same behavior. Camera and microphone
must start OFF. Frontend code must never receive `LIVEKIT_API_SECRET`;
`vision_token.py` generates a short-lived token in the trusted backend.
Guardian screenshot/ambient pixel capture is retired.
<!-- NOVA-A1-CORE-INTELLIGENCE BEGIN -->
## Core Intelligence A1 — 2026-09-06

A1 adds intrinsic read-only project awareness to the same unified NOVA agent.
`Assistant` owns one per-session `ContextBroker`; `get_nova_core_context` is
always present without creating a new capability ID or user-facing mode.

A1 ProjectState uses current repository/Git evidence, provenance, freshness,
UNKNOWN-safe resolution, bounded failed-approach awareness, and shadow
evaluation. Project packets remain `SHADOW_ONLY` unless the evaluation
graduation bar passes and trusted runtime configuration explicitly opts in.

A1 grants no approval, Safe Mode bypass, release, production, arbitrary shell,
or Git-write authority. Automatic REMEMBER/dedupe remains A2 work.

A1 transaction state: UNCOMMITTED - verifier must pass before checkpoint.
<!-- NOVA-A1-CORE-INTELLIGENCE END -->
