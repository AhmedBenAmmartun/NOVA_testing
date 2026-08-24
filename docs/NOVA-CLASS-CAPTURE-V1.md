# NOVA Class Intelligence V1.3 — Capture, Live Q&A, and Study Outputs

## Release intent

V1.3 keeps one authoritative Class Capture architecture and adds the first
complete intelligence layer on top of the evidence pipeline. Raw recording and
transcription are always finalized independently of AI answering, note
generation, or presentation generation.

The release is designed so a model/provider failure can reduce intelligence
features without losing the lecture recording.

## Authoritative architecture

- `class_capture.py` — LiveKit/STT orchestration and class-session coordination
- `nova_capture/` — WAV/session lifecycle, transcript, speaker evidence,
  questions, live Q&A, post-class processing, presentation generation
- `nova_runtime/` — generic managed background jobs
- `nova_school/` — course registry/resolution, course vocabulary, materials,
  Downloads organization, class/session context

There is no second capture runtime and no second microphone/session owner.

## Raw/private session storage

Raw evidence stays outside Git and outside the Vault:

`%LOCALAPPDATA%\NOVA\ClassCapture\<COURSE>\<SESSION-ID>\`

A V1.3 session can contain:

- `session.json`
- `audio.wav` — 16 kHz, mono, 16-bit when local WAV capture is available
- `transcript.jsonl` — authoritative machine transcript
- `transcript.txt` — derived readable transcript
- `questions.jsonl`
- `markers.jsonl`
- `topics.jsonl`
- `speaker_roles.json`
- `attachments.jsonl`
- `context_sources.json`
- `Live Q&A.md`
- `postprocess.json`
- `Materials\` — session-specific copied attachments

Raw `speaker_id` values remain evidence even after generic role inference.

## Polished class knowledge

Finished human-readable outputs are written to:

`NOVA Vault\Knowledge\Classes\<COURSE>\Sessions\<DATE>\<SESSION>\`

V1.3 produces:

- `Lecture.md`
- `Summary.md`
- `Study.md`
- `Questions.md`
- `Source Transcript.md`
- `Evidence.md`
- `Presentation Outline.md`
- `Presentation.pptx`

AI-generated documents are grounded in transcript evidence, logged Q&A, and
available course/session materials. If specialist models are unavailable,
V1.3 writes deterministic evidence/transcript fallbacks instead of deleting or
invalidating the raw session.

## Start / status / stop

Start with a known course:

```powershell
.\Start-NOVA-Class.ps1 -Course CEN4065
```

If verified meeting times are configured, `-Course` can be omitted when exactly
one scheduled class resolves.

Status:

```powershell
.\Get-NOVA-Class-Status.ps1
```

Stop cleanly:

```powershell
.\Stop-NOVA-Class.ps1
```

or from anywhere:

```powershell
& "C:\Projects\AI Agent\Stop-NOVA-Class.ps1"
```

Do not use Ctrl+C on the current legacy LiveKit console path. V1.3 keeps the
V1.2 targeted stop request, waits for WAV/transcript finalization, and only then
closes the verified legacy launcher process.

## Lifecycle/recovery guarantees

V1.3 includes:

- duplicate-start protection;
- active-session ownership state;
- heartbeat-based stale-session cleanup;
- stop requests targeted to one session ID;
- no stale stop request when no class is active;
- source-safe finalization before outer-console cleanup;
- separate post-class processing state in `postprocess.json`;
- manual regeneration of notes if post-processing fails.

Regenerate the latest class outputs:

```powershell
.\Generate-NOVA-Class-Notes.ps1
```

or specify a raw session path:

```powershell
.\Generate-NOVA-Class-Notes.ps1 -Session "C:\...\ClassCapture\CEN4065\<session>"
```

## Speech recognition and noise handling

The capture path preserves the real runtime already exercised in V1.1/V1.2:

- Deepgram Nova-3 through LiveKit Inference;
- streaming speaker diarization;
- raw `speaker_id` preservation;
- Nova-3 course-specific `keyterm` prompting;
- punctuation/smart formatting;
- `ai_coustics` QUAIL voice enhancement;
- local WAV backup independent of STT.

The current LiveKit Inference configuration keeps `diarize=True` because that
is the documented and previously live-tested streaming parameter in this NOVA
environment. A future diarizer-model migration must be benchmarked on real
lecture audio before replacing the verified path.

## Teacher / student inference

V1.3 does **not** assume `speaker 0 = teacher` and does **not** assume the first
voice is the professor.

It observes per-speaker lecture evidence and only promotes one raw speaker ID to
`Teacher` after a clear dominance threshold is reached. Other observed voices
then receive stable generic labels such as `Student 1`, `Student 2`, etc.

If confidence is insufficient, the role stays `Unknown`.

For a manually verified class, an explicit raw speaker override is available:

`NOVA_CLASS_TEACHER_SPEAKER_ID=<raw speaker id>`

This is an in-session generic role mapping, not biometric identity recognition.

## Question detection and live answers

V1.3 reconstructs fragmented STT questions before answering them and also
recognizes common question forms even when STT omits a final `?`.

Example fragments:

- `What is the difference between`
- `aggregation`
- `and composition?`

become one stored question.

Common classroom-management filler such as `Any questions?` is not sent to the
answer model.

For a real question, NOVA uses:

1. the recent lecture transcript;
2. current course/session material excerpts;
3. prior class notes when available;
4. NOVA's existing specialist model router.

The answer is:

- shown as a Windows notification when available;
- logged to `Live Q&A.md`;
- written back into `questions.jsonl`;
- available to the post-class study documents.

Live answering is failure-safe: a provider failure never stops capture.

## Materials and attachments

Course-wide materials live under:

`NOVA Vault\Knowledge\Classes\<COURSE>\Materials\`

At class start, NOVA performs a bounded one-time scan of recent Downloads and
copies only high-confidence files classified to the current course. Originals
are never moved or deleted.

A session-specific file can be attached while class is active:

```powershell
.\Add-NOVA-Class-Attachment.ps1 -Path "C:\path\to\slides.pptx"
```

Or attach to a completed raw session:

```powershell
.\Add-NOVA-Class-Attachment.ps1 -Path "C:\path\to\slides.pptx" -Session "C:\...\session"
```

Supported context extraction includes PDF, PPTX, DOCX, TXT, Markdown, and CSV.
Legacy Office/spreadsheet files remain safely classifiable by filename even when
local text extraction is unavailable.

## Post-class evidence pipeline

V1.3 does not send one giant unbounded lecture prompt to a model.

The pipeline is:

1. load authoritative transcript/Q&A/speaker mapping;
2. split transcript into bounded chunks;
3. extract grounded evidence per chunk;
4. merge/deduplicate evidence;
5. combine with related course/session materials;
6. generate separate study documents;
7. create a presentation outline;
8. build a real `.pptx` recap deck;
9. preserve `Source Transcript.md` deterministically from the raw JSONL.

The extraction prompt explicitly forbids inventing professor statements,
deadlines, grade policies, exam hints, definitions, or page references.

## Feature controls

Defaults are enabled for the requested Class Intelligence workflow:

- `NOVA_CLASS_LIVE_ANSWERS=1`
- `NOVA_CLASS_POSTPROCESS=1`
- `NOVA_CLASS_ANSWER_POPUP=1`

Optional:

- `NOVA_CLASS_TITLE=<session title>`
- `NOVA_CLASS_TEACHER_SPEAKER_ID=<verified raw speaker id>`

No new provider key is required by Class Intelligence itself. It reuses NOVA's
existing specialist model router/provider configuration.

## Dependency

Presentation generation requires:

`python-pptx>=1.0,<2`

The V1.3 installer checks/installs this dependency before modifying source.

## Definition of done

Automated tests prove code-level behavior, not classroom quality. After V1.3 is
installed, the release remains **NEEDS LIVE VERIFICATION** until the acceptance
flow confirms:

- real microphone/WAV capture;
- real Deepgram transcript;
- multiple-speaker separation where possible;
- question reconstruction;
- live answer notification/logging;
- clean stop and outer-console exit;
- post-class notes completion;
- presentation generation;
- correct Vault/raw storage paths.

Accent, terminology, and speaker-role quality must then be benchmarked against
representative real lecture recordings before being called tuned/production
quality.
