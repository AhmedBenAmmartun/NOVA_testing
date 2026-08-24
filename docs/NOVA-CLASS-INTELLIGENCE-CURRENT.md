# NOVA Class Intelligence — Current State

## Release candidate

V1.3.4 — Turn-aware live question engine

## Verified by automated tests

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
