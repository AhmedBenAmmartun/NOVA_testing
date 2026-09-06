# DEVELOPMENT.md — NOVA (LiveKit)

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
                    video_input=False (Ahmed turned it off), greeting
prompts.py          SYSTEM_PROMPT (NOVA persona)
nova_os/            capability kernel: catalog.py registers 12 capabilities
                    over ~69 tools; capabilities.py owns CapabilityRegistry +
                    CapabilityManager.build_tool_context() (the ONLY tool
                    surface agent.py consumes); skills.py the skill registry
nova_core/          model routing: router.py + configuration.py +
                    provider_registry.py + cloud_budget.py. fallback_order is
                    env-driven; providers/ holds the concrete adapters
nova_policy/        permission engine (capability != permission)
nova_capture/       Class Capture runtime (see its own section below)
nova_school/        course registry, path authority, material context,
                    vocabulary, corrections.py (Ahmed's STT ground truth)
nova_knowledge/     course-material extraction + local retrieval index
nova_learning/      experience capture: schema/store/evaluator/instrument.
                    Wired into agent.py via LearningSessionRecorder
nova_runtime/       job + task-state foundation (BackgroundJobManager,
                    TaskSnapshot, JobState, EventBus).
                    NOT wired into agent.py -- only nova_school/automation.py
                    and cli.py consume it. See ROADMAP before extending
nova_lab/           internal development lifecycle primitives: feature state,
                    recoverable lifecycle journal, constrained Git worktrees,
                    allow-listed test profiles, and (V1B) service.py, the
                    safe bridge the model-facing `development` capability
                    calls into. Not a user-facing mode and not wired to
                    production promotion/restart.
nova_guardian/      guardian subsystem
nova_integrations/  email/calendar + secrets
tools/              ~80 @function_tool definitions across 15 modules;
                    capabilities.py, class_capture.py, conversations.py,
                    desktop.py, email_calendar.py, files.py, guardian.py,
                    information.py, media.py, models.py, obsidian.py,
                    permissions.py, skills.py, specialist.py, web.py.
                    common.py holds the sandbox/logging helpers and
                    vision.py the screen capture (neither exports tools).
                    Registration happens in nova_os/catalog.py, NOT here --
                    the decorator count and the live count differ
requirements.txt    deps (venv\ is the provisioned Python 3.14 venv; pypdf
                    powers course-material PDF extraction)
.env                secrets: LIVEKIT_URL/API_KEY/API_SECRET, GOOGLE_API_KEY,
                    OPENAI_API_KEY, SPOTIFY_CLIENT_ID/SECRET, GROQ_API_KEY,
                    OBSIDIAN_VAULT_PATH (path to the Obsidian vault)
.agents/skills/run-ai-agent/   run skill + driver.py test harness
```

## NOVA Lab (internal development lifecycle, V1A + V1B — LAB checkpoint)

NOVA Lab is not a separate NOVA mode/persona. It is the internal lifecycle used
to isolate experimental implementations from ACTIVE production behavior.
"development" is a capability of the one NOVA agent, not a separate agent.

`LAB -> CANDIDATE -> ACTIVE -> RETIRED`

V1A contains only lifecycle state, an append-only/recoverable audit journal,
constrained Git worktree creation, and named pytest profiles. Runtime state
defaults to `%LOCALAPPDATA%\NOVA\Lab\`; managed worktrees must stay under
`C:\Projects\NOVA-Labs\` and use `lab/*` branches. Promotion, retirement
of ACTIVE code, restart, rollback, arbitrary shell, and direct production edits
are deliberately absent. Future sensitive release operations must reuse
`nova_policy` and trusted user approval rather than create a second authority
system.

V1B (2026-09-05) adds the first model-facing surface: an inactive-by-default
(`default_active=False`) `development` NOVA OS capability
(`nova_os/catalog.py`) with exactly five tools (`tools/development.py`):
`lab_status`, `list_lab_features`, `get_lab_feature`,
`list_lab_test_profiles`, `register_lab_feature`. All five are
inspection/registration-metadata only — no test execution, lifecycle
transition, promotion, retirement, restart, rollback, deletion, shell, or
approval tool exists. `DevelopmentService.register_existing_feature`
(`nova_lab/service.py`) keeps every V1A provenance check (safe ids, `lab/*`
branch, exact worktree root under the approved Labs root, same Git
repository, clean worktree, branch match, approved test profile, base_ref
resolved to an immutable SHA, that SHA verified as an ancestor of Lab HEAD,
LAB-only entry, no silent overwrite) and adds one more: `capability_id` must
be a real NOVA capability, checked against
`nova_os.capabilities.CANONICAL_CAPABILITY_IDS`. That constant is the single
canonical source of capability identity — `nova_os.catalog
.build_default_capability_manager()` asserts its registered, tool-wired
capabilities equal it (drift raises `RuntimeError` immediately), and NOVA Lab
validates against the same constant rather than maintaining a second
hard-coded list. To avoid a `nova_os` <-> `nova_lab` import cycle (`nova_os
.catalog` imports `tools.development`, which imports `nova_lab.service`) and
avoid pulling in every `tools/*` module just to check an id,
`nova_os/__init__.py` now resolves `build_default_capability_manager` lazily
via `__getattr__` (PEP 562); `from nova_os import build_default_capability
_manager` (as `agent.py` does) is unaffected, but merely importing
`nova_os.capabilities` no longer imports `nova_os.catalog`.

**Known limitation, verified against the real runtime**
(`livekit-agents==1.6.6`, `livekit-plugins-google==1.6.6`): in a live
Assistant session, `activate_capability("development")` reports success and
does update `Agent._tools`, but the model calling a newly-activated tool
(e.g. `list_lab_test_profiles`) within the SAME `session.run()` tool-calling
chain gets LiveKit's "Unknown function" error. Root cause, traced directly in
the installed `livekit-agents` source: `voice/agent_activity.py` snapshots
the tool list once per turn (`all_tools = self.tools.copy()` in
`_generate_reply()` for the text/pipeline path; `tool_ctx =
llm.ToolContext(self.tools)` per realtime `GenerationCreatedEvent` for the
production voice path), and a same-turn recursive tool-response continuation
reuses that original snapshot rather than re-reading the now-updated tool
list. The production voice path is further gated by Gemini Live only
learning a new tool schema after a full session reconnect
(`realtime_api.py`'s `_mark_restart_needed()`). VERIFIED: same-turn use
fails. NEEDS VERIFICATION: whether the tools work on the *following* turn —
blocked on Gemini free-tier daily quota, not on this codebase. Do not claim
next-turn activation works or that this is fixed; it is a NOVA OS
capability-kernel property (every optional capability, not just
`development`), and its resolution (most likely a stable dispatcher/gateway
tool, or gating always-registered tools through `CapabilityManager`/
`nova_policy` instead of the runtime tool schema) is a separate future
architecture decision. Full trace: `docs/NOVA-LAB-LIFECYCLE.md`.

V1B verified: focused NOVA Lab suite 38/38 (36 carried over from V1A
hardening + 2 new tests for capability_id rejection and for `"development"`
being canonical), full current suite 720/720, bare `pytest -q` 720/720,
`git diff --check` clean, NOVA local tools driver 35/35.

## Class Capture (capability of the one NOVA, V1.3.7)

Class Capture is a NOVA capability, not a separate mode. Raw evidence lives
outside Git at `%LOCALAPPDATA%\NOVA\ClassCapture\<COURSE>\<SESSION_ID>\`;
derived notes go to `<Obsidian vault>\Knowledge\Classes\<COURSE>\Sessions\`.

```
class_capture.py              LiveKit job: supervisor + transcription + live
                              intelligence. Starts the durable recorder BEFORE
                              any STT work. An AgentSession close is a recovery,
                              never the end of the class.
nova_capture/
  recorder_process.py         THE microphone owner, in its own OS process
                              (`python -m nova_capture.recorder_process`).
                              Stops only on an explicit stop file/signal, an
                              unrecoverable device failure, or a long-expired
                              supervisor heartbeat.
  audio_chunks.py             ChunkedAudioRecorder (20 s WAV chunks, temp ->
                              fsync -> atomic rename -> manifest) and
                              scan_audio_dir() integrity checking
  supervisor.py               ClassSessionSupervisor: one session id per
                              sitting, worker health, health.json, events.jsonl,
                              honest stop outcomes
  live_notes.py               notes during the lecture, durable evidence queue
  speakers.py                 conservative authoritative roles + live
                              confidence view + Guest Speaker
  pipeline.py                 NOVA_CLASS_PIPELINE seam (livekit default;
                              pipecat is an uninstalled pilot)
  status.py                   the status renderer both PowerShell and tests use
  control.py                  lifecycle lock, stop requests, orphaned-recorder stop
  understanding.py            map/reduce lecture understanding (see below)
  renderers.py                pure functions: understanding -> each document
scripts/nova_class_endurance.py   wall-clock soak monitor (observer only)
```

Per-session files: `audio/*.wav` + `audio/manifest.jsonl`, `health.json`,
`events.jsonl`, `class_capture.log`, `live_notes.md` (+ queue/state),
`transcript.jsonl`/`.txt`, `questions.jsonl`, `live_qa_events.jsonl`,
`speaker_roles.json` / `speaker_roles_live.json`, `session_evidence.json`,
`understanding.json`.

### Post-class generation is map/reduce, not five generations

Generation used to send the same ~32,000-character evidence bundle to the model
**once per output document**. On 2026-08-28 that produced five silent fallback
dumps for a real CEN4934 class while `postprocess.json` still said
`"completed"` — every prompt was ~8,000 tokens against a stock Ollama serving
2,048.

```
lecture sections (derive_lecture_structure, no model)
  -> windows of <=7,000 chars that never cross a section
  -> MAP       one small call per window
  -> REDUCE    one bounded call per semantic section
               oversized single topic -> contiguous child reductions
               -> compact child summaries -> bounded parent reduction
  -> GLOBAL    one bounded cross-cutting study-list pass
  -> LectureUnderstanding  -> understanding.json
  -> RENDER    pure Python, zero model calls -> all five documents
```

The original whole-lecture reduce was structurally unsafe: the measured prompt
was ~6,625 input tokens and the Groq path reserves 4,000 output tokens, so the
request could never fit an 8,000-TPM envelope. Section-level reduction fixed the
real lecture, but a professor can still stay on one topic for 90 minutes. The
current guard therefore enforces this invariant before every model call:

`estimated input + actual configured output reservation + safety margin <= request limit`

The default envelope is 8,000 request tokens, a 4,000 output reservation and a
500-token safety margin. Non-ASCII text is estimated conservatively, and the
post-class process tracks the largest output reservation actually configured for
its Groq/OpenAI/Ollama fallback path. If one semantic section is too large,
`understanding.py` recursively reduces contiguous child groups and then merges
bounded child summaries; it never sends the oversized parent request. A
pathological synthetic 90-minute single-topic regression test pins this case.

A failed window still costs one window rather than a whole document
(`degraded_windows`). Any section/global reduce path that needs deterministic
fallback is now reported through `reduce_degraded`, so postprocessing cannot
claim a completely clean synthesis. Adding a document means adding an entry to
`renderers.RENDERERS` — no prompt, no extra model call.

`live_notes.md` is written during class and kept in the raw session, but
`postprocess.py` does **not** read it yet — post-class generation still starts
from the transcript and `session_evidence.json`. Wiring live notes into
generation is a tracked P1 follow-up, not current behaviour.

**There is no `audio.wav` any more.** Read `audio/manifest.jsonl`, or use
`nova_capture.audio_chunks.scan_audio_dir()`. Sessions recorded before V1.3.7
still have `audio.wav` and are never migrated.

```powershell
.\Start-NOVA-Class.ps1 -Course COP3710         # start
.\Get-NOVA-Class-Status.ps1 -Watch             # live health
.\Stop-NOVA-Class.ps1                          # clean stop (never close the window)
.\Test-NOVA-Class-Endurance.ps1 -Minutes 150   # real soak, run beside a class
```

Rules that must not be undone (each has a regression test in
`tests/test_nova_class_fault_isolation.py`): the durable recorder starts before
any STT work; the `AgentSession` `close` handler may never call `finalize()` or
`ctx.shutdown()`; a stop that was never requested may never be reported as
`completed`. Full write-up:
`docs/NOVA-CLASS-CAPTURE-RELIABILITY-REPORT.md`.

Two more invariants, added 2026-08-31 after a real COT3400 lecture lost its
notes (`tests/test_nova_class_postprocess_liveness.py`,
`tests/test_nova_class_corrections.py`):

- **A status file never proves its own job is alive.** `postprocess.json` is
  read through `read_postprocess_status()`, which resolves the recorded status
  against process identity (`pid` + `pid_created_at`) using
  `control.process_identity_matches`. A killed job cannot write its own
  failure, so a recorded `running` whose process is gone resolves to
  `interrupted`. A bare PID is never enough — the OS recycles them. Only
  `running` is ever reinterpreted; terminal statuses are facts. Never read
  `postprocess.json` raw.
- **Ahmed's corrections outrank the recognizer, and never touch raw evidence.**
  `<classes root>/<COURSE>/STT-Corrections.md` holds `heard => actual` rules
  (`nova_school/corrections.py`). They are applied longest-phrase-first to the
  *derived* evidence view in `apply_course_corrections()`, before any fuzzy
  term repair, with the original preserved in `attributes["raw_text"]`.
  `transcript.jsonl` and the audio are never rewritten. The file lives beside
  `Materials/` and must never move inside it, or the corrections would be
  re-ingested as course material.

  Known limit: corrections match within a single transcript segment, so a
  phrase split across a segment boundary ("...to N" / "zero...") will not fire.
- **`session.json` is the manifest; `health.json` is the live truth.** The
  counts on `ClassSessionMetadata` from `transcript_segment_count` down are
  *finalization outputs* — before `finalize()` they are dataclass defaults, so
  a live session legitimately shows `audio_chunks: 0` and
  `recorder_mode: "none"`. Never read them raw: go through
  `nova_capture.status.session_metrics()`, which answers from session.json when
  `metrics_finalized` is set, from health.json while recording, and `None` for
  anything genuinely unmeasured. `None` means "nobody checked" and is a
  different claim from zero. Sessions written before the flag are trusted when
  stopped, so historical measurements are not discarded.

## Task runtime (`nova_runtime`)

The authoritative task foundation. Consumers: `agent.py` (constructs it,
recovers durable state at startup, shuts it down with the job),
`nova_school/automation.py`, and `nova_school/cli.py`.

```
nova_runtime/
  task_state.py   JobState + TaskSnapshot (frozen). The five original states
                  are a compatibility contract -- consumers compare by
                  identity (`is JobState.COMPLETED`), so never rename or
                  re-value them. Graph fields (parent_id, depends_on,
                  children, priority, attempt/max_attempts, owner,
                  required_permissions) are additive with defaults.
  jobs.py         BackgroundJobManager: asyncio, one loop, no locks. State
                  changes are whole-object `replace()` into a dict slot.
                  `start(name, awaitable)` is the original one-shot path and
                  must keep its exact behavior -- `nova_school` depends on it,
                  including its infinite watcher job and its over-limit
                  RuntimeError. `submit(JobSpec)` is the graph path: it takes a
                  FACTORY, not a coroutine, because a consumed coroutine cannot
                  be re-awaited -- which is what structurally blocked deferral
                  and retry. A dependency that fails, is cancelled, or does not
                  exist BLOCKS its dependent; an unknown dependency id fails
                  loudly rather than wedging the runtime forever.
  store.py        Durable state: append-only `tasks.ndjson` + atomically
                  replaced `tasks.json` index, under `runtime_root()/runtime`.
  events.py       EventBus. `publish` awaits handlers inline and catches
                  nothing -- a subscriber that raises surfaces as a JOB
                  failure, so any subscriber must swallow its own errors.
```

Rules:

- **`INTERRUPTED` is not `FAILED`.** A task whose process vanished was never
  observed to fail. `TaskStore.recover()` reinterprets a `RUNNING` task whose
  owning process is gone (matched on pid **and** process create time, since the
  OS recycles PIDs); terminal states are facts and are never rewritten. Same
  reasoning as the postprocess-liveness and session-metrics rules above.
- **`nova_runtime` must not import `nova_policy`, `nova_os`, or `nova_school`.**
  It records the permissions a task *would* need as data and never evaluates
  them — the task layer must not be able to decide its own authority. It also
  keeps infrastructure off a domain package: importing `nova_school.paths`
  costs ~372ms because that package's `__init__` loads all of course
  intelligence.
- **`runtime_root()` is deliberately duplicated** from `nova_school/paths.py`
  for that reason, and `tests/test_nova_runtime_store.py` asserts the two
  resolvers return the same path so the split-brain `paths.py` warns about
  cannot happen silently.
- **`result` is never persisted**, only `result_ref`. A result may be huge,
  unserializable, or private; durable state carries a pointer.

> **Resuming engineering? Read `docs/NOVA-CURRENT-STATE.md` first** — exact Git
> state, verified test count, architecture decisions, blockers, and the next
> executable step. `docs/NOVA-FAILURE-LEDGER.md` holds the root causes and the
> reusable rule from each failure.

## Knowledge, truth, and evidence

Transcript is **evidence, not fact**. Three stores, one owner each:

| Store | Owns | Never |
| --- | --- | --- |
| Raw files (`%LOCALAPPDATA%\NOVA\ClassCapture\...`) | audio, `transcript.jsonl`, journals | rewritten by any correction |
| `knowledge.sqlite3` (`nova_knowledge/knowledge_db.py`) | confidence, status, scope, counts, provenance | large binaries |
| The vault | human-readable notes Ahmed reads and edits | opaque rows |

Rules:

- **Only CONFIRMED corrections are applied.** A correction NOVA infers enters as
  a `candidate` and is inert. `times_seen` never promotes anything on its own —
  the recognizer can be wrong the same way twice. Promotion needs user
  confirmation or independent evidence; contradiction lowers confidence and
  retires the rule, which is **retained, not deleted**, because a retired rule
  explains why a note was revised.
- **Scope is part of the rule** (global / course / topic / speaker; most
  specific wins). `consents → constants` is right in an algorithms lecture and
  wrong in a conversation about consent forms.
- **NOVA's own output is never evidence for verifying NOVA's own output.**
  `CourseContextLibrary.build_context` includes `prior_note` sources — NOVA's
  generated notes — which is correct for *grounding* a live answer and
  disqualifying for *verification*. Use `verification_material()` there; it
  admits only `course_material` and `session_attachment`. This is not
  hypothetical: "GNRO" appeared in `Lecture.md`, `Study.md` and `Questions.md`,
  so the reviewer's first real run found "corroboration" and flagged nothing.
- **The note reviewer makes no model call.** Asking the same model whether it
  believes itself is not independent evidence; the professor's slides are.
  `nova_capture/note_review.py` is deterministic and **marks rather than
  deletes** — a real term the slides happen not to contain must survive flagged,
  in `Review.md`.
- **A regeneration preserves what it replaces.** `nova_capture/note_versions.py`
  archives previous notes into `_versions/vN/` with a manifest recording when
  and why. Current notes keep their filenames; large artifacts are referenced,
  not copied; archiving is best-effort and never blocks regeneration.

## Security invariants (each has a regression test)

- **`os.startfile` may only ever receive a document or media file.**
  `open_file_or_folder` (`tools/files.py`) checks `is_launchable()` against the
  `LAUNCHABLE_SUFFIXES` **allowlist** before launching. `os.startfile` runs the
  shell's default verb, which for `.exe/.bat/.cmd/.vbs/.js/.lnk/.hta/.msi` means
  *execute*. Without this check, `web_download` (REVERSIBLE, never prompts) into
  `~/Downloads` (a SAFE_DIR) followed by `open_file_or_folder` was unconfirmed
  code execution using two default-active capabilities — bypassing the declared
  `arbitrary_shell_command: RESTRICTED` policy entirely.
  **Keep it an allowlist.** A denylist loses to the next extension Windows makes
  executable, and to the ones nobody remembers (`.pif`, `.wsh`, `.application`).
  `tests/test_nova_launch_safety.py`.
- **NOVA may not write a runnable file to the Desktop.** `_safe_desktop_child`
  forces a non-launchable suffix. It previously applied `.txt` only when the
  suffix was *empty*, so `create_desktop_file("x.bat")` wrote an executable.
- **Being inside a SAFE_DIR says the path is allowed, never that the contents
  are safe.** Sandbox containment and content safety are different questions;
  do not let one stand in for the other.
- **`nova_runtime` must not import `nova_policy` or `nova_os`.** The task layer
  records the permissions a task *would* need as data; it must never be able to
  evaluate its own authority. The orchestrator asks the trusted engine.
  `tests/test_nova_runtime_task_graph.py`.

Known gaps, documented in `ROADMAP.md` and NOT yet fixed: `approve()` has no
production caller, so no SENSITIVE action can ever be approved; the permission
engine has no principal, so a worker would be indistinguishable from the user;
only 4 of 81 tools route through the engine at all.

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
`SYSTEM_PROMPT`, existing working tools. Video input is currently OFF
(`video_input=False`, Ahmed's choice 2026-07-11) — don't flip it either way
without asking him.

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
- Dashboard status (updated 2026-07-21) — **SUPERSEDED 2026-08-15**: the
  `Dashboard/` directory described below no longer exists in this repository.
  It was detached with the rest of Valo per the project boundary at the top of
  this file. The entry is kept as history; nothing in it describes current
  NOVA. Original text follows. The old React/Vite + Tauri shell and the
  Tkinter skin were deleted at Ahmed's request (source backed up to the
  session scratchpad first) along with the demo zip. `Dashboard/` now holds
  the REAL dashboard, implemented from `design_handoff_nova_desktop` (kept as
  `Dashboard/DESIGN_HANDOFF.md`): the high-fidelity 5-page shell
  (`web/index.html` + `web/support.js` + wallpaper) with a live WebSocket
  bridge added to its logic class, served by `Dashboard/server.py` (aiohttp,
  binds 127.0.0.1:8787, zero new dependencies) with `feeds.py`/`actions.py`.
  Real wiring: psutil stats, Spotify (cached-OAuth Web API + window-title
  fallback, media-key controls), wttr.in weather, Obsidian vault (note count,
  recent notes, memory browser, `<vault>/NOVA/Tasks.md` tasks with
  write-back; forget moves to `NOVA/.trash`), agent phase + activity tailed
  from `nova_tools.log`, approvals from `audit_logs/nova_actions.jsonl`,
  conversation bubbles from `conversation_logs/`, usage chips from
  `cloud_usage.json`, real Start Menu apps / Desktop folders / Recent files
  with real launches. With no server the shell falls back to the design's
  simulated demo. Launch: `Dashboard\start_dashboard.ps1` or
  `venv\Scripts\python.exe Dashboard\server.py`; browser-pane preview via
  `.agents/launch.json` (`nova-dashboard`, port 8787). Verified 2026-07-20:
  feeds smoke 14/14, driver `tools` 33/33, live browser check with real data;
  driver `chat` blocked by Gemini 503/504 (known issue). The private local
  bridge now sends Ctrl+K text turns to the active LiveKit session and
  resolves Approve/Deny inside the agent process. Commands are validated,
  atomic, and expire after two minutes. Calendar is still Demo Data.
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
- `core/` (task.py, router.py, orchestrator.py) — **SUPERSEDED 2026-08-31.**
  Written, never imported by anything, and it collides by *class name* with the
  systems that actually run:

  | dead                       | live                                    |
  | -------------------------- | --------------------------------------- |
  | `core/router.py:12` `ModelRouter` (47 lines) | `nova_core/router.py:59` `ModelRouter` (421+) |
  | `core/task.py:25` `NovaTask`                 | `nova_runtime/task_state.py:17` `TaskSnapshot` |
  | `core/orchestrator.py:22` `NovaOrchestrator` | — (no live equivalent yet)              |

  **Ownership decision: `nova_runtime` owns tasks, `nova_core` owns model
  routing.** Do NOT revive `core/` and do NOT build the orchestrator from
  `core/orchestrator.py` — that would give NOVA two routers and two task
  models. `tests/test_nova_no_duplicate_runtime.py` fails the build if anything
  imports `core.*`. Deleting the directory is still Ahmed's call; the guard
  test makes leaving it on disk safe in the meantime.
