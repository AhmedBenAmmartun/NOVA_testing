# NOVA Class Capture V1 — Foundation

## Status

Foundation only. This stage does **not** activate the microphone or record a
real class yet.

It adds the tested runtime/storage primitives needed for Class Capture without
rewiring the current realtime NOVA session.

## Local raw-session storage

Default:

`%LOCALAPPDATA%\NOVA\ClassCapture\<course>\<session-id>\`

Raw class audio must remain outside Git and outside the Obsidian Vault.

Planned session artifacts:

- `audio.wav`
- `transcript.jsonl`
- `markers.jsonl`
- `questions.jsonl`
- `topics.jsonl`
- `session.json`

## Second Brain destination

Final human-readable products will later be saved under the existing NOVA Vault
in a class knowledge hierarchy, for example:

`Knowledge/Classes/<course>/<date - topic>/`

Products:

- Class Notes.md
- Class Summary.md
- Questions Asked.md
- Study Guide.md
- Flashcards.md
- Quiz.md
- Presentation Outline.md

Raw audio will not be copied into the Vault by default.

## Speaker intelligence

Planned speaker labels:

- professor
- student
- user
- unknown

Speaker identity is an estimate unless explicitly known. NOVA must never invent
a specific student's identity.

## Runtime boundary

`nova_runtime` is general lifecycle/background infrastructure.

`nova_capture` contains lecture-specific state, journals, local storage, topic
context, question records, markers, and the WAV storage primitive.

This avoids turning Class Capture into a hard-coded conversational mode.

## Next implementation slice

Attach the user's explicitly enabled classroom microphone track to
`LocalWaveRecorder` as a cancellable `nova_runtime` background job.

Recording must:

- require explicit start;
- show visible recording state;
- allow pause/resume/stop;
- never silently upload;
- safely close on cancellation/shutdown;
- not cause NOVA to answer the lecturer;
- preserve typed NOVA chat while capture runs.
