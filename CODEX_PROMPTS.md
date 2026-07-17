# Codex Prompts for NOVA (this repo — LiveKit + Gemini Realtime)

_Created 2026-07-15, adapted from Ahmed's `nova-codex-kit.zip`._

> **Warning about the kit:** the zip's `AGENTS.md` and skills describe the
> OLD Flask Nova (`nova.py`, Vosk, Piper, HUD orb, SQLite). None of that
> exists in this repo. Do NOT copy the kit's AGENTS.md here — this repo's
> `AGENTS.md` is already correct. What survives from the kit is the prompt
> format, the golden rules, and the demo advice, all adapted below.

Every prompt follows **Goal / Context / Constraints / Done when**.
Paste ONE prompt per Codex session. Codex must read `AGENTS.md` first and
follow its "After EVERY completed task" section (update `ROADMAP.md` +
`HACKATHON_LOG.md`, run the driver, report honestly).

## Golden rules

1. One task = one Codex session. Session goes sideways → start FRESH with a
   cleaner prompt instead of arguing with it.
2. The driver defines "done": `driver.py tools` + one `chat` must pass.
   Never let Codex edit the driver checks just to make them pass.
3. Same mistake twice → add a rule to `AGENTS.md`.
4. Review every diff before accepting. Run it yourself, every time.
5. Anything destructive or that sends data off the machine → NOVA asks Ahmed
   first. No exceptions, even under demo time pressure.

## How to verify (this repo's commands)

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "..."
& ".\venv\Scripts\python.exe" agent.py console   # live voice (speaks aloud)
```

---

## Task board (build order — check off as they land)

**Core — the winning demo. Build in this order:**

- [x] 1. Read a memory note back (DONE 2026-07-16, Claude)
- [x] 2. Course materials — PDF text extraction (DONE 2026-07-16, Codex)
- [ ] 3. Study Mode & Quiz Mode ← prompt rules added 2026-07-16; final chat
      verification blocked by Gemini/OpenAI quota
- [x] 3b. Memory write path ("remember this") (DONE 2026-07-16, Codex)
- [ ] 3c. Exam-prep briefing chain
- [x] 3d. Session conversation memory (DONE 2026-07-16, Codex)
- [x] 3e. File pull-up + Desktop/window control (DONE 2026-07-16, Codex)
- [ ] 4. Lecture Mode
- [ ] 8. Demo hardening (always LAST)

**Extras — only after the core works:**

- [ ] 2b. Whiteboard/photo → notes
- [ ] 4b. Spoken reminders
- [ ] 5. Phone access
- [ ] 5b. Desktop HUD widget <- dashboard experiments are parked locally and
      `Dashboard/` is gitignored until Ahmed chooses the right design
- [ ] 6. Standby + wake word
- [ ] 7. Voice recognition
- [ ] 7b. Offline voice mode (make Ollama talk)

**Backlog — post-hackathon unless time is left over:**

- [ ] A1. Conversation controller (queued replies + interruption handling) ←
      first runtime turn-handling pass added 2026-07-16; live console
      interruption verification still pending
- [ ] A2. Model router + specialist registry
- [ ] A3. Offline fallback architecture
- [ ] A4. Task manager + permission levels
- [ ] B1. Presentation coach
- [ ] B2. Mock interview mode
- [ ] B3. Brain-dump → outline
- [ ] B4. "Where did I put it"

Rule for Codex: when Ahmed says "do prompt N", read this file, execute that
prompt exactly, check it off here, and follow AGENTS.md's
"After EVERY completed task" section.

---

## 1. Read a memory note back — ✅ DONE 2026-07-16 (by Claude; skip this one)

Goal: Expose a `read_memory_note` function tool so NOVA can read back a note
that `search_memory` found.
Context: @tools/obsidian.py already has `read_obsidian_note` and the safety
helpers (`resolve_obsidian_note` blocks paths outside the vault and
`.obsidian/`). Follow the `search_memory` pattern in the same file.
Constraints: Reuse the existing helpers — no new path logic. Graceful error
strings, never a stack trace to the user. Register in @tools/__init__.py and
@agent.py. Add a driver check that patches OBSIDIAN_VAULT_PATH to a temp
vault (mirror how the driver isolates NOTES_PATH). No new packages.
Done when: driver `tools` passes with the new check, and one `chat` turn can
search for a note and read its contents back.

## 2. Course materials — PDF/slide text extraction — DONE 2026-07-16 (Codex)

Goal: Add a `read_course_material` tool that extracts text from a PDF (and
.txt/.md) inside a sandboxed `course_materials/` folder.
Context: @tools/files.py for the sandbox pattern (`_resolve_safe_path` in
@tools/common.py), Phase 12 in @ROADMAP.md.
Constraints: `pypdf` is the one allowed new dependency — add it to
requirements.txt and say so in the summary. Cap extracted text (e.g. first
~15k chars per call with a page-range parameter). Sandbox: only
`course_materials/` under the project root; `.env*` stays blocked.
Done when: driver `tools` passes, and a `chat` turn reads a sample PDF from
`course_materials/` and summarizes it.

## 3. Study Mode & Quiz Mode (hackathon centerpiece) — PROMPT RULES ADDED 2026-07-16

Status: SYSTEM_PROMPT now defines Study Mode and Quiz Mode choreography.
Final done check is still blocked because `driver.py chat` hit Gemini
`gemini-3.5-flash` quota before tool execution, and direct `ask_gpt56`
returned rate-limited/out-of-credits.

Goal: Teach NOVA "study mode" and "quiz mode" for a subject whose materials
are in `course_materials/`.
Context: @prompts.py (SYSTEM_PROMPT), the tools from prompts 1–2, `ask_gpt56`
in @tools/models.py, Phase 12 in @ROADMAP.md.
Constraints: Behavior lives in SYSTEM_PROMPT rules + existing tools — no new
frameworks. Quiz questions are generated with `ask_gpt56` from the extracted
material (this is what makes GPT-5.6 central for Build Week). Quiz flow: ask
one question at a time out loud, check the answer, explain mistakes, repeat
missed questions. Save quiz results/weak topics with `save_note`.
Done when: In a `chat` session, "quiz me on <subject>" produces material-
based questions, wrong answers get explained, and results are saved. Driver
passes.

## 2b. Whiteboard/photo → notes (cheap + insane)

Goal: An `analyze_image_with_gpt56` tool: give NOVA a photo (whiteboard,
slide, textbook page) and it extracts structured notes.
Context: @tools/models.py already has `run_gpt56_with_image` (used by screen
analysis) and @tools/common.py has `resolve_safe_path`. Phase 12 in
@ROADMAP.md.
Constraints: Image path must pass the sandbox; ask for confirmation before
sending the image to OpenAI (same consent pattern as
analyze_screen_with_gpt56).
PNG/JPG only, size-capped. No new packages.
Done when: A photo of handwritten notes in Pictures/ comes back as clean
structured notes in a chat turn, and the driver passes.

## 3b. Memory write path ("NOVA, remember this") — DONE 2026-07-16 (Codex)

Goal: A `save_memory_note` tool so NOVA can write new notes into a `NOVA/`
folder inside the Obsidian vault.
Context: @tools/obsidian.py — follow the `search_memory`/`read_memory_note`
pattern and reuse `get_obsidian_vault_path`. Phase 10 in @ROADMAP.md.
Constraints: Writes ONLY inside `<vault>/NOVA/`; never overwrite an existing
note (append a timestamp suffix instead); sanitize the note name; never
store passwords/keys/tokens. Add a driver check using the temp vault that
already exists in the driver.
Done when: "Remember that my exam is Friday" creates a note under NOVA/,
`search_memory` finds it, driver `tools` passes with the new check.

Result: `save_memory_note` is registered, writes only under `<vault>/NOVA/`,
refuses obvious secrets, and driver `tools` passes 31/31 with isolated temp
vault checks. Live conversation transcripts are also mirrored into
`<vault>/NOVA/Conversations/YYYY/MM/` when `OBSIDIAN_VAULT_PATH` is
configured.

## 3c. Exam-prep briefing (agentic chain — demo gold)

Goal: One spoken command ("prep me for my exam" / "morning briefing") makes
NOVA chain tools: check the time, search memory for the exam + weak topics,
read the relevant note, and offer a quick review or quiz.
Context: @prompts.py — this is mostly SYSTEM_PROMPT choreography over
existing tools (get_time, search_memory, read_memory_note, ask_gpt56).
Constraints: No new tools. The chain must degrade gracefully if a note is
missing. Keep spoken output short — a briefing, not a lecture.
Done when: One `chat` command visibly triggers 3+ tool calls and ends with
a spoken summary plus an offer to quiz.

## 3d. Session conversation memory — DONE 2026-07-16 (Codex)

Goal: Save each live NOVA session as a timestamped local Markdown transcript
with a fitting title, then let NOVA search/read those logs in later sessions.
Context: @agent.py session events and @tools/conversations.py.
Constraints: Local only, gitignored, no secrets handling changes, no cloud
summary call, no transcript text in `nova_tools.log`.
Done when: Driver `tools` creates an isolated temp conversation log, searches
it, reads `latest`, and passes.

## 3e. File pull-up + Desktop/window control — DONE 2026-07-16 (Codex)

Goal: Let NOVA pull up files/folders Ahmed asks for, create new files/folders
on the correct OneDrive Desktop location, and control visible Windows windows
and virtual desktops.
Context: @tools/files.py, @tools/desktop.py, @agent.py, @prompts.py.
Constraints: Keep file access sandboxed to approved folders, never overwrite
Desktop files/folders, keep destructive actions out of scope, and do not move
live windows during automated driver checks.
Done when: `find_user_file`, `open_file_or_folder`, `create_desktop_file`,
`create_desktop_folder`, `control_window`, `open_notifications`,
`open_quick_settings`, and `manage_virtual_desktop` are registered in NOVA,
driver `tools` passes with isolated temp-Desktop checks, and the docs/logs are
updated.

## 4. Lecture Mode — record + transcribe + notes

Goal: A `lecture_recorder.py` script (separate from the agent) that records
lecture audio locally, transcribes it, and writes structured notes.
Context: Phase 13 in @ROADMAP.md. The venv already has audio deps from
LiveKit; check before adding anything.
Constraints: Recording is started/stopped manually by Ahmed (a console
script is fine for v1). Audio + transcript + notes are saved locally under
`lectures/` (gitignored). Transcription may use the OpenAI API (key already
in `.env`) — never auto-upload without Ahmed running the script himself.
Notes format: topics, definitions, examples, follow-up questions, saved as
Markdown so it feeds study mode. Remind Ahmed in the README section to get
permission before recording a lecture.
Done when: A short test recording produces an audio file, a transcript, and
a structured notes file; nothing crashes when the mic yields silence.

## 4b. Spoken reminders (a reminder firing live = demo gold)

Goal: A `set_reminder` tool; when a reminder is due mid-session, NOVA says
it out loud.
Context: @agent.py — the AgentSession object; reminders can be an asyncio
background task that calls `session.generate_reply(...)` when due. Phase 16
in @ROADMAP.md.
Constraints: In-memory + a JSON file for persistence (project root,
gitignored). Reminders only fire while a session is running (v1 limit — say
so honestly). Validate durations; cap at 24h. No new packages.
Done when: "Remind me to stretch in 1 minute" is confirmed, and one minute
later NOVA speaks the reminder unprompted in console mode.

## 5. Phone access (talk to NOVA from the phone)

Goal: Ahmed can talk to NOVA from his phone.
Context: Phase 6.3 in @ROADMAP.md. A working website exists in git commit
`fea9a3f` (restore: `git checkout fea9a3f -- website`). LiveKit Cloud
already handles any device; dev mode registers worker `my-agent` and needs
explicit dispatch.
Constraints: Do not touch agent.py behavior. Smallest path first: restore
the parked website, verify locally, then deploy to Vercel. Passcode gate
stays. No secrets in the frontend.
Done when: NOVA answers by voice in the phone's browser over LiveKit Cloud.

## 5b. Desktop HUD widget (NOVA's face on screen)

Status: dashboard/HUD experiments are parked locally and `Dashboard/` is
gitignored until Ahmed chooses the right design. Do not assume a tracked
dashboard implementation exists in a fresh clone. The older parked-website
note below is historical reference for possible LiveKit transcript/tool-panel
patterns.

Goal: A small always-on-top desktop widget showing NOVA's orb state
(idle/listening/thinking/speaking), live transcript, and tool calls.
Context: Phase 15 in @ROADMAP.md. Review Ahmed's chosen design file first.
The parked website in git commit `fea9a3f` can still be used as a reference
for orb + live transcript + controls + tool panel patterns.
Constraints: Do not push a dashboard until the design direction is approved.
Agent side: publish tool-call events into the LiveKit room or a local bridge
so the panel updates live. Do not change tool behavior, only add event
publishing.
Done when: The widget sits on the desktop, the orb reacts to talking, and
tool calls appear in it as NOVA uses them.

## 6. Desktop standby + wake word ("Hey NOVA")

Goal: A lightweight standby listener that wakes NOVA on "NOVA"/"Hey NOVA".
Context: Phase 6.2 in @ROADMAP.md. The OLD repo
(`C:\Users\ahmed\OneDrive\Desktop\Nova`) has a working vosk wake-word
listener to reuse. Never run both listeners at once.
Constraints: Standby process owns the mic only while NOVA is asleep; hands
off cleanly when a session starts. Tray icon or console status is fine for
v1. Must be fully disableable.
Done when: Saying the wake word starts a NOVA session; silence returns it
to standby; the old repo's listener stays off.

## 7. Voice recognition (NOVA knows Ahmed's voice)

Goal: The standby listener only wakes for Ahmed's voice.
Context: Phase 14 in @ROADMAP.md; builds on prompt 6's listener.
Constraints: Fully local (resemblyzer or SpeechBrain embedding match).
One-time enrollment script; embedding stored locally, gitignored. On a
non-match, stay asleep — never send the audio anywhere.
Done when: Ahmed's voice wakes NOVA; a YouTube voice / another person does
not; enrollment can be redone.

## 7b. Offline voice mode (make Ollama talk)

Goal: Give `offline_agent.py` a voice, in stages that each work alone.
Context: @offline_agent.py (working text loop via `run_ollama`), Phase 17
in @ROADMAP.md. The old nova-codex-kit's voice-pipeline notes
(faster-whisper + Piper) apply HERE, not to the main Gemini agent.
Constraints: Stage 1 first: speak replies with Windows built-in speech
(System.Speech via pythonnet-free route or pyttsx3 — prefer zero/minimal
new packages) while keeping keyboard input. Stage 2: mic input with
faster-whisper ("base", compute_type="int8") + sounddevice — these two new
packages are approved for this task; record → transcribe → Ollama → speak.
Everything must run with wifi OFF. Never touch agent.py or the Gemini
pipeline. Errors recover to the prompt loop, never crash.
Done when: With wifi disabled, a spoken question gets a spoken answer from
local Ollama, and Ctrl+C exits cleanly.

## 8. Demo hardening (LAST, before submission)

Goal: NOVA cannot crash during a 5-minute live demo.
Context: Whole repo, especially every tool in @tools/.
Constraints: Every tool already returns error strings — verify none can
raise instead. Add a startup self-check (env keys present, vault path
resolves, mic available) printing a green checklist. No behavior changes.
Done when: Killing the network mid-question, gibberish input, and talking
over NOVA all fail gracefully; the self-check passes clean.

---

## A1. Conversation controller (queued replies + interruption handling)

Status: first runtime pass added 2026-07-16. `agent.py` now explicitly uses
Gemini realtime turn detection, enables start-of-activity interruption,
shortens AEC warmup to 0.8s, keeps generated speech interruptible, and logs
conversation state/interruption events. Driver `tools` passes and the
AgentSession options instantiate, but final done still requires live console
barge-in verification.

Goal: Make NOVA feel reliable by preventing delayed queued replies and making
interruptions cancel the current response instead of stacking old answers.
Context: @agent.py and LiveKit session behavior. The attached design notes say
conversation stability must come before more agents, standby alerts, or speaker
recognition.
Constraints: Do not change Ahmed's Gemini realtime model, voice, VAD tuning,
or `video_input=False` without asking. Prefer LiveKit-native turn-taking,
barge-in, cancellation, and session hooks before inventing a parallel voice
pipeline. No new packages unless a LiveKit feature already requires one.
Done when: In console mode, interrupting NOVA stops the current answer,
old answers are not spoken after a newer request, and the driver still passes.

## A2. Model router + specialist registry

Goal: Centralize request routing so NOVA chooses the right path: local tool,
Obsidian memory, GPT-5.6, Groq, Ollama, or Gemini realtime.
Context: @core/ already contains router/orchestrator scaffolding that is not
imported yet. @tools/models.py already has `ask_gpt56`, `ask_groq`, and
`ask_ollama`.
Constraints: NOVA remains the only assistant that speaks to Ahmed. Specialists
must be narrow workers with explicit permissions, timeouts, and structured
results. No autonomous agent loops; cap handoffs and retries.
Done when: A routing layer can classify representative requests without
changing existing tool behavior, and the driver passes.

## A3. Offline fallback architecture

Goal: NOVA can degrade honestly when the internet is unavailable and route to
local Ollama/offline tools where possible.
Context: @offline_agent.py already provides a text-only Ollama loop, and Phase
17 tracks offline mode.
Constraints: Do not replace the Gemini Live pipeline. Start with reliable
mode detection and text fallback before adding microphone STT or TTS. Use
smaller local models for normal offline commands; avoid keeping huge models
loaded in standby.
Done when: NOVA can detect cloud unavailability, say it is switching/offering
offline mode, run a local Ollama text fallback, and keep local tools usable.

## A4. Task manager + permission levels

Goal: Represent user requests and tool actions as cancellable tasks with clear
status, confirmation requirements, and logs.
Context: The attached design notes define safe, reversible, sensitive, and
destructive/external permission levels.
Constraints: Do not give autonomous permission to delete files, send emails,
install software, push code, change credentials, or reveal private notes.
Destructive/external actions still require explicit confirmation even after
speaker recognition exists.
Done when: Tasks have IDs, status, result/error fields, cancellation state,
and permission level; tool execution can report what happened without
breaking existing tools.

## B1. Presentation coach

Goal: "Presentation mode" — Ahmed rehearses a class presentation out loud;
NOVA times it, flags filler words and unclear parts, then asks the
questions a professor would ask.
Context: @prompts.py choreography over the live transcript + `ask_gpt56`
for feedback and audience questions. Reuses quiz-mode habits from prompt 3.
Constraints: v1 is SYSTEM_PROMPT behavior only — no new tools. Feedback
must be short and specific. Save the feedback with `save_note` (or the
vault write path once 3b is done).
Done when: A 1-minute rehearsal in console mode gets timing, 2–3 concrete
feedback points, and 3 audience questions.

## B2. Mock interview mode

Goal: NOVA plays interviewer for an internship/job posting and grades
Ahmed's spoken answers.
Context: `read_file` for the posting text, `ask_gpt56` to generate and
grade questions, quiz-mode flow from prompt 3.
Constraints: One question at a time, by voice. Grade at the end with
strengths + weaknesses, and save the results as a note. No new packages.
Done when: A chat session runs a 3-question mock interview from a posting
file in Documents and ends with graded feedback.

## B3. Brain-dump → outline

Goal: Ahmed thinks out loud in a mess; NOVA turns it into a structured
outline note in the vault.
Context: Requires prompt 3b (vault write path) first. `ask_gpt56`
structures the dump into: goal, main points, open questions, next steps.
Constraints: Never overwrite an existing note; outline saved under
`NOVA/` in the vault so `search_memory` finds it later.
Done when: A rambling paragraph becomes a clean saved outline that
`search_memory` can find by topic.

## B4. "Where did I put it"

Goal: NOVA remembers where Ahmed puts things and recalls on demand.
Context: Requires prompt 3b. Item locations stored as tiny notes under
`NOVA/Items/` in the vault; recall goes through `search_memory` +
`read_memory_note`.
Constraints: Update = new timestamped note (never overwrite); answer with
the most recent location. No new tools beyond 3b's writer if avoidable.
Done when: "My charger is in my backpack's front pocket" followed later by
"where is my charger?" answers correctly in a chat session.

---

## Demo & judging (from the kit — still true)

- Judges score roughly: working demo > wow factor > technical depth >
  polish > idea.
- Rehearse a 3-minute script 10+ times. Strong flow for THIS NOVA: wake it
  by voice → ask it to search your Obsidian memory → quiz mode on a real
  course PDF → it explains a wrong answer → end on the fast voice latency.
- Record a full backup demo video in case the venue mic/wifi fails; test in
  a noisy room; consider a directional mic.
- Lead with the live voice interaction, not slides. Your story: "My personal
  Jarvis: it knows my notes, quizzes me for exams with GPT-5.6, and talks
  back in under two seconds."
