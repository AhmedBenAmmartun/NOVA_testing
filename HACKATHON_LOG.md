# OpenAI Build Week Development Log

This file tracks what existed before the hackathon work and what Codex adds
during Build Week. Keep entries dated, concrete, and tied to commits or Codex
task/session IDs so the submission can clearly separate old work from new work.

## Submission Evidence Checklist

- [ ] Confirm the official Devpost deadline and submission requirements before
      submitting.
- [ ] Keep this repo's API keys and private files out of GitHub.
- [ ] Create or identify a clean baseline commit for pre-existing NOVA work.
- [x] Build the new hackathon feature after the submission period start.
- [x] Make GPT-5.6 and Codex central to the new hackathon functionality.
- [ ] Record dated commits for every meaningful feature change.
- [ ] Record the main Codex task/session ID needed for `/feedback`.
- [x] Add README setup instructions before submitting.
- [ ] Add a short demo video link before submitting.
- [x] Document third-party services and licenses.

## Baseline Status

Last known committed baseline before this log:

- Commit: `626d49d` (`Add Groq specialist model to NOVA`)
- Branch at time of log creation: `main`

Important: when this log was created on 2026-07-14, the working tree already
had modified and untracked files. Review those changes before calling any new
commit the official Build Week baseline.

## Existing Before Build Week

These items are treated as pre-existing NOVA work unless later changed in a
specific dated Build Week entry.

- LiveKit Agents app wired in `agent.py`.
- Gemini Realtime voice conversation using Ahmed's tuned model, voice, VAD,
  temperature, and `video_input=False`.
- NOVA persona in `prompts.py` via `SYSTEM_PROMPT`.
- Tool package split under `tools/`.
- Desktop controls: open app, close app, restart app, open website, app status.
- File and notes tools with sandboxing and `.env*` protection.
- Information tools: weather, web search, system info, and time.
- Media tools: YouTube search, media keys, volume, Spotify current song, and
  Spotify playback support.
- Specialist model tools: `ask_groq` and `ask_ollama`.
- Screen capture tool that saves PNG files under `screenshots/`.
- Tool logging to `nova_tools.log`.
- Driver/test harness for tools, chat, console check, and dev check.
- Roadmap phases 1 and 2 completed before this log.

## New Build Week Work

Add one entry per meaningful change. Prefer one feature per entry.

### 2026-07-14 - Hackathon tracking log

- Feature: Build Week evidence tracking.
- What Codex implemented: created `HACKATHON_LOG.md` to separate pre-existing
  NOVA work from new hackathon work.
- How GPT-5.6 is used: not applicable; this entry is project documentation.
- Codex task/session: TODO.
- Related commit: TODO.
- Tests or verification: documentation-only change.

### 2026-07-14 - Submission documentation prep

- Feature: Build Week submission documentation.
- What Codex implemented: created `README.md`, `HACKATHON_SUBMISSION.md`, and
  `THIRD_PARTY_SERVICES.md` with setup instructions, Devpost field tracking,
  demo planning, testing instructions, and third-party service notes.
- How GPT-5.6 is used: not applicable yet; this entry prepares the required
  documentation for the upcoming GPT-5.6-centered feature.
- Codex task/session: TODO.
- Related commit: TODO.
- Tests or verification: documentation-only change.

### 2026-07-14 - GPT-5.6 reasoning and screen help

- Feature: Opt-in GPT-5.6 reasoning and confirmed screen analysis.
- User goal: make NOVA valid for OpenAI Build Week by adding meaningful new
  Codex/GPT-5.6 functionality without replacing the existing Gemini Live voice
  stack.
- What existed before: Gemini Realtime voice, Groq/Ollama specialists, local
  screenshot capture, and safety-focused local tools.
- What Codex implemented: added an OpenAI Responses API client, `ask_gpt56`,
  `analyze_screen_with_gpt56`, prompt routing rules, tool exports, agent wiring,
  non-secret environment config, driver smoke-test awareness, and documentation.
- How GPT-5.6 is central: GPT-5.6 is the named specialist for explicit
  reasoning/planning requests and confirmed screenshot analysis.
- Other AI/tools used: Gemini remains the realtime voice layer; Groq and Ollama
  remain optional specialists.
- Files changed: `tools/models.py`, `tools/vision.py`, `tools/__init__.py`,
  `agent.py`, `prompts.py`, `.env.example`, driver scripts, README/submission
  docs, and `ROADMAP.md`.
- Tests or verification: `driver.py tools` passed 11/11 on 2026-07-13.
  `driver.py chat` was attempted twice but Gemini returned 504/503
  service-side errors after retries. The GPT-5.6 screen-share confirmation
  guard was checked without a network call.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: Show NOVA using GPT-5.6 for a planning task, then a confirmed
  screen-help task after hiding private information.

### 2026-07-15 - Obsidian memory search (verified)

- Feature: `search_memory` tool — NOVA searches Ahmed's Obsidian vault by
  note name and content and returns matching note paths.
- User goal: give NOVA local, private long-term memory backed by Ahmed's
  real notes (Roadmap Phase 10 started).
- What existed before: notes.txt save/read only; no vault access.
- What was implemented: `tools/obsidian.py` (vault path from
  `OBSIDIAN_VAULT_PATH`, sandboxed to the vault, `.obsidian/` blocked,
  100 KB per-note cap, graceful errors), exported in `tools/__init__.py`,
  registered in `agent.py`. Built with Claude (chat), not Codex — recorded
  for transparency in separating tool contributions.
- How GPT-5.6 is central: not part of this feature.
- Other AI/tools used: Claude chat (implementation), Claude Code
  (verification 2026-07-15).
- Files changed: `tools/obsidian.py`, `tools/__init__.py`, `agent.py`.
- Tests or verification: driver `tools` 11/11 on 2026-07-15; direct call
  confirmed the vault resolves and search matches; driver `chat` turn saw
  the agent call `search_memory` and answer with the match count (Gemini
  503'd twice, retried successfully). Known gap: no `read_obsidian_note`
  tool yet, and no driver check covers `search_memory`.
- Codex task/session: n/a (Claude).
- Related commit: TODO (working tree not yet committed).
- Demo notes: "NOVA, what do my notes say about <topic>?" — pairs well with
  the planned study/quiz mode.

### 2026-07-16 - Code fix pass + memory read tool (Claude)

- Feature: bug fixes and the `read_memory_note` tool.
- User goal: "fix all the issues that I have with the code."
- What was implemented (via Claude Code, not Codex): new `read_memory_note`
  tool so NOVA can read the Obsidian notes that `search_memory` finds
  (registered in `tools/__init__.py` + `agent.py`; SYSTEM_PROMPT memory
  guidance added); `ask_ollama` default model fixed from `gemma4:latest`
  (not installed — broken on fresh setups) to `mistral:latest`; driver now
  tests the Obsidian tools in an isolated temp vault (14 checks) and its
  latent `play_spotify_song` assertion ("not set up" vs actual "not
  configured") was fixed; unused `livekit-plugins-groq` removed from
  requirements.txt; `offline_agent.py` `.env` precedence aligned with
  `agent.py`.
- How GPT-5.6 is central: not part of this pass.
- Other AI/tools used: Claude Code.
- Files changed: `tools/obsidian.py`, `tools/__init__.py`, `tools/models.py`,
  `agent.py`, `prompts.py`, `offline_agent.py`, `requirements.txt`, both
  driver.py copies (`.claude/` and `.agents/`).
- Tests or verification: driver `tools` 14/14 on 2026-07-16; live `chat`
  turn: NOVA called `search_memory` then `read_memory_note` and summarized
  a real vault note in one line (first attempt failed on Gemini-side 504s,
  second succeeded).
- Codex task/session: n/a (Claude).
- Related commit: TODO.
- Demo notes: "NOVA, what do my notes say about X?" now works end-to-end:
  find the note, read it, answer.

### 2026-07-16 - Course materials PDF/text reader

- Feature: `read_course_material` tool for sandboxed course materials.
- User goal: do prompt 2 from `CODEX_PROMPTS.md` — let NOVA read course PDFs,
  Markdown, and text files from a project-local `course_materials/` folder.
- What existed before: general file tools could read small text files from
  broad approved folders, but NOVA had no PDF extraction or dedicated course
  material sandbox.
- What Codex implemented: added a course-material resolver limited to
  `course_materials/`, a `read_course_material` function tool with PDF page
  ranges and a 15k output cap, agent/tool exports, prompt guidance, isolated
  driver checks with a generated temp PDF, a tracked folder placeholder, and
  private course-material gitignore rules.
- How GPT-5.6 is central: this is the material-ingestion foundation for the
  GPT-5.6-powered Study Mode & Quiz Mode in prompt 3; this specific tool does
  not call GPT-5.6.
- Other AI/tools used: Codex implemented the change; Gemini text chat was
  attempted for end-to-end verification.
- Files changed: `tools/common.py`, `tools/files.py`, `tools/__init__.py`,
  `agent.py`, `prompts.py`, both driver copies, `requirements.txt`,
  `.gitignore`, `course_materials/.gitkeep`, `CODEX_PROMPTS.md`,
  `ROADMAP.md`, `AGENTS.md`, and `CLAUDE.md`.
- Tests or verification: installed prompt-approved `pypdf 6.14.2`; driver
  `tools` passed 17/17 on 2026-07-16, including text extraction, PDF
  extraction, and course-folder escape blocking. A direct call read
  `course_materials/sample_biology.pdf` and extracted the expected sentence.
  Full driver `chat` was attempted three times but Gemini returned 504/503,
  then free-tier 429 quota for `gemini-3.5-flash` before tool execution.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: Drop professor PDFs into `course_materials/`, then ask NOVA to
  read a file or a page range before using prompt 3's study/quiz flow.

### 2026-07-16 - Study Mode and Quiz Mode prompt choreography

- Feature: prompt-driven Study Mode and Quiz Mode over `course_materials/`.
- User goal: turn the course-material reader into an actual study/quiz mode,
  so Ahmed can ask NOVA to teach from a file or quiz him on course material.
- What existed before: NOVA could extract course text with
  `read_course_material`, but did not have explicit behavior for study mode,
  quiz flow, missed-question repetition, or saving weak topics.
- What Codex implemented: added SYSTEM_PROMPT rules for Study Mode triggers,
  Quiz Mode triggers, course-file selection, `read_course_material` usage,
  `ask_gpt56` quiz generation from extracted material, one-question-at-a-time
  spoken flow, answer grading, mistake explanations, missed-topic repetition,
  and `save_note` quiz-result summaries.
- How GPT-5.6 is central: quiz questions are explicitly routed through
  `ask_gpt56` using the extracted course material, keeping GPT-5.6 central to
  the Build Week study demo.
- Other AI/tools used: Codex made the prompt/docs change; Gemini text chat was
  attempted for end-to-end verification.
- Files changed: `prompts.py`, `CODEX_PROMPTS.md`, `ROADMAP.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, and `README.md`.
- Tests or verification: driver `tools` passed 17/17 on 2026-07-16.
  `driver.py chat "Quiz mode..."` was attempted but Gemini returned 504 and
  then free-tier 429 quota for `gemini-3.5-flash` before tool execution.
  A direct `ask_gpt56` quiz-generation smoke test returned rate-limited or
  out-of-credits, so final end-to-end quiz verification is still blocked by
  external API quota.
- Codex task/session: TODO.
- Related commit: TODO.

### 2026-07-16 - Desktop/file control expansion

- Feature: pull-up-anything workflow and richer Windows desktop control.
- User goal: make NOVA more useful as a real desktop assistant: find/open
  files Ahmed asks for, create new items on the right Desktop location, and
  control visible windows, notifications, quick settings, and virtual
  desktops.
- What existed before: approved app open/close/restart, broad sandboxed file
  read/list/create, media keys, and volume control.
- What Codex implemented: added `find_user_file`, `open_file_or_folder`,
  `create_desktop_file`, `create_desktop_folder`, `control_window`,
  `open_notifications`, `open_quick_settings`, and
  `manage_virtual_desktop`; expanded approved app aliases; updated
  SYSTEM_PROMPT routing so "pull up/open/find" uses file search/open and
  split-screen/desktop requests use the new window tools; registered all
  tools in `agent.py`; and added isolated driver checks that use a temporary
  Desktop folder.
- How GPT-5.6 is central: not part of this feature; this is local Windows
  action tooling that makes the Build Week assistant demo more practical.
- Other AI/tools used: Codex implemented and verified the change.
- Files changed: `tools/common.py`, `tools/files.py`, `tools/desktop.py`,
  `tools/__init__.py`, `agent.py`, `prompts.py`, both driver scripts,
  `ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, `CODEX_PROMPTS.md`, `README.md`,
  and `HACKATHON_SUBMISSION.md`.
- Tests or verification: `py_compile` passed for changed Python files.
  Driver `tools` passed 27/27 on 2026-07-16. Full driver `chat "What time is
  it? Answer briefly."` succeeded: NOVA called `get_time` and answered.
  Gemini logged retryable 504 warnings during the run, but the driver exited
  successfully.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: Show commands like "find my schedule file", "create a Desktop
  folder called NOVA demo", "snap Chrome left", and "open a new desktop."

### 2026-07-16 - Obsidian memory write path

- Feature: vault-backed memory writes and conversation transcript mirroring.
- User goal: Ahmed asked why NOVA conversations were not saved to the
  Obsidian vault, then asked Codex to build the missing write path.
- What existed before: NOVA could search/read Obsidian notes and saved
  conversations only under the project-local gitignored `conversation_logs/`
  folder.
- What Codex implemented: added `save_memory_note` in `tools/obsidian.py`;
  writes are sandboxed to `<vault>/NOVA/`, timestamped, never overwrite, and
  refuse obvious passwords/API keys/tokens. `SessionConversationRecorder` now
  keeps the local `conversation_logs/` copy and also mirrors live-session
  Markdown transcripts into `<vault>/NOVA/Conversations/YYYY/MM/` when
  `OBSIDIAN_VAULT_PATH` is configured. The new tool is exported, registered
  in `agent.py`, described in `SYSTEM_PROMPT`, and covered in both driver
  copies using a temporary vault.
- How GPT-5.6 is central: not part of this feature; this is local memory
  infrastructure that improves NOVA's persistent context.
- Other AI/tools used: Codex implemented and verified the change.
- Files changed: `tools/obsidian.py`, `tools/conversations.py`,
  `tools/__init__.py`, `agent.py`, `prompts.py`, both driver scripts,
  `ROADMAP.md`, `CODEX_PROMPTS.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `HACKATHON_LOG.md`, and `HACKATHON_SUBMISSION.md`.
- Tests or verification: `py_compile` passed for the changed Python files.
  Driver `tools` passed 31/31 on 2026-07-16, including conversation mirror,
  explicit memory write, memory search, and secret-write refusal checks in an
  isolated temp vault. Full driver `chat "What time is it? Answer briefly."`
  succeeded once with a `get_time` tool call and response, but the final rerun
  after safety hardening hit Gemini-side 503/504 errors after retries.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: Ask NOVA to remember a harmless project preference, then search
  the Obsidian vault for it. For transcript mirroring, run a live console
  voice session and show the new note under `NOVA/Conversations/`.

### 2026-07-16 - NOVA Core 1.0 roadmap consolidation

- Feature: future-work planning from Ahmed's attached design notes.
- User goal: preserve the recommended improvement order for NOVA: fix queued
  replies and interruption handling first, then build routing, offline mode,
  standby alerts, speaker recognition, permissions, and specialists.
- What existed before: `ROADMAP.md` already had phases for standby, voice
  recognition, offline mode, and dashboard ideas, but the attached design
  notes were not captured as a clear build order or Codex prompt list.
- What Codex implemented: added a "NOVA Core 1.0 priority order" to
  `ROADMAP.md` and added ready-to-run `CODEX_PROMPTS.md` entries for
  conversation controller, model router/specialist registry, offline fallback,
  and task manager/permission levels.
- How GPT-5.6 is central: not directly; this is architecture planning so the
  GPT-5.6 study/demo features remain reliable instead of being buried under
  unstable autonomy.
- Other AI/tools used: Codex summarized and integrated the attached design
  notes.
- Files changed: `ROADMAP.md`, `CODEX_PROMPTS.md`, and `HACKATHON_LOG.md`.
- Tests or verification: documentation-only planning change; driver results
  should be reported in the final task response.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: do not add speaker recognition or many autonomous agents before
  conversation cancellation, task state, routing, and permission boundaries
  exist.

### 2026-07-16 - Conversation Mode turn-handling first pass

- Feature: runtime conversation-control pass for delayed replies and barge-in.
- User goal: turn the attached design notes into a real NOVA mode instead of
  only a roadmap item, starting with the recommended first priority:
  conversation stability.
- What existed before: NOVA used Gemini Realtime with Ahmed's model/voice/VAD
  tuning, but `AgentSession` relied on implicit turn-handling defaults and the
  default 3-second AEC warmup could make immediate interruptions feel ignored.
- What Codex implemented: added explicit LiveKit turn handling in `agent.py`
  with `realtime_llm` turn detection, interruptions enabled, shorter 0.8s AEC
  warmup, explicit Gemini `START_OF_ACTIVITY_INTERRUPTS`, an interruptible
  greeting, and local conversation-state/interruption logging.
- How GPT-5.6 is central: not directly; this reliability pass protects the
  GPT-5.6 study/quiz demo path from stale or queued spoken replies.
- Other AI/tools used: Codex inspected the installed LiveKit and Gemini plugin
  code before changing the runtime configuration.
- Files changed: `agent.py`, `ROADMAP.md`, `CODEX_PROMPTS.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, and `README.md`.
- Tests or verification: `agent.py` compiled; a local AgentSession option
  check resolved `turn_detection=realtime_llm`, interruptions enabled,
  `min_duration=0.35`, and preemptive retries `2`; driver `tools` passed
  17/17. Full driver `chat` was attempted but Gemini returned 429 quota for
  `gemini-3.5-flash` before completing the turn. Live console barge-in still
  needs a manual interactive voice run.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: the next test is to run console mode, ask for a long answer, say
  "stop" or redirect mid-sentence, and confirm the old answer does not finish
  after the new request.

### 2026-07-16 - Session conversation memory

- Feature: automatic local session transcripts plus tools to search/read them.
- User goal: let NOVA remember what Ahmed talked about across sessions and
  let Ahmed access the saved conversation files later.
- What existed before: NOVA had a notes file, Obsidian search/read tools, and
  conversation state logging, but did not save full session transcripts or
  expose previous-session search to the agent.
- What Codex implemented: added `tools/conversations.py` with
  `SessionConversationRecorder`, `search_conversation_history`, and
  `read_conversation_history`; wired the recorder into `agent.py`; registered
  both tools; added prompt guidance; gitignored `conversation_logs/`; and
  added isolated driver checks in both driver copies.
- How GPT-5.6 is central: not directly; this is persistent local context that
  helps later GPT-5.6 study or planning turns refer back to previous work.
- Other AI/tools used: Codex implemented the recorder and tool path using the
  repo's NOVA tool pattern.
- Files changed: `agent.py`, `tools/common.py`, `tools/conversations.py`,
  `tools/__init__.py`, `.gitignore`, both driver copies, `prompts.py`,
  `ROADMAP.md`, `CODEX_PROMPTS.md`, `AGENTS.md`, `CLAUDE.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, and `README.md`.
- Tests or verification: compile check passed for changed Python files.
  Driver `tools` passed 19/19 with temp conversation logs, including search
  and read-latest checks. Full driver `chat` was attempted but Gemini returned
  429 quota for `gemini-3.5-flash` before the agent could call the tools.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: after a real voice session, ask "what did we talk about last
  session?" or "search my conversation history for quiz mode." NOVA should
  use the new history tools and read the saved Markdown log.

### 2026-07-16 - Debug pass after session memory

- Feature: verification and cleanup pass.
- User goal: debug the current code after adding saved conversation memory.
- What existed before: the latest Python files compiled and the local driver
  had passed, but the runtime startup path had not been rechecked in this
  turn and `AGENTS.md` / `CLAUDE.md` still said 27 tools.
- What Codex implemented: reran compile, driver tools, and console startup;
  corrected the documented tool count to 29 registered tools.
- How GPT-5.6 is central: not directly; this was reliability work around the
  local NOVA agent and Build Week documentation.
- Other AI/tools used: Codex used the NOVA run skill and tool-pattern rules.
- Files changed: `AGENTS.md`, `CLAUDE.md`, `ROADMAP.md`, and
  `HACKATHON_LOG.md`.
- Tests or verification: compile passed; driver `tools` passed 19/19;
  `driver.py console-check` passed; neutral full `chat` was attempted but
  Gemini returned 429 quota for `gemini-3.5-flash`.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: real agent startup is OK; the remaining blocked check is
  Gemini text-chat quota, not a local code failure.

### 2026-07-16 - Pylance/type-check cleanup

- Feature: editor diagnostics cleanup (reported as "1k+ problems").
- User goal: fix the Pylance error flood in VS Code.
- What existed before: ~95% of the diagnostics came from the cloned
  `references/` study repos (openai-python, python-agents-examples), which
  Pylance analyzed even though they are gitignored; the real project errors
  were untyped `turn_handling` in `agent.py` and `None` passed as the
  RunContext in the driver smoke tests.
- What Codex implemented: (Claude session) excluded `**/references/**` in
  `.vscode/settings.json`; annotated `CONVERSATION_MODE_TURN_HANDLING` as
  `TurnHandlingOptions` (a TypedDict — no runtime change to Ahmed's voice
  tuning); driver now uses `no_ctx = cast(RunContext, None)` and an
  `Any`-typed chat event item; synced the `.agents/` driver copy.
- How GPT-5.6 is central: not directly; reliability work on the NOVA repo.
- Other AI/tools used: Claude Code with pyright for verification.
- Files changed: `.vscode/settings.json`, `agent.py`,
  `.claude/skills/run-ai-agent/driver.py`,
  `.agents/skills/run-ai-agent/driver.py`, `ROADMAP.md`, `HACKATHON_LOG.md`.
- Tests or verification: pyright reports 0 errors on `agent.py` and the
  driver; driver `tools` passed 19/19; `import agent` OK; `chat` was
  attempted but Gemini `gemini-3.5-flash` returned the known free-tier 429
  daily quota (limit 20) before the turn completed.
- Codex task/session: n/a (Claude Code session).
- Related commit: TODO.
- Demo notes: none — editor hygiene only, no behavior change.

### 2026-07-16 - NOVA Desktop Companion dashboard first slice

- Feature: modular NOVA desktop widget/dashboard frontend.
- User goal: turn the attached NOVA dashboard/widget design and implementation
  prompt into the mode/widget experience, starting with a usable frontend.
- What existed before: NOVA had local voice/tools and roadmap notes for a
  future HUD, but no active dashboard app in this repo.
- What Codex implemented: imported the provided dashboard design scaffold into
  `Dashboard/`, replaced the Figma Make shell with a clean React/Vite app,
  added Orb/Mini/Compact/Full modes, a typed widget registry, widget gallery,
  persisted layout/theme settings, a mock `NovaClient` boundary, widgets for
  NOVA status, current priority, tasks, school assignments, Obsidian memory,
  activity, model health, system state, projects, and suggestions, plus
  dashboard architecture/run docs.
- How GPT-5.6 is central: not directly in this slice; the dashboard provides
  a visible command center for the GPT-5.6 study/screen-help workflow and for
  future live specialist/model status.
- Other AI/tools used: Codex read the attached Markdown/PDF/ZIP context,
  implemented the frontend, installed npm dependencies, and verified it.
- Files changed: `Dashboard/`, `.gitignore`, `ROADMAP.md`,
  `CODEX_PROMPTS.md`, `README.md`, `AGENTS.md`, `CLAUDE.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, and
  `THIRD_PARTY_SERVICES.md`.
- Tests or verification: `pnpm run typecheck` passed, `pnpm run build`
  passed, the Vite dev server returned HTTP 200 at
  `http://127.0.0.1:8443/`, and repo-level driver `tools` passed 31/31 after
  sandbox approval. The required full `chat "What time is it? Answer
  briefly."` smoke test hit repeated Gemini 504 deadline errors after
  retries. The dashboard still uses mock data; live NOVA HTTP/WebSocket
  events and the always-on-top desktop shell are next.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: show Mini mode as NOVA's desktop companion, then expand to the
  full command center to show memory, school, model, task, and activity
  widgets.

### 2026-07-16 - Native NOVA desktop widget shell

- Feature: native Windows desktop widget that sits on the desktop.
- User goal: Ahmed clarified that the NOVA companion should not just be a
  browser/app dashboard; it should be a desktop surface.
- What existed before: `Dashboard/` had a React/Vite command-center
  prototype that could run in a browser, but no native always-on-screen
  widget shell.
- What Codex implemented: added `Dashboard/desktop_widget.py`, a Tkinter
  desktop widget launched with `pythonw.exe`; added
  `Dashboard/start_desktop_widget.ps1`; made the widget frameless, draggable,
  topmost, hidden from the normal app-window style where Windows allows it,
  and able to switch between Orb, Mini, and Full modes. It reads local
  non-secret status from system metrics, `nova_tools.log`,
  `conversation_logs/`, and the Obsidian vault setting, while clearly showing
  "Live bridge pending" instead of faking live agent connectivity.
- How GPT-5.6 is central: not directly; this is the visible desktop surface
  for the broader NOVA/GPT-5.6 demo.
- Other AI/tools used: Codex implemented and launched the widget.
- Files changed: `Dashboard/desktop_widget.py`,
  `Dashboard/start_desktop_widget.ps1`, `Dashboard/README.md`,
  `Dashboard/AGENTS.md`, `ROADMAP.md`, `CODEX_PROMPTS.md`, `README.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, `AGENTS.md`, and
  `CLAUDE.md`.
- Tests or verification: `desktop_widget.py` compiled, `--self-test` returned
  local status successfully, and the widget was launched through
  `Dashboard/start_desktop_widget.ps1` with `pythonw.exe`; process check
  showed `pythonw.exe` running. Repo driver `tools` still passed 31/31 during
  this task; full chat remained blocked by Gemini 503 high-demand and 504
  deadline errors after retries.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: open the widget in Mini mode before the demo starts so NOVA has
  a visible desktop face even before the live event bridge lands.

### 2026-07-17 - NOVA native desktop skin polish and pre-push verification

- Feature: Rainmeter-style native desktop skin polish and GitHub readiness
  check.
- User goal: clean up the current code and docs so the repo can be pushed to
  GitHub with the new dashboard direction.
- What existed before: the native desktop surface existed as
  `Dashboard/desktop_widget.py`, but the docs still described the older
  single-widget shell and did not capture the newer skin modules, safe command
  bar, profile layouts, WorkerW attachment, or dedicated dashboard tests.
- What Codex implemented: reviewed the worktree, verified the new dashboard
  code, documented the July 17 desktop skin state, added the desktop skin
  unit-test command to the agent instructions, ignored generated
  `Dashboard/.figma/` metadata, and updated roadmap/submission docs for the
  verified state.
- How GPT-5.6 is central: not directly in this pass; it preserves the visible
  desktop surface used to demonstrate the broader GPT-5.6 study/screen-help
  workflow.
- Other AI/tools used: Codex inspected and verified the repo.
- Files changed: `.gitignore`, `AGENTS.md`, `CLAUDE.md`, `ROADMAP.md`,
  `HACKATHON_LOG.md`, `HACKATHON_SUBMISSION.md`, `README.md`,
  `CODEX_PROMPTS.md`, `Dashboard/README.md`, `Dashboard/AGENTS.md`, and
  `THIRD_PARTY_SERVICES.md`.
- Tests or verification: secret-pattern scan had no matches; `git diff
  --check` passed; Python `py_compile` passed for agent/tool/dashboard files;
  `python -m unittest Dashboard.test_desktop_skin` passed 7 tests;
  `Dashboard/desktop_widget.py --self-test` passed; `pnpm run typecheck` and
  `pnpm run build` passed; driver `tools` passed 31/31; full driver
  `chat "What time is it? Answer briefly."` succeeded with a `get_time` tool
  call.
- Codex task/session: TODO.
- Related commit: TODO.
- Demo notes: show the native skin on the desktop first, then use the React
  command center only as the larger future dashboard prototype.

## Third-Party Services And Licenses

Update this section before submission. Note the service purpose and where the
license or terms are documented.

- OpenAI Codex: used for Build Week implementation and session evidence.
- GPT-5.6: used for explicit reasoning/planning requests, confirmed screen
  analysis, and material-based quiz generation when NOVA enters Quiz Mode.
- Gemini API: existing realtime voice provider.
- LiveKit: existing realtime agent and audio infrastructure.
- Groq: existing cloud specialist model tool.
- Ollama: existing local specialist model tool.
- Spotify API: existing optional playback integration.
- Obsidian: used — `search_memory` / `read_memory_note` read Ahmed's local
  vault, `save_memory_note` writes new notes under `<vault>/NOVA/`, and live
  transcripts mirror to `<vault>/NOVA/Conversations/` when configured.
  Obsidian access stays local; nothing is uploaded by these tools.

## Submission Notes

- Recommended category: Apps for Your Life, unless the final demo focuses on
  developer tooling.
- Do not include copyrighted characters, copyrighted music, private material,
  or third-party logos unless permission is documented.
- Keep the demo under the official time limit and explain what Codex and
  GPT-5.6 added during Build Week.
