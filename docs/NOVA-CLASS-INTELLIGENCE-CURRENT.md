# NOVA Class Intelligence — Current State

## Release candidate

V1.3.7 — Durable audio, session supervisor, live notes

> Full reliability write-up: `docs/NOVA-CLASS-CAPTURE-RELIABILITY-REPORT.md`

## Verified by automated tests

- durable chunked audio in a separate OS process, surviving a hard kill of the
  intelligence process (real subprocess test on Windows);
- one logical session id across repeated transcription-worker loss and restart;
- a simulated 180-minute sitting with a continuous chunk sequence, frame-exact
  timestamps, no self-stop, and no memory growth with duration;
- a 2h30m fault-injection scenario (STT loss, provider outage, guest speaker);
- live notes with a durable evidence queue that survives a provider outage;
- live speaker confidence with guest-speaker separation, without weakening the
  conservative labels written into study documents;
- stop outcomes that can never claim success they did not achieve;
- one authoritative `nova_capture` session/audio pipeline;
- V1.2 lifecycle reliability and recovery;
- structured/raw + readable transcript storage;
- fragmented and punctuation-poor question detection;
- cautious teacher/student role inference with manual override;
- grounded live-Q&A orchestration and permanent logging;
- course/session material context and session attachment copying;
- bounded recent-Downloads auto-organization;
- chunked post-class evidence extraction with no-AI fallback;
- Markdown study outputs;
- real PPTX generation;
- no eager `nova_capture.control` import warning;
- NOVA/Valo repository boundary unchanged.

## 2026-08-29 checkpoint hardening — pending Windows verification

The current uncommitted patch closes the last known request-size hole in
post-class synthesis without changing the durable capture hot path:

- every model request is checked against an explicit request envelope before it
  is sent; the default is 8,000 request tokens with the actual configured
  output reservation plus a 500-token safety margin;
- one unusually long semantic section is reduced hierarchically (contiguous
  child groups -> compact child summaries -> parent reduction) instead of being
  sent as one oversized request;
- a forced synthetic 90-minute one-topic lecture verifies that every observed
  request stays inside the envelope and the final section still covers the full
  lecture span;
- non-ASCII prompt estimation is conservative rather than assuming an English
  chars/token ratio;
- committed question-detection fixtures now use synthetic ASR-like phrases, and
  the reliability report uses `<SESSION_ID>` rather than a unique real-session
  folder name.

Local audit-copy verification: 66 directly affected tests passed. The Windows
venv full suite and one final end-to-end Groq run are still required before this
can be called a completed checkpoint.

## Needs live verification on the user's Windows NOVA runtime

- microphone and Deepgram under V1.3;
- Windows answer notification rendering;
- two-or-more-speaker diarization behavior;
- teacher/student inference on a real lecture;
- specialist-router answer latency/quality;
- detached post-class worker behavior after clean stop;
- safe legacy-console closure;
- real lecture note completeness;
- real PowerPoint/PDF context quality.

## Known external issue

LiveKit CLI 2.18.2 did not honor this repository's existing venv correctly for
`lk agent console`; the verified legacy launcher remains in place with NOVA's
own targeted clean-stop/verified-launcher cleanup. Do not change package
management merely to work around that external CLI issue without re-verifying.

## Next quality gate

Install V1.3, run the controlled live acceptance test, then benchmark the two
representative lecture recordings before any Git checkpoint is called
production-ready.

## V1.3.1 live-test findings and fixes

Verified in the 2026-08-23 Windows acceptance run:

- targeted stop finalized transcript/audio and cleared active state;
- the legacy LiveKit console closed after finalization;
- post-class intelligence completed and wrote the session output folder;
- fragmented spoken questions were assembled across STT chunks;
- Nova-3 misheard important CEN4065 terms such as aggregation/composition;
- Groq was configured in `NovaConfiguration` but not registered in the provider registry.

V1.3.1 therefore:

- implements and registers the existing planned `GroqProvider`;
- migrates the old Groq default to `openai/gpt-oss-120b` while leaving local secrets/config files untouched;
- routes Class Intelligence only as Groq -> OpenAI -> Ollama without changing global NOVA role defaults;
- expands Nova-3 keyterms from trusted course/session materials up to the provider limit;
- writes `stt_keyterms.json` in every raw session for auditability;
- applies conservative downstream terminology interpretation without altering the authoritative raw transcript;
- writes any question corrections to `question_interpretations.jsonl`.

The second 2026-08-23 live test additionally verified:

- the STT keyterm expansion reached the intended 100-term ceiling;
- Groq and OpenAI provider health checks were READY;
- Groq generation was blocked before provider execution because the shared NOVA
  cloud-request budget had already reached its configured 5/5 daily limit;
- a non-academic utterance (`Hello?`) was classified as a question and attempted
  to spend a cloud request.

V1.3.2 therefore:

- gives Class Intelligence a separate local cloud-request budget (default 60/day,
  configurable with `NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT`) without changing the
  general NOVA cloud budget;
- stores only counts/provider names in the separate class budget state;
- prevents greetings and very short/non-substantive question fragments from being
  added to the live Q&A path;
- adds `Test-NOVA-Class-AI.ps1` for a real generation check through the exact class
  router before starting a lecture;
- preserves the 100-keyterm STT vocabulary, raw transcript, audio, course context,
  Groq/OpenAI/Ollama provider order, and all V1.3/V1.3.1 lifecycle behavior.

The next quality gate is a successful class-router generation test, followed by
one CEN4065 aggregation/composition live test and then a multi-speaker/real-lecture
benchmark.


## V1.3.3 classroom-signal findings and fixes

The 2026-08-23 multi-speaker live acceptance run verified that the V1.3.2
pipeline now performs real in-session Groq generation, shows near-real-time
answers, separates raw diarized speaker IDs, persists Q&A, and cleanly finalizes
audio/transcript/post-processing.

That same run exposed three quality issues:

- automatic role inference could lock the first/only early speaker as Teacher
  before a second speaker appeared, then never reconsider the decision;
- statement fragments beginning with auxiliary words (for example, `can` or
  `have`) could be misclassified as questions;
- generated prior notes/transcripts were eligible for STT-keyterm mining, so
  earlier ASR errors such as `aggression` and `compulsion` could be fed back to
  Deepgram as future prompts.

V1.3.3 therefore:

- keeps raw diarized speaker IDs authoritative during live capture unless a
  manual teacher ID is supplied;
- defers automatic Professor/Student assignment until finalization and requires
  strong multi-speaker, early-lecturer, dominance, and absolute-speech evidence;
- leaves roles generic when evidence is ambiguous instead of forcing a Teacher;
- tightens punctuation-poor question grammar so statement fragments like
  `can just stick there.` and `Have an Indian professor.` do not spend live-AI
  requests;
- preserves discourse lead-ins when assembling split questions, so phrases like
  `Like, where are you` + `getting theta from?` stay one question;
- mines STT keyterms only from curated course terms plus original/attached course
  materials, never NOVA-generated prior notes or transcripts;
- treats 100 as a maximum, not a target that must be filled with low-value terms;
- stores structured `live_qa_events.jsonl` and re-renders `Live Q&A.md` after
  final speaker resolution so Q&A speaker labels cannot disagree with
  `questions.jsonl`;
- strengthens the answer prompt against guessing replacements for garbled ASR
  words unless the deterministic terminology layer supplied the correction;
- preserves the dedicated class cloud budget, Groq -> OpenAI -> Ollama routing,
  raw transcript/audio, post-class outputs, and clean-stop lifecycle.

UTF-8 storage was verified healthy. PowerShell 5.1 must read UTF-8 session files
with `-Encoding UTF8`; no file-format migration is required.

The next quality gate after V1.3.3 is a real lecture benchmark with an actual
professor plus at least one student question, checking accent transcription,
role confidence, question precision/recall, popup latency, and final notes.


## V1.3.4 turn-aware question findings and fixes

The 2026-08-23 V1.3.3 live acceptance run verified cleaner statement filtering,
generic live speaker labels, a reduced/trusted STT keyterm set, Groq live
generation, and clean capture shutdown. It also exposed a timing problem in
the live-question path:

- finalized STT chunks were being classified and answered before LiveKit had
  committed the speaker's complete human turn;
- one spoken question could therefore become multiple model calls, for example
  `Like, where are you?` followed by `Getting the data from?`;
- rapid restatements could launch near-duplicate live answers;
- per-question `asyncio.create_task` fan-out allowed provider work to overlap,
  and an answer could still be running when class finalization began.

V1.3.4 therefore:

- keeps every finalized STT chunk authoritative and saves it immediately to the
  raw transcript;
- buffers only the live-question interpretation path until
  `conversation_item_added` commits a user turn;
- gives slow final STT a 450 ms grace window after the committed-turn event;
- retains a 3.5 second inactivity fallback if a committed-turn event is absent;
- merges grammatical WH continuations such as
  `Like, where are you?` + `Getting the data from?` into one spoken question;
- preserves speaker boundaries when a committed turn contains multiple diarized
  speaker IDs;
- suppresses near-identical restatements for 15 seconds before they spend another
  live-AI request;
- replaces per-question answer task fan-out with one bounded serial answer queue;
- drains the answer queue during clean shutdown and cancels remaining worker
  activity before final capture finalization;
- preserves unanswered questions in `questions.jsonl` for post-class review if
  the live queue cannot drain in time;
- preserves all V1.3.3 speaker-role, vocabulary, provider routing, class budget,
  raw audio/transcript, structured Q&A, post-class, and clean-stop behavior.

The next quality gate is a short Windows acceptance run that reproduces the
exact split-question case, repeats a paraphrase within 15 seconds, verifies
only one live answer, and confirms no live-answer work continues after clean
shutdown. After that, Class Awareness can be wired into the normal NOVA agent.


## V1.3.7 reliability rebuild (2026-08-28)

A real COP3710 lecture on 2026-08-27 stopped recording after **38m37s** while
the user was still in class. The evidence on disk is unambiguous: `audio.wav`
ended at 2317.744 s, the last transcript segment ended at 2317.812 s, and
`session.json` said `status: "completed"` with `audio_error: null`. Both streams
died together because the microphone was closed by `finalize()`, which the
LiveKit job shutdown callback owned. **Which** LiveKit event fired cannot be
determined, because Class Capture wrote no log file.

V1.3.7 therefore:

- moves the microphone into its own OS process (`nova_capture/recorder_process.py`)
  that knows nothing about STT, LLMs, or LiveKit, and stops only on an explicit
  request, an unrecoverable capture-device failure, or a long-expired supervisor;
- replaces the single `audio.wav` with rolling 20-second WAV chunks plus an
  append-only `audio/manifest.jsonl`, written temp → fsync → atomic rename, so a
  crash costs at most the chunk in flight and any loss is detectable
  (`scan_audio_dir`);
- adds `ClassSessionSupervisor`, which owns one session id for the whole sitting,
  tracks every worker in `health.json`, and journals lifecycle events to
  `events.jsonl`;
- turns an `AgentSession` close into a recovery — `STT_GAP_START`, rebuild with
  backoff, `STT_GAP_END` — instead of the end of the class;
- adds a live notes worker with evidence batching and a durable queue, so a
  provider outage costs latency and never evidence, and starts producing notes
  within roughly 60–120 seconds. `live_notes.md` is written during class and
  persisted in the raw session, but **post-processing does not read it yet** —
  wiring it in as an explicit generation input is a P1 follow-up;
- gives `SpeakerRoleTracker` a live confidence view and a Guest Speaker role,
  while leaving the authoritative finalize-only labels exactly as V1.3.3 made
  them;
- reports honest stop outcomes (`completed` / `completed_with_warnings` /
  `failed` / `aborted`) and writes `class_capture.log` in every session;
- keeps LiveKit Inference as the default pipeline and ships Pipecat 1.8.1 only
  as a flagged, uninstalled pilot (`NOVA_CLASS_PIPELINE`).

**Status: IMPLEMENTED + AUTOMATED TESTS PASSED** — 388 passed / 0 failed
(baseline 282), plus a real Windows microphone check proving the separate
recorder process acquires the capture device. **The real 150-minute soak has
NOT been run**, and transcript gap backfill is **not implemented**.

Next quality gate: a real classroom run with
`.\Test-NOVA-Class-Endurance.ps1 -Minutes 150` beside it.
