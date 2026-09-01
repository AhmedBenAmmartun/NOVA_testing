# NOVA Class Capture — Reliability + Live Intelligence Report

_Implementation date: 2026-08-28 · Capture version 1.3.6 → 1.3.7_

---

## 1. Executive Summary

**What was wrong.** A real COP3710 lecture on 2026-08-27 stopped recording after
**38 minutes 37 seconds** while the user was still in class. The cause was
architectural, not incidental: the microphone lived inside the same asyncio
process as the LiveKit `AgentSession`, and the recorder was closed by the job's
shutdown callback. Anything that ended that session — an unrecoverable STT
error, a transport disconnect, a job shutdown — also ended the recording. The
session was then written to disk with `status: "completed"`, so nothing in the
evidence said the class had been cut off.

**What was changed.** Audio is now the durable source of truth and everything
else is a worker that may fail:

- the microphone is owned by a **separate OS process**
  (`nova_capture/recorder_process.py`) that knows nothing about STT, LLMs, or
  LiveKit, and stops only on an explicit request, an unrecoverable capture-device
  failure, or a long-expired supervisor;
- audio is written as **rolling 20-second WAV chunks** with an append-only
  manifest, atomic renames and fsync, so a crash can cost at most the chunk in
  flight and a missing chunk is *detectable*;
- a **`ClassSessionSupervisor`** owns one logical session id for the whole
  sitting, tracks every worker's health in `health.json`, and journals what
  happened in `events.jsonl`;
- losing the transcription session is now a **recovery event**, not the end of
  the class: the gap is recorded, transcription is rebuilt with backoff, the
  session id and the recording are untouched;
- **live notes** are written during the lecture with a durable evidence queue,
  so a provider outage costs latency, never evidence;
- **speaker intelligence** gained a live, confidence-scored view and explicit
  Guest Speaker separation, without weakening the conservative labels that go
  into the study documents;
- stop now reports the outcome it actually achieved —
  `completed` / `completed_with_warnings` / `failed` / `aborted` — and can
  never silently claim success.

**Current reliability status.** `IMPLEMENTED + AUTOMATED TESTS PASSED`
(388 passed / 0 failed / 0 skipped, up from a 282-test green baseline), plus one
real Windows microphone check proving the separate recorder process actually
acquires the capture device. A simulated three-hour class at the **production
20-second chunk default** produces exactly **540 chunks** with no gaps and no
overwrites. The full 150-minute wall-clock soak has **not** been run, and this
is **not** `VERIFIED FOR REAL CLASS USE` — see the runtime acceptance checklist
in §18.

**Is Pipecat used?** No. **PILOT ONLY** — see §13. The abstraction and feature
flag ship; the dependency does not.

**Ready for a real class?** Ready to *try* with a monitor running. Not yet
`VERIFIED FOR REAL CLASS USE` — that phrase is reserved until a real
multi-hour classroom run succeeds (§18, §24).

---

## 2. Verified Starting State

| Item | Value |
| --- | --- |
| Repository | `C:\Projects\AI Agent` (NOVA only; Valo untouched) |
| Branch | `nova-nextgen-runtime-20260824` |
| HEAD at start | `72e4d519d392a7ba89b0a0ca83415d3a4236ac7a` — "Centralize NOVA path authority and protect archives" (2026-08-27) |
| Remotes | `origin` → BEN-Ammar-Ahmed/Nova · `testing` → AhmedBenAmmartun/NOVA_testing |
| Working tree at start | `M agent.py`; untracked `nova_knowledge/`, `nova_learning/`, 4 `scripts/nova_knowledge_*`, 4 `tests/test_*learning*|*knowledge*` — **pre-existing work, not touched by this task** |
| Python | 3.14.6 (`venv\Scripts\python.exe`) |
| Platform | Windows-11-10.0.26200-SP0 |
| livekit-agents | 1.6.6 (livekit 1.1.13, livekit-api 1.2.0, livekit-protocol 1.1.21) |
| Audio / process deps | sounddevice 0.5.5, psutil 7.2.2, numpy 2.5.1 |
| Capture version | `1.3.6` → `1.3.7` |
| Raw capture root | `%LOCALAPPDATA%\NOVA\ClassCapture\<COURSE>\<SESSION_ID>` (unchanged) |
| Control root | `%LOCALAPPDATA%\NOVA\ClassCapture\_control` (unchanged) |
| Derived notes root | `<Obsidian vault>\Knowledge\Classes\<COURSE>\Sessions\` (unchanged) |
| Baseline test suite | `388 passed` after this work; `282 passed` before it |

Sensitive credential material exists in this repository and was intentionally
not displayed, read for value, or copied anywhere.

---

## 3. Root Cause Analysis

### VERIFIED (from the session's own evidence on disk)

Session `COP3710/<SESSION_ID>`:

| Evidence | Value |
| --- | --- |
| `audio.wav` | 37,083,904 frames @ 16 kHz = **2317.744 s (38:37.7)** |
| Last transcript segment `end_seconds` | **2317.812 s** |
| `started_at` → `stopped_at` | 19:17:57.932Z → 19:56:59.260Z = **2341.3 s** |
| `status` | `"completed"` |
| `audio_enabled` / `audio_error` | `true` / `null` |
| Segments / questions | 743 / 90 |

From this, four things are certain:

1. **Audio and transcription stopped at the same instant** (0.068 s apart).
   They come from different sources — `sounddevice` for the WAV, LiveKit
   Inference for the transcript — so a single shared cause ended both.
2. **The microphone did not fail.** `audio_error` is `null` and
   `audio_enabled` is `true`; a device error would have been recorded.
3. **The recording was closed by `finalize()`.** In the old
   `class_capture.py`, `microphone.stop()` was reachable only from `finalize()`,
   which ran only from the LiveKit job shutdown callback or the startup
   exception path.
4. **It ran the normal shutdown path, not the error path.** The exception path
   wrote `status="error"`; the file says `completed`. Finalization then took
   23.4 s, consistent with the 10-second answer-queue drain plus speaker
   finalization and post-processing launch.

Conclusion: **the entire capture process was shut down at 38:37 and then
finalized normally.** The old design guaranteed that killed the recording.

### PROBABLE contributing factors (not verified)

Reading livekit-agents 1.6.6 as installed, two documented mechanisms produce
exactly this shape:

- `AgentSession._on_error` (`voice/agent_session.py:1614-1647`) closes the
  session with `CloseReason.ERROR` once **more than three consecutive
  unrecoverable STT errors** occur (`SessionConnectOptions.max_unrecoverable_errors = 3`,
  line 146). The STT counter resets only on a successful transcript.
- `voice/room_io/room_io.py:404-420` closes the session with
  `CloseReason.PARTICIPANT_DISCONNECTED` when the participant disconnects
  (`close_on_disconnect` defaults to `True`).

Either can end the job in console mode, which triggers the shutdown callback.

### UNKNOWN / UNVERIFIABLE

**Which of these actually fired cannot be determined**, because Class Capture
wrote **no log file**. `logging.getLogger("nova.class_capture")` output went to
the console window, which was closed. The `on_error` handler logged the error
*type* only, and to nowhere durable.

This is itself a defect, and it is fixed: every session now writes
`class_capture.log`, and every lifecycle transition is journaled to
`events.jsonl`, including a `close` handler that records the LiveKit close
reason verbatim.

### Explicitly ruled out

| Hypothesis | Why it is ruled out |
| --- | --- |
| The user stopped it | `stop.request.json` is cleared on claim and only honoured for a matching session id; the user states they did not stop it |
| Microphone/device failure | `audio_error: null`, `audio_enabled: true` |
| Disk exhaustion | 74 MB written; the volume had room, and no OSError was recorded |
| Memory growth | The old writer streamed to a single WAV; it held no PCM |
| A NOVA duration cap | None existed anywhere in the code |

---

## 4. Architecture Before

```
                        ONE PROCESS
  ┌──────────────────────────────────────────────────────────────┐
  │  class_capture.py (LiveKit job)                              │
  │                                                              │
  │   ClassCaptureSession ── session.json, transcript.jsonl      │
  │                                                              │
  │   LocalMicrophoneCapture ─► LocalWaveRecorder ─► audio.wav   │
  │            ▲                                    (one file,   │
  │            │                                     header only │
  │            │                                     valid after │
  │            │                                     close)      │
  │            │                                                 │
  │   finalize() ── stops the microphone ◄── ctx shutdown        │
  │            ▲                                                 │
  │            │                                                 │
  │   AgentSession(stt=LiveKit Inference/Deepgram)               │
  │        │   └── unrecoverable errors ──► session closes       │
  │        │   └── participant disconnect ──► session closes     │
  │        ▼                                                     │
  │   transcript ─► questions ─► Live Q&A ─► speakers            │
  │                                                              │
  │   notes: NONE until after the class                          │
  └──────────────────────────────────────────────────────────────┘

  Failure direction:  STT ──► session ──► job ──► finalize ──► AUDIO DIES
```

Everything pointed the wrong way: a transcription failure could reach the
recording.

## 5. Architecture After

```
                                NOVA
                                  │  "record my class"
                                  ▼
   PROCESS A — Class Intelligence (class_capture.py)
  ┌───────────────────────────────────────────────────────────────────┐
  │  ClassSessionSupervisor      one session_id for the whole sitting │
  │    ├── owns stop request, worker health, recovery counters        │
  │    ├── health.json      (atomic, every 5 s)                       │
  │    ├── events.jsonl     (append-only lifecycle journal)           │
  │    └── class_capture.log                                          │
  │                                                                   │
  │  AgentSession(stt=Deepgram nova-3-general via LiveKit Inference)  │
  │    │   on("close") ─► STT_GAP_START ─► rebuild session ─► resume  │
  │    │                  (never finalize, never touch the audio)     │
  │    ▼                                                              │
  │  TranscriptJournal ─┬─► SpeakerRoleTracker ─► speaker_roles_live  │
  │                     ├─► QuestionJournal ─► LiveQAManager          │
  │                     └─► LiveNotesWorker ─► live_notes.md          │
  │                             │                                     │
  │                             └── durable queue + checkpoint        │
  │                                 (provider outage = latency only)  │
  └───────────────────────────────────────────────────────────────────┘
             │ spawn / heartbeat / stop-file          ▲ recorder.json
             ▼                                        │ (health)
   PROCESS B — Durable Recorder (nova_capture.recorder_process)
  ┌───────────────────────────────────────────────────────────────────┐
  │  LocalMicrophoneCapture ─► ChunkedAudioRecorder                   │
  │                                                                   │
  │    NNNNNN.wav.tmp → flush → fsync → close → atomic rename         │
  │                          → append audio/manifest.jsonl            │
  │                                                                   │
  │  Stops ONLY on:  explicit stop file / signal                      │
  │                  unrecoverable capture-device failure             │
  │                  supervisor gone > orphan grace (default 1 h)     │
  │                  opt-in --max-seconds                             │
  └───────────────────────────────────────────────────────────────────┘

   PROCESS C — Post-class refinement (nova_capture.postprocess, detached)
        complete transcript + questions + Q&A + session evidence
        + speaker roles + course materials  ─►  Lecture / Summary /
        Study / Questions / Evidence / Lecture Timeline / Presentation

        NOTE: live_notes.md is written during class and persisted in the raw
        session, but post-processing does NOT read it yet. Wiring it in is a
        P1 follow-up (§22 #7), not current behaviour.

   Pipeline boundary:  NOVA_CLASS_PIPELINE = livekit (default, verified)
                                           | pipecat (pilot, see §13)
```

Failure direction is now inverted: **nothing downstream of the microphone can
reach the microphone.**

---

## 6. Files Added

| File | Purpose | Why needed |
| --- | --- | --- |
| `nova_capture/audio_chunks.py` | `ChunkedAudioRecorder`, `ChunkRecord`, `scan_audio_dir`, `AudioIntegrityReport` | A single growing `audio.wav` has no valid header until it is closed and no record of what should exist. Chunks + manifest make a crash cost seconds and make loss detectable. |
| `nova_capture/recorder_process.py` | Recorder entry point (`python -m nova_capture.recorder_process`), `DurableRecorderProcess`, `InlineDurableRecorder`, `create_durable_recorder` | Puts an OS process boundary between the microphone and everything that can fail. |
| `nova_capture/supervisor.py` | `ClassSessionSupervisor`, `WorkerStatus`, `SessionOutcome`, `CaptureEvent`, `read_health`, `read_events` | One owner of the sitting; workers report in. Dependency-free so a 180-minute session is testable in milliseconds. |
| `nova_capture/live_notes.py` | `LiveNotesBatcher`, `LiveNotesQueue`, `LiveNotesDocument`, `LiveNotesWorker` | Notes during the lecture, batched to avoid per-sentence model calls, with a durable queue so a provider outage cannot lose evidence. |
| `nova_capture/pipeline.py` | `resolve_class_pipeline`, `PipelineSelection`, `PipecatTranscriptionEngine`, `describe_pipecat_support` | Makes the transcription engine a configuration choice and lets the Pipecat pilot state precisely what it is missing. |
| `nova_capture/status.py` | `render_status`, `status_json`, `latest_session_path` | Status that reports the recording, not the process — shared by PowerShell, tests, and tooling. |
| `scripts/nova_class_endurance.py` | Wall-clock soak monitor (observer only) | Automated tests cannot prove this machine survives 150 real minutes. |
| `Test-NOVA-Class-Endurance.ps1` | Launcher for the soak monitor | The requested real endurance entry point. |
| `tests/test_nova_class_durable_audio.py` (13) | Chunking, manifests, integrity, resume | — |
| `tests/test_nova_class_long_session.py` (13) | Simulated 180-minute sitting **at the production 20 s chunk default** (540 chunks) | — |
| `tests/test_nova_class_supervisor.py` (12) | Session ownership, outcomes, health, events | — |
| `tests/test_nova_class_recovery.py` (9) | Recorder loop + **real process-isolation crash test** | — |
| `tests/test_nova_class_live_notes.py` (15) | Batching, durable queue, provider failure/recovery | — |
| `tests/test_nova_class_live_speakers.py` (10) | Live confidence, guest speakers, honest "Unknown" | — |
| `tests/test_nova_class_pipecat_adapter.py` (8) | Pipeline selection and pilot honesty | — |
| `tests/test_nova_class_fault_isolation.py` (14) | 2h30m torture scenario + structural guarantees | — |
| `tests/test_nova_class_lifecycle_v137.py` (12) | Duplicate start, clean stop, orphan stop, status | — |
| `docs/NOVA-CLASS-CAPTURE-RELIABILITY-REPORT.md` | This report | — |

## 7. Files Modified

| File | Before | After | Reason | Risk |
| --- | --- | --- | --- | --- |
| `class_capture.py` | One process; mic closed by `finalize()`; STT close = end of class; no health; no live notes; version 1.3.6 | Supervisor-owned session; durable recorder started **before** any STT work; `on("close")` rebuilds transcription; health/events/log files; live notes worker; honest outcome; version 1.3.7 | The core fix | **Medium** — the largest change. Every previously asserted behaviour string is preserved and the existing class suite (217 tests) still passes. |
| `nova_capture/speakers.py` | Conservative finalize-only inference | Same conservative `resolve()`, plus `live_assessment`/`live_snapshot`, guest-speaker separation, instructional-language and interaction evidence | Requirements 15–17 without regressing the V1.3.3 lesson | Low — authoritative labels unchanged; all V1.3/V1.3.3 speaker tests pass unmodified |
| `nova_capture/control.py` | Stop signalled only the in-process job | Also writes the recorder stop file; remembers `last_session.json`; `stop_orphaned_recorder()` | A separate recorder must remain stoppable when the intelligence process is gone | Low |
| `nova_capture/microphone.py` | Typed to `LocalWaveRecorder` | Typed to a `PcmSink` protocol | Lets the same adapter drive either recorder | Very low |
| `nova_capture/models.py` | `SpeakerRole` without a guest role | Added `GUEST = "guest"` | Guests must not be students or professors | Very low — additive |
| `nova_capture/intelligence.py` | `_route` was private | Added public `route_class_prompt` | Live notes and post-class share one provider order and budget | Very low |
| `nova_capture/__init__.py` | — | Exports the new capture API | Discoverability | Very low |
| `tools/class_capture.py` | `end_class_capture` checked `audio.wav` only | `_verify_saved_audio` accepts chunked audio and still accepts legacy `audio.wav` | Otherwise NOVA would report "audio unavailable" for every new session | Low |
| `Get-NOVA-Class-Status.ps1` | Printed control state + postprocess status | Full health view via `nova_capture.status`, `-Watch`, `-Json`, `-Session` | Requirement 9 | Low |
| `tests/test_phase1_vision_contract.py` | `active_python_sources()` scanned `.claude/worktrees/` | `.claude` added to the blocked set | A background git worktree of an older branch was being scanned as live NOVA source (§15) | Very low — unrelated to Class Capture; the contract is unchanged for every live file |

`agent.py` shows as modified in `git status`; that change **pre-dates this task**
and was not touched.

---

## 8. Durable Recording Implementation

**Chunk duration: 20 seconds** (`NOVA_CLASS_AUDIO_CHUNK_SECONDS`). Chosen from
the measured trade-off: at 16 kHz mono 16-bit each chunk is 640 KB, a 3-hour
class is 540 files and 346 MB, and an abrupt kill can cost at most 20 seconds.
Shorter values multiply file operations for no meaningful gain; longer ones
increase what a crash costs.

**Write path** (`ChunkedAudioRecorder._close_current_locked`):

```
write_pcm  →  NNNNNN.wav.tmp
           →  wave.close()      (rewrites RIFF/data sizes — header now correct)
           →  flush + os.fsync  (bytes are on the platter)
           →  os.replace()      (atomic publish)
           →  append manifest.jsonl (+ fsync)
```

Every published `NNNNNN.wav` is a complete, playable WAV *before* the next one
begins. Verified by opening finished chunks with `wave` while the recorder is
still running.

**Chunk-boundary splitting.** A defect found by testing: an oversized single
`write_pcm` used to land entirely in the current chunk, so chunk length depended
on device block size. `write_pcm` now splits payloads exactly at the boundary,
so chunk duration depends only on `chunk_seconds`.

**Manifest** (`audio/manifest.jsonl`, append-only), one record per chunk:

```json
{"sequence": 42, "file": "000042.wav", "start_seconds": 820.0,
 "end_seconds": 840.0, "frames": 320000, "bytes": 640044,
 "sample_rate": 16000, "channels": 1, "sample_width": 2,
 "status": "complete", "started_at": "...", "completed_at": "..."}
```

`scan_audio_dir()` reads it and detects missing chunks, sequence gaps,
timestamp gaps, truncated files (size vs recorded size), unlisted files,
orphaned `.tmp` chunks, and malformed manifest lines. It is strictly read-only —
it never repairs or deletes a recording. While a recorder is actively writing,
the single trailing `.tmp` is reported as `in_progress`, not as damage.

**Timestamps** come from frames written (`total_frames / sample_rate`), never
from the wall clock, so there is zero drift at the three-hour mark
(asserted to 1e-6 s).

**Memory.** PCM streams straight to the file handle; only per-chunk metadata is
retained. Measured over a simulated 180-minute session writing 17.3 MB:
**< 1 MB retained**, and less than 1/10th of the bytes written. Measured on the
real recorder process: RSS flat at **9.5 MB**.

**Stop.** The current chunk is finalized (a partial chunk is published; an empty
one is not), the manifest is completed, and `recorder.json` records the status
and the reason.

**Crash.** Completed chunks survive untouched; the in-flight `.tmp` remains and
is reported as an interrupted chunk on the next scan. A restarted recorder
**resumes numbering and the session clock from the manifest** rather than
overwriting chunk 1.

---

## 9. Session Supervisor

`ClassSessionSupervisor` owns: `session_id`, `course`, `session_path`, start
time, the stop request and its reason, every worker's status/restarts/failures,
`audio_written_until`, `transcription_confirmed_until`, STT gap history and
reconnect count, and the finalization error list.

**Heartbeat** (every 5 s, in `class_capture.py`): renews the lifecycle lock
(`heartbeat_active_session`), renews the recorder's supervisor heartbeat
(`audio/supervisor.json`), polls `audio/recorder.json`, refreshes worker
statuses, and writes `health.json`. Live speaker evidence is checkpointed every
30 s to `speaker_roles_live.json`.

**Worker statuses:** `starting`, `recording`, `connected`, `active`, `tracking`,
`queued`, `recovering`, `degraded`, `offline`, `failed`, `stopped`, `disabled`.

**Restart behaviour.** A worker's disappearance changes only that worker's
status. The session id never changes — asserted across five simulated STT
losses and across the 2h30m torture run.

**Stop / finalization order:**

1. supervisor records the stop request;
2. heartbeat and restart tasks cancelled;
3. **recorder stopped** — current chunk finalized, manifest completed;
4. live-question path drained (bounded, 10 s answer-queue join);
5. live notes flushed and drained (bounded, `NOVA_CLASS_NOTES_DRAIN_SECONDS`, default 25 s);
6. speaker roles finalized, `speaker_roles.json` + live snapshot persisted,
   questions and Live Q&A re-labelled;
7. outcome resolved and written to `session.json`;
8. post-processing launched;
9. lifecycle lock released (`Stop-NOVA-Class.ps1` waits on this).

**Outcomes.** `completed` requires an explicit stop, healthy audio integrity, no
STT gaps or reconnects, no worker in a warning state, and no finalization error.
Otherwise `completed_with_warnings`; a failed audio worker or any finalization
error gives `failed`; `aborted` is available for an explicit abort. **A stop
that was never requested can never be reported as `completed`** — that is
precisely the lie the 2026-08-27 session told.

---

## 10. STT / Recovery

**Engine:** LiveKit Agents `AgentSession` with `inference.STT("deepgram/nova-3-general")`,
`diarize`, `punctuate`, `smart_format`, and up to 100 course keyterms. Unchanged
and still the verified path.

**Disconnect behaviour.** `live_session.on("close")` now fires a recovery
instead of ending the class: it records `STT_GAP_START` with the LiveKit close
reason, marks the STT worker `recovering`, and schedules a restart. The handler
is structurally forbidden from calling `finalize()` or `ctx.shutdown()` — a test
asserts that.

**Reconnect.** `restart_transcription()` builds a fresh `AgentSession` with a
fresh STT and re-registers all handlers, with linear backoff (2 s × attempt,
capped at 30 s) up to `NOVA_CLASS_STT_MAX_RESTARTS` (default 20). The session id,
the transcript journal, the speaker tracker, the question journal and the
recording are all untouched. After the maximum, the STT worker is marked
`offline` and the console says plainly that audio continues and the transcript
will be incomplete for that stretch.

**Gap detection.** The supervisor tracks `audio_written_until` (from the
recorder) and `transcription_confirmed_until` (from finalized segments).
`STT_GAP_START` records the audio position at the loss; `STT_GAP_END` records it
at the first transcript after recovery. `health.json` exposes every gap,
`transcript_lag_seconds`, `stt_reconnects` and `unrecovered_gaps`.

**Backfill status: NOT IMPLEMENTED — NEEDS VERIFICATION / FOLLOW-UP.**
The architecture makes it possible — the audio for every gap is on disk as
addressable chunks, and each gap carries exact start/end seconds — but no
automatic re-transcription of gap chunks is implemented. Every gap is therefore
recorded with `"backfilled": false` and counted in `unrecovered_gaps`. **Do not
assume transcript gaps repair themselves.** See §22 (P1).

---

## 11. Live Notes

**When they start.** The first batch closes on the earlier of 60 seconds of
lecture with ≥60 words, or 800 accumulated words. In practice the first note
appears within roughly 60–120 seconds of real speech. `live_notes.md` exists
from the moment the session opens, so there is always a file to watch.

**Batching strategy.** After the first batch: 75 seconds (`NOVA_CLASS_NOTES_INTERVAL_SECONDS`)
with ≥120 words, **or** 800 new words (`NOVA_CLASS_NOTES_WORD_TRIGGER`), **or**
an explicit flush at finalization. A single sentence never triggers a model call.

**Provider fallback.** Notes route through `route_class_prompt`, the same
Groq → OpenAI → Ollama order and the same dedicated class cloud budget the rest
of Class Intelligence uses.

**Queue / checkpoint.** Every batch is appended to `live_notes_queue.jsonl`
*before* any provider is contacted; `live_notes_state.json` records which
batches were actually folded in. A failure re-queues the batch, marks the worker
`degraded`, and rewrites `live_notes.md` so the status is visible in the file the
user is reading. On recovery the backlog drains. `restore_pending()` re-queues
anything a previous run persisted but never folded in. Nothing pending is ever
discarded.

**Merging.** The model returns a small JSON object of arrays; the worker merges
them into a deduplicated document (Key Concepts, Definitions, Professor
Explanations, Examples, Questions Asked, Answers/Clarifications, Important
Emphasis, Assignments/Deadlines, Items to Review) plus Current Topic and Topic
Progression. Unparseable output is treated as a failure, never as a note.

**A side fix.** `LectureContext.set_topic` and `TopicTracker.update` previously
had **zero production callers**, so `topics.jsonl` was empty in every real
session and Live Q&A always said "CURRENT TOPIC: not yet resolved". The notes
worker's topic callback now feeds both, so topics are captured live for the
first time.

**Final refinement.** Post-class processing is unchanged in shape and remains
the refinement pass: it consumes the complete transcript, session evidence,
questions, Q&A, speaker roles and course materials to produce the existing
canonical outputs (Lecture, Summary, Study, Questions, Evidence, Lecture
Timeline, Source Transcript, Presentation Outline, Presentation.pptx).

**`live_notes.md` is NOT one of those inputs yet.** Verified against the current
tree on 2026-08-28: `nova_capture/postprocess.py` and `nova_capture/evidence.py`
contain no reference to `live_notes`, so the live notes are written during class
and persisted in the raw session directory, but nothing downstream reads them.
Post-class generation therefore still starts from the transcript and session
evidence, not from what was already noted live. Making live notes an explicit
post-processing input is a **P1 follow-up (§22 #7)** and is deliberately not
implemented in this task. Until it lands, do not describe post-class output as a
refinement *of the live notes* — it is a refinement of the same underlying
evidence.

---

## 12. Speaker Intelligence

**Two deliberately separate answers.**

*Authoritative* (`resolve`) — what the transcript, questions and study documents
are labelled with. Unchanged and conservative: raw diarized ids during capture,
a decision only at finalization, only on strong multi-speaker evidence, and
`Unknown` preferred over a confident-but-wrong role. This rule exists because a
real 2026-08-23 lecture locked the first voice it heard as "Teacher".

*Live* (`live_assessment`) — what the status view shows during class, e.g.

```
00:20  Speaker 0 → Unknown              0.35
00:45  Speaker 0 → Probable Professor   0.63
02:00  Speaker 0 → Professor            0.91
```

**Roles:** Professor, Student, Guest Speaker, Unknown (`SpeakerRole.GUEST` added).

**Evidence** per speaker: cumulative words and share, turns and average turn
length, estimated speech time, first/last seen, longest turn, instructional
("course-running") language, guest language, questions addressed to the class,
and who speaks after whom (distinct responders).

**Scoring.** Professor score = 0.30 share + 0.20 monologue + 0.20 instructional
language + 0.15 early presence + 0.15 interaction, damped by total evidence and
by having seen fewer than two speakers. **Talk time alone can never earn
"Professor"**: with zero course-running language the score is hard-capped at
0.70, permanently in the "probable" band. Bands: ≥0.75 confident, 0.45–0.75
"Probable …", below that "Unknown".

**Guest speakers.** A speaker is guest-shaped only if they were **not** present
early (first seen after 5 minutes) **and** either used explicit guest language
twice or delivered a substantial presenting block. Guests are scored on a
separate *presenter* score (share + monologue + interaction) so they are not
penalised for arriving late or for not discussing homework — otherwise an
obvious guest presenter stayed "Unknown" for a whole hour. Guests are excluded
from professor candidacy **and from the dominance denominator**, so a professor
who hands an hour to a guest is still recognised as the professor. Verified in
the torture run: a guest who out-talked the professor for the last hour was
labelled Guest Speaker, and the professor kept the role.

**Bootstrap.** "Unknown" and "Probable …" are first-class outcomes. A speaker
with no evidence reports `stage: "no_evidence"` and confidence 0.0.

**Manual override.** `NOVA_CLASS_TEACHER_SPEAKER_ID` still wins immediately with
confidence 1.0.

**Persistence.** `speaker_roles_live.json` is checkpointed every ~30 s and marked
`kind: "live_provisional"`; `speaker_roles.json` (schema version 3) holds the
authoritative reconciliation at finalization and now carries both the final and
the live view per speaker.

**Limitations.** Within-session only. **No persistent biometric voice profile is
created** (§20). Diarization quality is Deepgram's; NOVA only interprets the ids
it is given. Instructional-language detection is English pattern matching, so an
unusual lecturing style may keep a real professor in the "probable" band — which
is the intended failure direction.

---

## 13. Pipecat Evaluation

**Version evaluated:** `pipecat-ai` **1.8.1** (published 2026-08-27), from PyPI
metadata and the current official documentation — not from assumptions.

**Why considered:** real-time audio frame pipelines, local audio transport,
first-class Deepgram STT, LiveKit transport, custom processors, observers,
parallel pipelines, and audio recording utilities.

**What was prototyped:** `nova_capture/pipeline.py` — a
`resolve_class_pipeline()` engine selector behind `NOVA_CLASS_PIPELINE`, a
`PipecatTranscriptionEngine` written against the current documented API
(`LocalAudioTransport`/`LocalAudioTransportParams`,
`DeepgramSTTService(settings=DeepgramSTTService.Settings(...))` — note
`live_options` is deprecated as of v0.0.105 — `Pipeline`/`PipelineTask`/
`PipelineRunner`, and a custom `FrameProcessor` forwarding `TranscriptionFrame`s
into NOVA's existing journals), and `describe_pipecat_support()`, which reports
what this machine is actually missing.

**Compatibility, measured on this runtime** (`pip install --dry-run`, nothing
installed):

| Check | Result |
| --- | --- |
| `pipecat-ai==1.8.1` core resolves on Python 3.14 / Windows | ✅ yes — 19 new packages |
| New transitive deps | numba 0.67.0, llvmlite 0.49.0, onnxruntime 1.24.4, sympy, nltk, resampy, soxr, regex, joblib, mpmath, … |
| Source builds required (core) | `docopt` (pure Python) |
| `pipecat-ai[deepgram,local,livekit]` resolves | ✅ yes — 21 packages |
| Source builds required (with `local`) | **`PyAudio 0.2.14` — no cp314 wheel; needs MSVC + PortAudio headers** |
| Direct Deepgram credential | **Not configured** — NOVA reaches Deepgram through LiveKit Inference and holds no Deepgram key |

**Advantages:** explicit frame-level pipeline with observers and parallel
branches; a transport-agnostic model; a documented Deepgram settings surface
including diarization and keyterms; would make alternate/local STT easier later.

**Disadvantages:** 21 additional packages including a JIT toolchain
(numba/llvmlite) and an ONNX runtime, added to a stack that is stable and about
to be used for a real class; its local-audio transport does not install cleanly
on this exact Python 3.14 Windows runtime; it would require provisioning and
storing a second speech credential; and NOVA's current LiveKit path is already
verified against real lectures.

**Benchmark results:** **NOT RUN.** No latency, accuracy, diarization, CPU, RAM,
reconnect, or long-session comparison was performed, because installing Pipecat
was judged too risky for this runtime before a real class. Any claim of a
Pipecat-vs-LiveKit measurement would be invented.

**FINAL DECISION: PILOT ONLY.**

Reasons: (1) the reliability problem this task existed to solve is solved by the
recorder process, not by the transcription framework — audio now survives
whatever the engine does, so Pipecat would buy pipeline flexibility, not
reliability; (2) the `local` transport does not install on this runtime without a
C toolchain; (3) adopting it needs a Deepgram credential NOVA does not have; and
(4) requirement 22 forbids replacing a working pipeline on a hypothesis. The
seam, the flag, the adapter and the support probe all ship, so a future
evaluation is configuration plus one `pip install`, not a rewrite. Requesting
`NOVA_CLASS_PIPELINE=pipecat` today falls back to LiveKit and states exactly
what is missing — a class never fails to record over a pilot.

---

## 14. Test Results

All commands run from `C:\Projects\AI Agent` with
`.\venv\Scripts\python.exe -m pytest`.

| Test | Command | Result | Notes |
| --- | --- | --- | --- |
| Durable audio | `pytest tests/test_nova_class_durable_audio.py -q` | **PASS — 13 passed** | Chunk rollover, valid WAV mid-session, manifest, frame-exact timestamps, partial/empty final chunk, in-progress vs orphaned `.tmp`, missing/truncated/gap/malformed detection, restart-resume, state file |
| 180-min simulation **at the production chunk default** | `pytest tests/test_nova_class_long_session.py -q` | **PASS — 13 passed** | Recorder built with no `chunk_seconds`, so the shipped 20 s default does the work: **exactly 540 chunks**, sequences 1..540 with none reused, 8,640,000 frames, last chunk ends at 10800.000000 s, drift < 1e-6 s, no self-stop, retained memory < 1 MB against 17.3 MB written and flat across both halves |
| Supervisor | `pytest tests/test_nova_class_supervisor.py -q` | **PASS — 12 passed** | Session id survives 5 STT losses; outcome resolution; unrequested stop ≠ `completed`; health/event journals; journal failure never raises |
| STT recovery + process isolation | `pytest tests/test_nova_class_recovery.py -q` | **PASS — 9 passed** | Stop-only-when-asked, stale stop ignored, dead device, orphan grace, max-duration guard, mic-open failure, **real subprocess crash test**, thread safety |
| Notes failure isolation | `pytest tests/test_nova_class_live_notes.py -q` | **PASS — 15 passed** | First batch ≤120 s, no per-sentence calls, durable queue survives restart, degraded status visible in the file, backlog drains on recovery, unusable output ≠ a note |
| Speaker roles | `pytest tests/test_nova_class_live_speakers.py -q` | **PASS — 10 passed** | 0.35→0.63→0.91 progression, live labels never leak into the transcript role, talk-time-alone capped, guest does not steal the professor, snapshot serializable |
| Pipecat | `pytest tests/test_nova_class_pipecat_adapter.py -q` | **PASS — 8 passed** (adapter never executed against a microphone) | Default is LiveKit, unknown value falls back loudly, blockers enumerated, no credential value ever exposed |
| Duplicate start / clean stop / status | `pytest tests/test_nova_class_lifecycle_v137.py -q` | **PASS — 12 passed** | Second start rejected, stop reaches the separate recorder, orphaned recorder still stoppable, status output, chunked + legacy audio verification |
| Fault isolation / torture | `pytest tests/test_nova_class_fault_isolation.py -q` | **PASS — 14 passed** | Full 2h30m scenario + structural guarantees on `class_capture.py`. Uses a **30 s test chunk size** (300 chunks) — see the chunk-size note below |
| Existing class suite | `pytest tests/test_nova_class_*.py -q` | **PASS — 217 passed** | Includes every pre-existing class test, unmodified |
| School / context / path suite | `pytest tests/test_nova_class_reliability_v12.py tests/test_nova_class_intelligence_v11.py tests/test_nova_course_knowledge_foundation.py tests/test_nova_path_authority.py -q` | **PASS — 49 passed** | — |
| Class capture suite | `pytest tests/test_nova_class_*.py -q` | **PASS — 222 passed in 78.98s** | — |
| Full NOVA suite | `pytest tests -q` | **PASS — 388 passed in 74.48s** | Baseline before this work: 282 passed |
| Real microphone / process acquisition | ad-hoc `DurableRecorderProcess` run, 12 s | **PASS** | Separate process acquired the real Windows microphone; startup 1.22 s; 5 valid chunks; integrity healthy; clean stop; **captured audio deleted immediately** |
| Real 150-min soak | `.\Test-NOVA-Class-Endurance.ps1 -Minutes 150` | **NOT RUN** | Requires a real class; see §16 |

**Torture scenario, as executed** (`tests/test_nova_class_fault_isolation.py`):

```
Logical duration:  2h 30m          Session IDs: 1
00:20  STT worker failure       →  audio continued, session not finalized
00:21  STT restart              →  transcription resumed, same session id
00:45  provider/network failure →  audio continued, notes queue persisted
01:10  notes provider still down→  audio "recording", >60 min recorded, notes "degraded", ≥1 batch queued
01:20  provider recovered       →  backlog drained, notes "active"
01:30  guest speaker appears    →  labelled Guest Speaker; professor kept the role
End    explicit stop            →  1 finalized session, 300 chunks, integrity healthy,
                                    outcome completed_with_warnings (1 unrecovered gap)
```

**Counts:** 388 passed, 0 failed, 0 skipped, 0 errors. New tests: 106.

### Chunk size used by each audio test

Production default is **20 seconds** (`NOVA_CLASS_AUDIO_CHUNK_SECONDS`, and
`audio_chunks.DEFAULT_CHUNK_SECONDS`). A three-hour class is therefore
**540 chunks**. Tests that use a different chunk size do so deliberately, and
this is what each one uses:

| Test module | Chunk size | Why | Chunks produced |
| --- | --- | --- | --- |
| `test_nova_class_long_session.py` | **20 s — the production default, taken from `DEFAULT_CHUNK_SECONDS` rather than passed in** | This is the test that has to match reality | **540** over 180 simulated minutes |
| `test_nova_class_fault_isolation.py` | 30 s (test-specific) | Fault injection is about *what happens to* the recording, not about chunk arithmetic; larger chunks keep a 2h30m scenario with live notes and speaker tracking under 30 s of wall clock | 300 over 150 simulated minutes |
| `test_nova_class_durable_audio.py` | 2 s (test-specific) | Rollover, manifests, and integrity detection need many boundaries in a few hundred milliseconds | 1–4 per test |
| `test_nova_class_recovery.py` | 2 s synthetic / 0.5 s in the real subprocess (test-specific) | The supervision loop and the real crash-survival test need chunks to appear within seconds | 2–8 per test |
| `test_nova_class_lifecycle_v137.py` | 2 s (test-specific) | Fixture only needs a few chunks to exist | 3 |
| Real microphone check (§17) | 3 s (ad hoc) | A 12-second device-open check | 5 |

Chunk length only affects how often the rollover path runs. Sequence numbering,
manifest records and timestamps are all frame-derived, so they are arithmetically
identical at any chunk size — which is why the shortened sizes are safe for the
mechanism tests. The one place the number itself matters is "how many chunks does
a real three-hour class produce", and that is now asserted at the production
default.

`test_nova_class_long_session.py` also asserts that
`audio_chunks.DEFAULT_CHUNK_SECONDS` is 20.0 **and** that `class_capture.py`
passes the same default, so the two cannot drift apart without the test failing.

The **sample rate** is scaled down in the simulations (800 Hz, or 400 Hz in the
torture run) purely to keep fixture disk usage sane. The real 16 kHz recorder is
exercised against a real microphone in §17.

---

## 15. Failed Tests

**No automated tests failed in the final run.**

Three genuine defects were found *by* the new tests during development and fixed
at the root rather than worked around:

1. **Chunk-boundary splitting** — a single oversized `write_pcm` landed entirely
   in the current chunk, so chunk duration depended on device block size instead
   of `chunk_seconds`. Fixed by splitting payloads at the boundary.
2. **Degraded notes were invisible** — `live_notes.md` still said "active"
   during a provider outage because the file was only rewritten on success.
   Fixed by refreshing the file on every status change.
3. **Guest presenters could not be identified** — the professor-shaped score
   penalised guests for arriving late and for not using course-running language,
   pinning an obvious guest at "Unknown". Fixed by scoring guests on a separate
   presenter score, and by removing guests from the dominance denominator.

A fourth issue was found and fixed while testing status output: an actively
recording session was reported as `Integrity: NEEDS REVIEW` for its whole
duration, because the in-flight `.tmp` chunk was treated as damage.

### 2026-08-28 follow-up run

One test failed during the follow-up full-suite run and was fixed at the root:

**`tests/test_phase1_vision_contract.py::test_no_active_screenshot_capture_backend`
— FAILED, then fixed.**

- *Observed:* `assert bad == []` failed with two paths under
  `.claude/worktrees/bold-jones-eebe42/` — `nova_guardian/ambient_vision.py`
  and `tools/vision.py`.
- *Root cause:* a git worktree of a **different branch** was checked out inside
  the project at `.claude/worktrees/bold-jones-eebe42`, pinned to commit
  `0bf3a8b` (2026-07-23) — which predates the retirement of Guardian's
  `ImageGrab` ambient-vision backend. `active_python_sources()` blocked
  `venv`, `Dashboard`, `.nova-backups` and friends but not `.claude`, so it
  walked that sibling checkout and reported its files as active NOVA source.
- *Not a regression:* the live tree is clean. Scanning every `.py` under the
  repository root with `.claude` excluded returns **zero** `ImageGrab` hits.
  Nothing in this task touched vision, Guardian, or `agent.py`.
- *Fix:* added `.claude` to the blocked set, with a comment explaining why. This
  is a scoping correction, not a weakened assertion — the contract still applies
  in full to every live NOVA source file, and it now also holds while a
  background worktree exists.
- *Status:* `tests/test_phase1_vision_contract.py` → 11 passed.

---

## 16. Tests Not Run

These are **not verified**. Do not treat them as working.

- **Real 150-minute wall-clock soak.** `REAL 150-MINUTE SOAK TEST: NOT RUN.`
- **A real lecture end-to-end on the new code.** No classroom run has happened
  since these changes. Live Q&A latency, Deepgram accuracy, Windows toast
  notifications and post-class output quality are unchanged in design but
  unexercised on 1.3.7.
- **Live STT reconnect against real LiveKit/Deepgram.** The restart path is
  asserted structurally and simulated at the supervisor level; it has never
  reconnected to a real Deepgram stream.
- **Transcript backfill.** Not implemented at all.
- **Pipecat execution.** The adapter has never run. No Pipecat benchmark exists.
- **Inline recorder fallback on real hardware.** Only the process recorder was
  exercised against the real microphone.
- **Multi-hour disk-pressure behaviour**, USB/Bluetooth microphone hot-unplug,
  sleep/hibernate resume, and battery exhaustion.
- **Post-class generation on a 1.3.7 session.** The post-processing code is
  unchanged, but no full pipeline has run end to end since the rewiring.
- **`Get-NOVA-Class-Status.ps1 -Watch`** was not executed interactively.

---

## 17. Performance Results

Measured on this machine, this Python, today.

| Metric | Value | How measured |
| --- | --- | --- |
| Recorder process RSS | **9.5 MB, flat** over 12 s of real capture | `psutil` on the recorder pid |
| Recorder process CPU | **~0%** (1 s sample) | `psutil.cpu_percent` |
| Recorder startup to first healthy report | **1.22 s** | `DurableRecorderProcess.start()` |
| Memory retained over a simulated 180-minute session | **< 1 MB** against 17.3 MB written (< 1/10th) | `tracemalloc` |
| Timestamp drift at 180 minutes | **< 1e-6 s** | manifest assertions |
| Disk usage | **115.2 MB/hour**; **0.35 GB per 3-hour class**; 540 chunks | 16 kHz × 16-bit × mono |
| Chunk size | 640 KB per 20 s chunk | measured (96,044 B per 3 s chunk × ratio) |
| Simulated 180-minute session at the production 20 s default (10,800 write calls, **540 chunks**) | 14.7 s wall (0.7 s for the recorder alone) | pytest |
| Simulated 2h30m torture run (9,000 write calls, 300 chunks at a 30 s test chunk size, live notes, speakers) | ~29 s wall | pytest |
| Full test suite | 74.5 s | pytest |
| STT latency / accuracy | **NOT MEASURED** | unchanged code path, no new run |
| Note latency (real providers) | **NOT MEASURED** | injected generator in tests |
| Pipecat vs LiveKit | **NOT MEASURED** | Pipecat not installed |

---

## 18. Reliability Guarantees

**VERIFIED by automated tests (and, where noted, by a real hardware check):**

- audio chunks are persisted, fsynced and atomically published **before** any AI
  processing touches them;
- every completed chunk is a valid, playable WAV while the class is still running;
- one logical session id survives repeated transcription-worker loss and restart;
- a **hard kill of the intelligence process does not stop the recording** —
  proven with a real subprocess that was killed while the recorder kept writing
  (Windows);
- the durable recorder acquires the real Windows microphone from its own process
  (real hardware check);
- a simulated 180-minute session produces a continuous chunk sequence with
  frame-exact timestamps, no self-stop, and no memory growth with duration;
- a provider outage leaves audio, transcript and session untouched, keeps note
  evidence durably queued, and drains it on recovery;
- a stop that was never requested can never be reported as `completed`;
- a finalization error can never be reported as success;
- an interrupted or missing chunk is detectable on the next scan;
- a restarted recorder resumes numbering instead of overwriting the lecture;
- an orphaned recorder can still be stopped after the intelligence process dies;
- duplicate start is still rejected, leaving exactly one logical session;
- a guest presenter who out-talks the professor does not take the professor role.

**NEEDS REAL-WORLD VERIFICATION (explicitly NOT guaranteed):**

- an uninterrupted 150-minute classroom microphone run;
- real STT reconnection against live LiveKit Inference / Deepgram;
- live-note quality and latency with real providers in a real lecture;
- speaker-role accuracy on a real multi-speaker class under 1.3.7;
- post-class generation quality from a 1.3.7 session;
- behaviour on sleep/hibernate, device hot-unplug, or a full disk.

### Runtime acceptance checklist

**Current status: `IMPLEMENTED + AUTOMATED TESTS PASSED`.**
**This is NOT `VERIFIED FOR REAL CLASS USE`.** Every item below must pass on the
real runtime before that phrase may be used.

| # | Requirement | Status |
| --- | --- | --- |
| 1 | Real 20–30 minute rehearsal with a live class capture | NOT RUN |
| 2 | Startup banner confirms `AUDIO ISOLATION: SEPARATE PROCESS` | NOT VERIFIED |
| 3 | LiveKit and the separate recorder can hold the microphone **at the same time** | NOT VERIFIED — the 12 s check in §17 proved the recorder process opens the device, but not while a LiveKit console session is also capturing |
| 4 | `Get-NOVA-Class-Status.ps1 -Watch` run for the duration of the rehearsal | NOT RUN |
| 5 | Live transcript, live notes, speaker tracking and audio chunks all observed advancing | NOT VERIFIED |
| 6 | No stale/orphan Class Capture or recorder process remains after a clean stop | NOT VERIFIED |
| 7 | Post-class generation completes and writes the session output folder | NOT VERIFIED on 1.3.7 |
| 8 | Real 150-minute endurance run (`.\Test-NOVA-Class-Endurance.ps1 -Minutes 150`) | NOT RUN |
| 9 | Real LiveKit / Deepgram STT reconnect | **NEEDS VERIFICATION** — simulated and structurally asserted only |
| 10 | Transcript gap backfill | **NOT IMPLEMENTED** — gaps are recorded `backfilled: false` (§10, §22 P1 #4) |

Items 1–8 are runtime observations. Item 9 stays `NEEDS VERIFICATION` until a
real provider drop is survived in a real class. Item 10 is a feature that does
not exist and must not be described as working.

---

## 19. Known Limitations

1. **No transcript backfill.** Audio for a gap is on disk and addressable, but
   nothing re-transcribes it. Gaps are recorded as `backfilled: false`.
2. **The intelligence process is still one process.** STT, questions, Live Q&A,
   live notes and speaker tracking share an event loop. A hard crash there loses
   in-flight *intelligence* work (not audio, not the persisted transcript, not
   queued note evidence).
3. **A crash-shutdown leaves the recorder running on purpose**
   (`NOVA_CLASS_KEEP_AUDIO_ON_CRASH`, default on). It stops on an explicit stop,
   or after the orphan grace window (`NOVA_CLASS_RECORDER_ORPHAN_SECONDS`,
   default 3600 s). Until then the microphone is held and disk keeps filling at
   115 MB/hour.
4. **Post-processing is deferred after a crash-shutdown**, because the recording
   is still growing. The user must stop the class to get notes.
5. **The inline fallback has no process isolation.** It says so in its health
   payload and in the startup banner, but if the process recorder cannot start,
   the 2026-08-27 failure mode partially returns for that session.
6. **`audio.wav` is gone for new sessions.** Anything expecting a single file
   must read `audio/manifest.jsonl` (or concatenate chunks). `end_class_capture`
   accepts both; older sessions are untouched and still verify.
7. **Restart backoff can lose up to ~30 s of transcript per attempt.** Audio is
   unaffected.
8. **STT restart is untested against a real provider.**
9. **Speaker inference is English-pattern-based and within-session only.**
10. **The Pipecat adapter is unverified code.** It is guarded and unreachable by
    default, but it has never been executed.
11. **`CAPTURE_VERSION` stayed in the 1.3.x series** (1.3.7) because
    `test_nova_class_intelligence_v13` and `test_nova_class_quality_v133` assert
    the literal substrings `'CAPTURE_VERSION = "1.3'` / `'"1.3.'`. This
    pre-existing brittleness (already flagged in `ROADMAP.md`) will block a
    1.4.0 bump; it was not fixed here to avoid touching unrelated tests.
12. **Chunk duration was chosen by analysis, not by an A/B measurement** on real
    lecture hardware.

---

## 20. Security / Privacy Review

- **No secrets exposed.** `.env` and `.env.local` were never opened, printed, or
  copied. Sensitive credential material exists in this repository and was
  intentionally not displayed. `describe_pipecat_support()` reports only
  *whether* `DEEPGRAM_API_KEY` is set, never its value — asserted by a test.
- **Raw recordings remain outside Git.** All class evidence stays under
  `%LOCALAPPDATA%\NOVA\ClassCapture\`. Nothing was moved into the repository or
  into any vault. `git status` contains no audio, transcript, or session file.
- **No private recordings committed** — and nothing was committed at all.
- **No private classroom audio used as a test fixture.** Every test uses
  synthetic PCM (`b"\x01\x00"` blocks) and synthetic speaker text.
- **Real-microphone check was minimal and cleaned up.** A 12-second device-open
  check was run to prove the separate process can acquire the microphone; the
  captured audio was deleted immediately and was never read, transcribed, or
  copied.
- **The 2026-08-27 session was inspected for metadata only** — durations,
  counts, statuses, WAV frame counts. No transcript or audio content was read or
  reproduced anywhere.
- **No Valo files touched.** No dashboard or Valo code was read, imported, or
  modified.
- **No persistent biometric professor profile created.** All speaker inference
  is within-session, derived from diarized ids, word counts, timing and language
  patterns. No voice embeddings are computed or stored. Cross-class voice
  identification remains an explicitly opt-in future feature (§23).
- **New files written per session:** `audio/*.wav`, `audio/manifest.jsonl`,
  `audio/recorder.json`, `audio/supervisor.json`, `audio/recorder.stop`,
  `health.json`, `events.jsonl`, `class_capture.log`, `live_notes.md`,
  `live_notes_queue.jsonl`, `live_notes_state.json`, `speaker_roles_live.json` —
  all inside the existing session directory, all containing only what Class
  Capture already intentionally records.
- **One new control file:** `_control/last_session.json` (session id, course,
  path, start time) so an orphaned recorder can be stopped. No secrets.

---

## 21. Rollback Plan

Nothing was committed, so rollback is entirely local. **Do not run
`git reset --hard` or `git clean -fd`** — that would destroy the unrelated
`nova_knowledge/`, `nova_learning/` and `agent.py` work that was already in the
tree.

**Full rollback of this task only:**

```bash
git checkout -- class_capture.py nova_capture/control.py nova_capture/intelligence.py nova_capture/microphone.py nova_capture/models.py nova_capture/speakers.py nova_capture/__init__.py tools/class_capture.py Get-NOVA-Class-Status.ps1
```

```bash
rm nova_capture/audio_chunks.py nova_capture/live_notes.py nova_capture/pipeline.py nova_capture/recorder_process.py nova_capture/status.py nova_capture/supervisor.py scripts/nova_class_endurance.py Test-NOVA-Class-Endurance.ps1 tests/test_nova_class_durable_audio.py tests/test_nova_class_fault_isolation.py tests/test_nova_class_lifecycle_v137.py tests/test_nova_class_live_notes.py tests/test_nova_class_live_speakers.py tests/test_nova_class_long_session.py tests/test_nova_class_pipecat_adapter.py tests/test_nova_class_recovery.py tests/test_nova_class_supervisor.py docs/NOVA-CLASS-CAPTURE-RELIABILITY-REPORT.md
```

That returns Class Capture to 1.3.6 exactly and leaves `agent.py`,
`nova_knowledge/`, `nova_learning/`, `scripts/nova_knowledge_*` and the
knowledge/learning tests untouched.

**Partial rollbacks, no code changes needed:**

| Behaviour | How to disable |
| --- | --- |
| Separate recorder process | `NOVA_CLASS_RECORDER_MODE=inline` |
| Live notes | `NOVA_CLASS_LIVE_NOTES=0` |
| Keeping audio alive after a crash-shutdown | `NOVA_CLASS_KEEP_AUDIO_ON_CRASH=0` |
| STT auto-restart | `NOVA_CLASS_STT_MAX_RESTARTS=0` |
| Pipecat | already off; it requires `NOVA_CLASS_PIPELINE=pipecat` |

Sessions recorded under 1.3.6 are unaffected: nothing rewrites, moves, or
migrates existing raw sessions.

---

## 22. Recommendations

### P0 — before the next real class

1. **Run a 20–30 minute rehearsal with the endurance monitor.**
   Benefit: exercises the whole new path — process recorder, health file, status
   script, notes worker, clean stop — before a lecture depends on it.
   Risk: none (it only records you). Complexity: trivial. Dependency: none.
   Architecture change: no.
2. **Confirm the recorder process coexists with LiveKit's console audio on your
   machine.** The 12-second check proved the device opens, but not while a
   LiveKit console session is also capturing. If it falls back, the banner will
   say `IN-PROCESS FALLBACK (no crash isolation)` — that is the one line to look
   at when the class starts.
   Risk: if it always falls back, crash isolation is lost and P0 #3 becomes
   urgent. Complexity: trivial. Architecture change: no.
3. **Watch `Get-NOVA-Class-Status.ps1 -Watch` for the first ten minutes** of the
   next real class, and stop with `Stop-NOVA-Class.ps1`, not by closing the
   window.

### P1 — soon

4. **Implement transcript gap backfill.** Re-transcribe the exact chunks covering
   each `STT_GAP_START`/`STT_GAP_END` range with Deepgram's pre-recorded API and
   splice with a `backfilled: true` provenance marker.
   Benefit: turns the last remaining transcript loss into a delay. Risk: medium
   — ordering and de-duplication against live segments. Complexity: medium.
   Dependency: a batch transcription endpoint. Architecture change: no (the gap
   records and addressable chunks already exist).
5. **Run the real 150-minute soak** (§24). Benefit: the only thing standing
   between "tests pass" and `VERIFIED FOR REAL CLASS USE`. Risk: none.
6. **Add a notification when the STT worker goes `offline`.** Right now a long
   transcription outage is visible only in the status view.
   Benefit: the user can intervene while the class is still happening. Risk:
   low. Complexity: low (`nova_capture/notifications.py` already exists).
7. **Have post-processing consume `live_notes.md`.** The file is written and
   available but the generation prompts do not read it yet.
   Benefit: post-class notes become genuine refinement of live notes. Risk: low.
   Complexity: low. Architecture change: no.
8. **Fix the `CAPTURE_VERSION` substring assertions** in
   `test_nova_class_intelligence_v13` and `test_nova_class_quality_v133` to use
   the parsed-minimum-version approach already used by
   `test_nova_class_turn_aware_v134`. Benefit: unblocks a 1.4.0 bump and removes
   a test that would silently pass on a 1.3.3 regression. Risk: none.

### P2 — future

9. **Auto-recover the recorder process** if it dies unexpectedly mid-class
   (resume-from-manifest already makes this safe). Complexity: low-medium.
10. **A real Pipecat benchmark** in a throwaway venv — latency, accuracy,
    diarization, CPU/RAM, reconnect, long-session stability — before revisiting
    §13. Risk: none if isolated from the working venv.
11. **Opt-in cross-class professor voice recognition** (§23) — explicitly
    requires separate approval.
12. **Compress finished chunks** (FLAC) to cut 115 MB/hour by roughly half.
    Risk: must never touch a chunk until the class is finalized.

---

## 23. Suggested Future Features

Suggestions only; none of these were implemented.

- **Opt-in persistent professor voice recognition** — cross-class identification
  from a stored embedding. Explicitly deferred; requires separate approval and a
  clear consent and deletion story.
- **Schedule-triggered capture** — NOVA offers to start recording when a verified
  meeting begins, and never starts silently.
- **Automatic slide synchronisation** — align `capture_screen` frames or a slide
  export with the lecture timeline.
- **Speaker correction UI** — let the user say "Speaker 1 is the professor" mid
  class and re-render all derived labels.
- **Live transcript / notes UI** — a small always-on-top window instead of a
  PowerShell watch loop.
- **Confidence visualisation** — show the live speaker confidence curve after
  class as a diagnostic.
- **Automatic transcript gap repair** — the productised form of P1 #4.
- **Local Whisper fallback** — transcribe from persisted chunks with no network
  at all, which the chunked format now makes straightforward.
- **Audio-device failover** — detect a dead device and switch to the next input
  rather than ending the recording.
- **Battery and storage warnings** — warn at class start if the disk cannot hold
  three hours (0.35 GB) or the battery cannot last the sitting.
- **Class-end detection that never stops without confirmation** — notice a long
  silence and *ask*, never act.

---

## 24. Exact User Commands

All from `C:\Projects\AI Agent`.

**Start a class**

```powershell
.\Start-NOVA-Class.ps1 -Course COP3710
```

Or, in normal conversation with NOVA: *"NOVA, record my class."* — Class Capture
is a capability of the one agent, not a separate mode.

**Check status (one shot)**

```powershell
.\Get-NOVA-Class-Status.ps1
```

**Watch health live during class**

```powershell
.\Get-NOVA-Class-Status.ps1 -Watch -IntervalSeconds 10
```

**Machine-readable status**

```powershell
.\Get-NOVA-Class-Status.ps1 -Json
```

**Watch the transcript**

```powershell
Get-Content -Wait -Encoding UTF8 "$env:LOCALAPPDATA\NOVA\ClassCapture\COP3710\<SESSION_ID>\transcript.txt"
```

**Watch the live notes**

```powershell
Get-Content -Wait -Encoding UTF8 "$env:LOCALAPPDATA\NOVA\ClassCapture\COP3710\<SESSION_ID>\live_notes.md"
```

**Stop the class**

```powershell
.\Stop-NOVA-Class.ps1
```

**Run the reliability tests**

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_nova_class_durable_audio.py tests/test_nova_class_long_session.py tests/test_nova_class_supervisor.py tests/test_nova_class_recovery.py tests/test_nova_class_live_notes.py tests/test_nova_class_live_speakers.py tests/test_nova_class_pipecat_adapter.py tests/test_nova_class_fault_isolation.py tests/test_nova_class_lifecycle_v137.py -q
```

**Run every class test**

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_nova_class_*.py -q
```

**Run the whole NOVA suite**

```powershell
.\venv\Scripts\python.exe -m pytest tests -q
```

**Run the real endurance soak (start a class first, then run this beside it)**

```powershell
.\Test-NOVA-Class-Endurance.ps1 -Minutes 150
```

**Inspect a finished session's audio integrity**

```powershell
.\venv\Scripts\python.exe -m nova_capture.status --session "$env:LOCALAPPDATA\NOVA\ClassCapture\COP3710\<SESSION_ID>"
```

**Switch the transcription pipeline** (LiveKit is the default and the verified path)

```powershell
$env:NOVA_CLASS_PIPELINE = "pipecat"; .\Start-NOVA-Class.ps1 -Course COP3710
```

Pipecat is not installed, so this currently falls back to LiveKit and prints why.

**Configuration reference (all optional)**

| Variable | Default | Effect |
| --- | --- | --- |
| `NOVA_CLASS_RECORDER_MODE` | `process` | `inline` disables process isolation |
| `NOVA_CLASS_AUDIO_CHUNK_SECONDS` | `20` | Rolling chunk length |
| `NOVA_CLASS_RECORDER_ORPHAN_SECONDS` | `3600` | How long recording outlives a lost supervisor (`0` = forever) |
| `NOVA_CLASS_MAX_RECORDING_MINUTES` | `0` | Opt-in hard cap; `0` = no cap |
| `NOVA_CLASS_KEEP_AUDIO_ON_CRASH` | on | Keep recording when shutdown was not a user stop |
| `NOVA_CLASS_STT_MAX_RESTARTS` | `20` | Transcription restart attempts |
| `NOVA_CLASS_LIVE_NOTES` | on | Live notes worker |
| `NOVA_CLASS_NOTES_INTERVAL_SECONDS` | `75` | Note batch interval |
| `NOVA_CLASS_NOTES_WORD_TRIGGER` | `800` | Note batch word budget |
| `NOVA_CLASS_NOTES_DRAIN_SECONDS` | `25` | Note drain budget at stop |
| `NOVA_CLASS_PIPELINE` | `livekit` | Transcription engine |
| `NOVA_CLASS_TEACHER_SPEAKER_ID` | unset | Manual professor override |

---

_Status: **IMPLEMENTED + AUTOMATED TESTS PASSED** (388 passed / 0 failed /
0 skipped). **NOT `VERIFIED FOR REAL CLASS USE`** — that phrase requires every
item in the §18 runtime acceptance checklist to pass on the real runtime,
including the real 150-minute endurance run. Real LiveKit/Deepgram STT reconnect
remains NEEDS VERIFICATION; transcript gap backfill remains NOT IMPLEMENTED._
