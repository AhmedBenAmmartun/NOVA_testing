# NOVA Roadmap

_Last updated: 2026-07-17_

## Mission

NOVA is Ahmed's personal AI operating assistant: voice-first, vision-capable,
tool-using — for coding, school, research, desktop control, media, email,
calendar, files, and daily productivity. This LiveKit + Gemini Realtime repo
is the main NOVA going forward (fast, smooth speech-to-speech voice).

## Current status (verified 2026-07-17)

Done and working:

- [x] LiveKit agent runs (console mode and LiveKit Cloud dev mode)
- [x] Gemini Realtime voice conversation (voice "Puck")
- [x] Camera/video input intentionally off (`video_input=False`)
- [x] ai_coustics noise cancellation
- [x] NOVA persona (`SYSTEM_PROMPT` in prompts.py)
- [x] 12 basic tools: weather, web search, open website, open app, YouTube
      search, system info, time, save/read notes, list/read/create files
- [x] `.env` credential loading fixed (was silently loading nothing)
- [x] `requirements.txt` completed (ai-coustics added)
- [x] Test harness + run skill (`.claude/skills/run-ai-agent/` — `tools`,
      `chat`, `console-check`, `dev-check` all pass)
- [x] **Phase 1 complete (2026-07-09)** — see below
- [x] Music controls with zero setup: `control_music` (play/pause, next,
      previous via media keys), `change_volume`, `get_current_song` (Spotify
      window title), `is_app_running` — all live-tested
- [x] `play_spotify_song` tool (spotipy) — code ready, waits for Spotify API
      credentials (see Phase 4)
- [x] **Phase 2 complete (2026-07-11)** — `tools.py` split into the `tools/`
      package (common, desktop, files, information, media, models, vision)
- [x] Phase 3 core (2026-07-11): `close_app` (approved-list only),
      `restart_app`, `is_app_running`
- [x] `capture_screen` tool — saves an all-screens PNG to `screenshots/`
      (Gemini *analysis* of the capture is Phase 9's remaining half)
- [x] Build Week GPT-5.6 tools (2026-07-14): `ask_gpt56` for explicit
      reasoning/planning and `analyze_screen_with_gpt56` for confirmed
      screenshot analysis through OpenAI.
- [x] Specialist models (2026-07-11, both live-tested end-to-end):
      `ask_groq` (cloud, fast; GROQ_API_KEY in `.env`) and `ask_ollama`
      (fully local/private; Ollama at localhost:11434, default
      `mistral:latest`, override with OLLAMA_MODEL / OLLAMA_BASE_URL)
- [x] Driver repaired after the tools/ refactor (2026-07-11): two stale
      assertions fixed, smoke-test notes isolated again (they had been
      writing to the real `notes.txt`), ask_groq unconfigured check added —
      `tools` passes 11/11
- [x] Voice tuning by Ahmed (2026-07-11): model
      `gemini-2.5-flash-native-audio-preview-12-2025`, voice "Puck",
      temp 0.5, high-sensitivity VAD, `video_input=False` for now
- [x] Obsidian memory search (verified end-to-end 2026-07-15):
      `search_memory` tool finds notes in Ahmed's Obsidian vault
      (`OBSIDIAN_VAULT_PATH` in `.env`; sandboxed to the vault,
      `.obsidian/` blocked, 100 KB per-note cap). Driver `tools` 11/11
      plus a live `chat` turn where the agent called the tool and
      answered. Next gap: NOVA can *find* notes but can't *read* one
      back yet — see Phase 10.
- [x] Fix pass (2026-07-16, driver `tools` 14/14 + live chat verified):
      `read_memory_note` tool added (NOVA now reads the notes it finds),
      `ask_ollama` default corrected to installed `mistral:latest` (was
      `gemma4:latest` — broken on fresh setups), driver now covers the
      Obsidian tools in an isolated temp vault and its latent
      `play_spotify_song` assertion was fixed, unused `livekit-plugins-groq`
      removed from requirements.txt, `offline_agent.py` .env precedence
      aligned with agent.py, SYSTEM_PROMPT now tells NOVA when to use the
      memory tools.
- [x] Course-material reader (2026-07-16, driver `tools` 17/17 + direct
      sample PDF verified): `read_course_material` extracts text from PDF,
      Markdown, and text files inside the sandboxed `course_materials/`
      folder only, supports PDF page ranges, caps output at about 15k chars,
      and keeps `.env*` blocked. Full `chat` verification was attempted but
      Gemini `gemini-3.5-flash` hit free-tier 429 quota before tool use.
- [x] Conversation Mode first pass (2026-07-16): `agent.py` now explicitly
      uses LiveKit/Gemini realtime turn handling, enables barge-in via
      `START_OF_ACTIVITY_INTERRUPTS`, shortens AEC warmup from the default
      3.0s to 0.8s, keeps the greeting interruptible, and logs conversation
      state/interruption events to `nova_tools.log` without transcript text.
      Syntax check, session-option instantiation, and driver `tools` passed;
      live barge-in verification is still pending because it needs an
      interactive console voice run.
- [x] Session conversation memory (2026-07-16): live NOVA sessions now save
      timestamped Markdown transcripts under gitignored `conversation_logs/`
      once Ahmed speaks. Filenames include the session time and a title slug
      from the first user message. New `search_conversation_history` and
      `read_conversation_history` tools let NOVA find or read earlier
      sessions, including `latest`. Driver `tools` passes 19/19 with isolated
      temp conversation logs.
- [x] Obsidian memory write path (2026-07-16, compile passed + driver
      `tools` 31/31): `save_memory_note` writes new Markdown notes under
      `<vault>/NOVA/` without overwriting, refuses obvious secrets, and live
      session transcripts are now also mirrored under
      `<vault>/NOVA/Conversations/YYYY/MM/` when `OBSIDIAN_VAULT_PATH` is
      configured. Full `chat "What time is it? Answer briefly."` succeeded
      once after the change, but the final rerun after safety hardening hit
      Gemini-side 503/504 errors after retries.
- [x] Debug pass (2026-07-16): compile check passed, driver `tools` passed
      19/19, `agent.py console` startup check passed, and `AGENTS.md` /
      `CLAUDE.md` were corrected to say NOVA now registers 29 tools.
- [x] Pylance/type-check cleanup (2026-07-16, pyright 0 errors + driver
      `tools` 19/19): the ~1k reported problems were almost all from the
      cloned `references/` study repos — now excluded from analysis in
      `.vscode/settings.json`. Real fixes: `agent.py` turn-handling dict is
      now annotated `TurnHandlingOptions` (typing only, Ahmed's tuning values
      untouched), and the driver passes a typed `no_ctx` sentinel instead of
      bare `None` to tools plus duck-types chat events. `chat` verification
      hit the known Gemini free-tier 429 daily quota again (not a code
      failure).
- [x] Desktop/file control expansion (2026-07-16, compile passed + driver
      `tools` 27/27): NOVA can now find files/folders by name in approved
      folders, open approved files/folders, create new files/folders on
      Ahmed's OneDrive Desktop without overwriting, focus/minimize/maximize/
      restore/snap windows, open notifications/quick settings, and create or
      switch Windows virtual desktops. Full `chat "What time is it? Answer
      briefly."` verification succeeded: NOVA called `get_time` and answered;
      Gemini logged retryable 504 warnings during the run but the driver
      exited successfully.
- [x] NOVA Desktop Companion dashboard first slice (2026-07-16,
      `Dashboard` typecheck/build passed + local Vite HTTP 200): added a
      React/Vite/Tailwind frontend with Orb, Mini, Compact, and Full modes,
      a typed widget registry, widget gallery, persisted layout/theme
      settings, mock NOVA service boundary, Obsidian memory widget, school
      assignments widget, model/system status widgets, and observable
      activity only. It is not yet a Tauri/always-on-top shell and is not
      connected to live NOVA events. Repo-level driver `tools` passed 31/31
      after sandbox approval; the required `chat "What time is it? Answer
      briefly."` smoke test hit repeated Gemini 504 deadline errors after
      retries.
- [x] Native desktop widget shell (2026-07-16, compile + self-test passed,
      launched with `pythonw.exe`): `Dashboard/desktop_widget.py` is now the
      actual desktop surface, not a browser app. It is a frameless,
      draggable, topmost Windows widget with Orb/Mini/Full modes, persisted
      position/mode under `%APPDATA%\NOVA`, local system/vault/tool-log/
      conversation status, and an honest "Live bridge pending" state. Driver
      `tools` passed 31/31; the final required chat smoke test hit Gemini
      503 high-demand and 504 deadline errors after retries.
- [x] NOVA Desktop Skin polish (2026-07-17, compile + unit tests +
      self-test + React checks + driver verified): `Dashboard/` now has a
      Rainmeter-style native skin layer with independent Tkinter module
      windows, WorkerW wallpaper attachment when available, monitor-relative
      persisted layout, profiles (`minimal`, `focus`, `study`, `system`),
      local non-secret status polling, a safe command bar, hotkey support,
      and optional tray hooks. Verification passed: `py_compile`,
      `python -m unittest Dashboard.test_desktop_skin` (7 tests),
      `desktop_widget.py --self-test`, `pnpm run typecheck`,
      `pnpm run build`, driver `tools` 31/31, and full
      `chat "What time is it? Answer briefly."` with a `get_time` tool call.

In progress / blocked:

- [ ] Study Mode & Quiz Mode prompt choreography (2026-07-16): `SYSTEM_PROMPT`
      now tells NOVA how to enter study mode, read course material, generate
      quiz questions through `ask_gpt56`, ask one question at a time, explain
      wrong answers, repeat missed topics, and save quiz results with
      `save_note`. End-to-end chat verification is blocked until Gemini chat
      quota and GPT-5.6/OpenAI quota are available again.
- [ ] Conversation Mode live verification: interrupt NOVA in console mode and
      confirm the current answer stops instead of finishing later. Automated
      chat verification was attempted on 2026-07-16 but Gemini
      `gemini-3.5-flash` returned 429 quota before the turn completed.
- [ ] Session memory live chat verification: a direct tool check passed, but
      `driver.py chat "What did we talk about last session?"` was blocked by
      Gemini `gemini-3.5-flash` 429 quota before the agent could call the
      history tools.
- [ ] Obsidian conversation mirror live voice verification: run `agent.py
      console`, speak one real turn, stop the session, and confirm the
      transcript appears in the Obsidian vault under `NOVA/Conversations/`.
- [ ] Desktop control live manual verification: open a real console voice
      session and test focus/snap/minimize/new desktop on visible windows.
      The driver covers registration and safety guards but intentionally does
      not move Ahmed's live windows during automated verification.
- [ ] Desktop Companion live bridge: stream safe NOVA status/tool/task/memory
      events into the native desktop skin and/or the React command center.
      The local desktop skin exists and is verified; the live agent bridge is
      still pending.

## NOVA Core 1.0 priority order (added 2026-07-16)

This is the stability roadmap from Ahmed's attached design notes. Use it to
decide what to build after the Build Week study demo path is usable.

1. Conversation experience first: fix delayed/queued replies, interruption
   handling, barge-in, response cancellation, and one-active-response-at-a-time
   behavior before adding more autonomous features.
2. Model router: route simple desktop commands locally, private knowledge
   through Obsidian, complex coding/research through specialists, and offline
   requests through Ollama instead of sending everything to one model.
3. Offline fallback: build a real local voice path
   wake phrase -> local STT -> Ollama -> local TTS -> local tools.
4. Memory architecture: separate working, personal, project, and event memory;
   retrieve only relevant notes instead of injecting large history.
5. Task system: represent requests as cancellable tasks with status, result,
   error, priority, and confirmation requirements.
6. Standby notifications: keep lightweight local monitors running without the
   full realtime voice model; speak only important alerts.
7. Permission levels: classify tools as safe, reversible, sensitive, or
   destructive/external, and require confirmation for risky actions.
8. Tool reliability contract: move toward structured tool results with success,
   message, data, error_code, and retryable fields.
9. Desktop dashboard: show online/offline/standby state, active model, current
   task, mic/network status, CPU/RAM, notifications, and recent tool activity.
10. Measurement: track recognition latency, first response time, interruption
    reaction time, false interruptions, tool success, RAM, offline response
    time, and stale queued responses.

Multi-agent rule: keep NOVA as the only coordinator that talks to Ahmed.
Specialists should be narrow workers (coding, memory, desktop; later research)
with strict permissions, timeouts, and structured results. Do not add many
independent autonomous agents before task management and permissions exist.

## Phase 1 — Stabilize & secure ✅ DONE 2026-07-09

- [x] `git init` + `.gitignore` + first commit
- [x] `open_app` whitelisted — raw model input never reaches a shell
- [x] File tools sandboxed to approved folders; `.env*` always blocked
- [x] `notes.txt` absolute path next to agent.py
- [x] `Google_API_Key` → `GOOGLE_API_KEY` in `.env`
- [x] Deps trimmed (mem0ai, langchain-community out; DuckDuckGo called
      directly; spotipy added)
- [x] Tool call + error logging to `nova_tools.log`
- [x] Driver extended with security-regression checks (12 checks)

## Phase 2 — Tool structure ✅ DONE 2026-07-11

`tools.py` split into modules (final layout differs slightly from the plan):

```
tools/
  __init__.py  common.py  desktop.py  files.py
  information.py  media.py  models.py  vision.py
```

One tool = one small function with error handling. Driver checks updated
2026-07-11 to match the refactored messages.

## Phase 3 — Desktop control (core done 2026-07-11)

- [x] Close app / restart app (approved-list only)
- [x] Check if an app is running (exact process-name match)
- [x] Focus / minimize / maximize / restore / snap visible windows
- [x] Open Windows notifications and quick settings
- [x] Create/switch virtual desktops and show task view/desktop
- [ ] Wait for app to open
- [ ] All destructive actions ask Ahmed first

## Phase 4 — Spotify / media ✅ core DONE 2026-07-09

Verified end-to-end: Spotify API credentials in `.env`, OAuth login cached
(`.spotify_cache`), `play_spotify_song` opened Spotify, started a real
track on this laptop, `get_current_song` read it back, media keys paused.
Media-key controls + volume + current-song work with no API at all.
Fixed `is_app_running` to exact process-name matching (the SpotifyLauncher
background stub was being counted as the real app).

Remaining (later):
- [ ] Play playlist / album; queue song
- [ ] Search accuracy: test query for one song returned a different track —
      consider `market="from_token"` or smarter query building

## Phase 5 — Custom NOVA website (parked)

A working v1 was built and verified 2026-07-09 (passcode gate, token route
dispatching `my-agent`, orb + live transcript + controls + tool panel),
then removed the same day — Ahmed didn't want it yet. The complete code is
preserved in git commit `fea9a3f`; restore anytime with:
`git checkout fea9a3f -- website` (then `pnpm -C website install`).

When revisited, remaining work was: agent-side `nova.tools` events for the
tool panel, settings panel, Vercel deploy for phone access.

## Phase 6 — Standby / always-on & phone access

1. Website standby first: stay connected while the site is open; mute/unmute,
   camera on/off, manual standby button.
2. Desktop standby: background process + tray icon, wake word
   "NOVA"/"Hey NOVA" (reuse the old Nova repo's vosk wake-word listener),
   connects to LiveKit only when activated, sleeps after silence, can be
   fully disabled. Retire the old repo's listener when this lands (one mic
   owner only).
3. Phone access — talk to NOVA from Ahmed's phone. LiveKit Cloud is already
   device-agnostic: redeploy the parked website (Phase 5, commit `fea9a3f`)
   to Vercel and open it on the phone, or use the LiveKit playground as a
   stopgap. Needs mic permission in the mobile browser and dispatch of
   worker `my-agent`.

## Phase 7 — Canvas / school

Port from `nova/integrations.py` in the old repo (working code exists):

- [ ] Assignments due today / this week / next assignment
- [ ] Class schedule, study planner, assignment + exam reminders

## Phase 8 — Email & calendar

Port Outlook (Graph device flow) from the old repo, or add Gmail:

- [ ] Summarize unread, search, draft, reply-draft
- [ ] Calendar summary, create event
- Safety: NOVA never sends an email without explicit confirmation.

## Phase 9 — Screen understanding (started)

- [x] `capture_screen` — saves an all-screens PNG to `screenshots/`
- [x] Build Week path: `analyze_screen_with_gpt56` captures a screenshot and
      sends it to GPT-5.6 only after explicit screen-share confirmation.
- [ ] **Next recommended step:** add local redaction or OCR preview before
      cloud screen analysis.
- [ ] Read visible errors, explain code on screen, OCR, read PDFs/images

## Phase 10 — Memory (started 2026-07-15)

- [x] `search_memory` — searches Ahmed's Obsidian vault by name + content
      (verified end-to-end 2026-07-15; see Current status)
- [x] `read_memory_note` — reads back a note that `search_memory` found
      (added + verified end-to-end 2026-07-16)
- [x] Session conversation memory — timestamped local Markdown logs plus
      `search_conversation_history` / `read_conversation_history`; live
      sessions also mirror to `NOVA/Conversations/` in the Obsidian vault
      when configured.
- [x] Memory write path — `save_memory_note` creates new Markdown notes under
      `<vault>/NOVA/`, never overwrites, and refuses obvious secrets.
- [ ] **Next recommended step:** add memory cleanup/indexing: duplicate note
      detection, stale-memory review, and dashboard-friendly memory metadata.
- [ ] Longer term: preferences, project details, coding style, workflows,
      school schedule, favorite apps, NOVA settings.
      Never store passwords, API keys, tokens, or sensitive data unless asked.

## Phase 11 — Mission mode

"NOVA, help me finish my assignment" / "start coding mode" / "morning
briefing" → create a plan, use tools, track progress, ask before risky
actions, summarize what was done.

## Phase 12 — Study Mode & Quiz Mode (NOVA the teacher)

Ahmed drops course material from his professors (PDFs, slides, notes) into
a sandboxed course-materials folder (or the Obsidian vault), then:

- [ ] "Study mode: <subject>" — prompt choreography added 2026-07-16; final
      end-to-end chat verification is still blocked by API quota.
- [ ] "Quiz mode: <subject>" — prompt choreography added 2026-07-16; NOVA is
      instructed to generate questions with `ask_gpt56`, ask one at a time,
      explain mistakes, repeat missed topics, and save results with
      `save_note`. Final end-to-end chat verification is still blocked by API
      quota.
- [ ] Track weak topics across sessions with `save_memory_note` under the
      Obsidian `NOVA/` folder.
- [x] PDF/text extraction and sandboxed course folder:
      `read_course_material` reads PDFs, Markdown, and text from
      `course_materials/` only, with PDF page ranges and a 15k output cap.
      Slide-native parsing remains future work; export slides to PDF for now.
- [ ] **Next recommended step:** rerun `driver.py chat "Quiz mode..."` after
      Gemini and GPT-5.6 quotas reset; then tighten the prompt based on the
      observed tool sequence.
- [ ] Whiteboard/photo → notes: point NOVA at a photo (whiteboard, slide,
      textbook page) and it extracts structured notes into the vault —
      cheap to build, `run_gpt56_with_image` already exists in
      tools/models.py, just needs a sandboxed image-path tool

## Phase 13 — Lecture Mode (listen, record, take notes)

In class, NOVA listens to the lecture from the phone or the laptop:

- [ ] Record the lecture audio to a local file for later
- [ ] Transcribe the lecture (live if possible, after class at minimum)
- [ ] After class: structured notes (topics, definitions, examples,
      follow-ups) saved into the Obsidian vault / course folder
- [ ] "Explain what I missed" — analyze the transcript and teach it
      (the notes feed straight into Phase 12's study material)
- Note: check the school's recording policy / ask the professor before
  recording a lecture.

## Phase 14 — Voice recognition (NOVA knows Ahmed's voice)

- [ ] Speaker recognition: NOVA recognizes that it's *Ahmed* talking —
      enroll his voice once, then match new audio against a locally stored
      voice embedding (e.g. resemblyzer or SpeechBrain, fully local)
- [ ] Use it for personalization + safety: greet Ahmed by name; sensitive
      tools only respond to Ahmed's voice
- Reality check: with Gemini Realtime the mic audio streams straight
  through LiveKit, so speaker ID most naturally lives in the standby
  wake-word listener (Phase 6), which decides whether to wake NOVA at all.

## Phase 15 — Desktop HUD widget (NOVA's face)

A small always-on-top window on the desktop, linked live to the agent:
orb with states (idle / listening / thinking / speaking), live transcript,
and a feed of tool calls as they happen.

- [x] First frontend slice exists in `Dashboard/` (2026-07-16): React/Vite
      dashboard with Orb, Mini, Compact, and Full Command Center modes,
      typed widget registry, widget gallery, persisted widget settings,
      mock `NovaClient`, memory/school/status widgets, command palette, and
      reduced-motion support.
- [x] Native desktop shell exists in `Dashboard/desktop_widget.py`
      (2026-07-16): no browser or dev server required. It launches through
      `Dashboard/start_desktop_widget.ps1`, runs with `pythonw.exe`, stays
      frameless/topmost, can be dragged around the desktop, and has
      Orb/Mini/Full modes.
- [x] Native Rainmeter-style skin layer exists (2026-07-17): independent
      Tkinter skin module windows attach to the desktop wallpaper host when
      Windows exposes WorkerW, persist monitor-relative layout under
      `%APPDATA%\NOVA`, support `minimal`/`focus`/`study`/`system` profiles,
      and expose only safe local commands from the desktop command bar.
- [ ] Agent side: publish safe status/tool/task/memory events through a real
      HTTP/WebSocket bridge so the native skin and
      `Dashboard/src/novaClient.ts` can replace their local/mock status.
- [ ] Desktop polish: finish tray/startup behavior on clean installs,
      minimize-to-tray, multi-monitor placement testing, and live state
      animations once the bridge exists.

- Historical reference: the parked website (Phase 5, commit `fea9a3f`) still
  has useful LiveKit transcript/tool-panel patterns, but the current primary
  desktop path is `Dashboard/desktop_widget.py` plus the native skin modules.
- Why it matters: it gives the demo a face — judges can *see* the agentic
  work that is otherwise invisible voice.

## Phase 16 — Reminders & focus mode

- [ ] Spoken reminders: "remind me to stretch in 20 minutes" → NOVA speaks
      up when it fires (needs a background task that can trigger speech in
      the live session — demo gold when one fires live)
- [ ] Focus / pomodoro mode: study timer with spoken breaks; optionally
      closes distracting approved apps (uses existing `close_app`)
- [ ] Daily auto-journal: NOVA writes a short daily note into the vault
      about what was done/asked (builds on the Phase 10 write path)

## Phase 17 — Offline mode (NOVA without internet)

Today, no internet = no voice: Gemini Realtime, GPT-5.6, Groq, weather, and
search are all cloud. What already survives offline: `offline_agent.py`
(text chat through local Ollama) and all local tools.

- [x] Text-only offline chat via Ollama (`offline_agent.py` exists)
- [ ] Offline voice loop: faster-whisper (local STT) → Ollama (local LLM)
      → Piper or Windows neural voices (local TTS). Slower and simpler
      than Gemini, but it talks with the wifi off.
- [ ] Auto-fallback: when Gemini is unreachable, NOVA says so and offers
      offline mode instead of dying silently (the unused `core/` router
      was designed for exactly this split — wire it here)
- Demo angle: kill the wifi live and NOVA keeps answering.
- Custom/cloned NOVA voice (Ahmed's voice-training idea): not possible
  inside Gemini Realtime (fixed voices); only worth doing as part of THIS
  phase's local TTS, and only ever clone your own voice.

## Idea backlog (not scheduled — Ahmed's brainstorm list)

- Presentation coach: rehearse a class presentation out loud; NOVA times
  it, flags filler words/unclear parts, then asks the questions a professor
  would ask (reuses quiz-mode machinery).
- Mock interview mode: paste a job/internship posting; GPT-5.6 generates
  interviewer questions, NOVA plays the interviewer by voice and grades
  answers.
- Brain-dump mode: think out loud, messy; NOVA turns it into a structured
  outline/note in the vault.
- "Where did I put it": tell NOVA where things are ("charger is in my
  backpack's front pocket"); it recalls later (memory write + search).
- Self-improvement pipeline (SAFE version only): NOVA drafts code for a new
  tool it wishes it had into a `proposals/` folder — never touches its own
  live code; Ahmed reviews, the driver tests, then it gets merged by hand.
  NOVA must never edit agent.py/tools/ on its own.

## Update rule

When Ahmed says a feature is done:

1. Move it to Current status with the date.
2. Note any bugs found.
3. Add the next recommended step.
4. Update the "Last updated" date here and in `CLAUDE.md` if the stack or
   rules changed.
