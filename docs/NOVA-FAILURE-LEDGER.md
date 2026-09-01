# NOVA Failure Ledger

Durable record of engineering failures, their verified root causes, and the
reusable lesson each one bought. Append only — a fixed entry stays, because the
value is the lesson, not the status.

Format per entry: what was attempted, what failed, the evidence, the root cause,
the **assumption that was wrong**, the fix, how the fix was verified, and the
reusable rule. An entry without evidence is a story, not a lesson.

---

## F-001 — Post-class processing died and reported itself healthy for 8 hours

**Date** 2026-08-31 · **Severity** high · **Status** fixed

**Attempted.** Generate lecture notes for a real COT3400 session after class.

**Failed.** No notes were produced. `Sessions/` was never created in the vault.

**Evidence.** `postprocess.json` read `{"status": "running", "error": null,
"pid": 18064}` with `started_at` 13:01:11. At 20:59 the same file was unchanged;
`Get-Process -Id 18064` returned nothing. The failure was invisible until
someone went looking for the notes.

**Root cause.** The status file was written by the process it described. A
process that is killed, power-cycled, or reaped never runs its `except` block,
so `status: "running"` was the last thing ever written and stayed true-looking
forever.

**Wrong assumption.** *A process can be relied on to report its own death.* It
cannot. Every crash-reporting mechanism that lives inside the crashing process
has this hole.

**Fix.** Liveness resolved by the **reader**, not the writer.
`read_postprocess_status()` re-checks the recorded process identity (pid **and**
process create time) and reports `interrupted` when the owner is gone.

**Verified.** Against the real stale file, which reinterpreted correctly —
including the backwards-compatible path, since that file predated the identity
fields entirely. 10 tests.

**Reusable rule.** **A record may not be the sole witness to its own liveness.**
When a file asserts that something is running, the reader must independently
confirm it. Store pid *and* create time; the OS recycles PIDs.

---

## F-002 — `session.json` and `health.json` described the same session differently

**Date** 2026-08-31 · **Severity** medium · **Status** fixed

**Attempted.** Check capture health during a live lecture.

**Failed.** `session.json` reported `audio_chunks: 0`, `recorder_mode: "none"`,
`audio_integrity_ok: false` while `health.json` simultaneously reported 84
chunks from a healthy isolated recorder process.

**Evidence.** Both files read from the same live session directory, minutes
apart, disagreeing on every count.

**Root cause.** Those fields are *finalization outputs* stored in a struct that
is written from session start. Before `finalize()` runs they hold dataclass
defaults. Nothing distinguished "measured as zero" from "never measured".

**Wrong assumption.** *A default value is a safe placeholder.* It is not, when
the field's type cannot express "unknown". `audio_integrity_ok: false` reads as
*the recording is damaged*; it meant *nobody has checked*.

**Fix.** `metrics_finalized` flag plus `session_metrics()` as the only
sanctioned reader — session.json when finalized, health.json when live, `None`
when genuinely unmeasured. Pre-flag sessions stay trusted when stopped, so
historical measurements are not discarded.

**Verified.** Against the real 2026-08-31 session, which carries no flag and
resolved correctly (201 chunks, 4005.07s, 729 segments). 9 tests.

**Reusable rule.** **`None` and zero are different claims.** If a field can be
unmeasured, its type must be able to say so. A boolean that defaults to `false`
cannot represent "unknown" and will be read as a negative finding.

---

## F-003 — Unconfirmed code execution via `open_file_or_folder`

**Date** 2026-08-31 · **Severity** critical · **Status** fixed

**Attempted.** Security threat-model of tool authority ahead of worker
execution.

**Failed.** Found a live chain giving NOVA arbitrary code execution with no user
confirmation.

**Evidence.** `web_download` registered `PermissionLevel.REVERSIBLE`
(`tools/web.py:41`) → the permission engine executes it with no prompt → writes
to `~/Downloads`, which is in `SAFE_DIRS` → `open_file_or_folder` calls
`os.startfile(path)` (`tools/files.py:284`) with no extension check → Windows
runs it. Both capabilities are `default_active=True`. No network needed either:
`create_file("~/Desktop/x.bat")` → open. `_safe_desktop_child` applied `.txt`
only when the suffix was *empty*, so an explicit `.bat` passed through.

**Root cause.** The sandbox answered "is this path allowed?" and was treated as
having answered "is this safe to execute?". Two different questions.

**Wrong assumption.** *The declared `arbitrary_shell_command: RESTRICTED` policy
prevents shell execution.* It did not, because the real execution primitive was
never a shell tool — it was `os.startfile`. A policy protects the tool it names,
not the capability it describes.

**Fix.** Extension **allowlist** (`LAUNCHABLE_SUFFIXES` / `is_launchable()`) at
the launch point, plus forcing a non-launchable suffix at the Desktop write
point.

**Verified.** 40 tests, including `invoice.pdf.exe` judged by its real suffix,
and Ahmed's real `.pptx`/`.docx`/`.md` still opening.

**Reusable rules.**
1. **Containment is not safety.** "Inside an allowed directory" says the path is
   permitted, never that its contents are safe to act on.
2. **Audit the primitive, not the policy name.** Ask what actually executes
   code, then check whether *that* is gated. A policy governing a tool that does
   not exist protects nothing.
3. **Allowlist, never denylist, for anything that can execute.** A denylist
   loses to the next extension the OS makes runnable, and to the ones nobody
   remembers (`.pif`, `.wsh`, `.application`, `.msp`).

---

## F-004 — A regression run raced an in-flight source edit

**Date** 2026-08-31 · **Severity** low (process) · **Status** fixed by practice

**Attempted.** Run the full suite in the background while continuing to work.

**Failed.** The run reported `11 failed, 552 passed`. Re-running the same file
immediately after gave 25/25 pass, and the next clean full run gave 563 passed.
The failure report was entirely an artifact.

**Evidence.** The 11 failures were all in `test_nova_runtime_task_graph.py`,
whose subject (`nova_runtime/task_state.py`) was edited *during* the run.

**Wrong assumption.** *A background test run is a snapshot of the code at
launch.* It is not — it reads files as it reaches them.

**Fix (practice).** Do not edit files under test while a suite runs. Adding
*new* files is safe once collection has finished; editing files under test is
not. When a result looks surprising, check whether it raced an edit before
believing it.

**Reusable rule.** **A test result is only evidence about the tree that was on
disk when the test read it.** Treat a surprising failure as a question about
what was actually tested, not only about the code.

---

## F-005 — A tool reported success for a run that never happened

**Date** 2026-08-31 · **Severity** low · **Status** noted

**Attempted.** `pytest tests/ -q --timeout=600 2>&1 | tail -60`.

**Failed.** `pytest-timeout` is not installed; pytest exited with a usage error.
The shell reported **exit code 0**, because the pipeline's exit status came from
`tail`, not from pytest.

**Wrong assumption.** *A zero exit code from a piped command means the command
succeeded.*

**Fix.** Capture `${PIPESTATUS[0]}` explicitly when piping a command whose exit
status matters.

**Reusable rule.** **Verify the thing you care about, not a proxy that happens
to be adjacent to it.** This is the same class of error as F-001 and F-002:
trusting a signal that was never actually connected to the fact.

---

## F-006 — `GROQ_API_KEY` invalid; every provider call silently degraded

**Date** 2026-08-31 · **Severity** high · **Status** BLOCKED_EXTERNAL

**Attempted.** Live class notes, live Q&A, and post-class generation during a
real 67-minute lecture.

**Failed.** Live notes stalled with 23 unfolded batches; the topic never
resolved; the final notes were written by a 3B local model and contained a
fabricated definition built from a transcription error.

**Evidence.** `GET https://api.groq.com/openai/v1/models` → **HTTP 403**.
`nova_core.router` logs: `provider=groq error=ProviderRequestError` followed by
`provider=openai error=ProviderUnavailableError`.

**Root cause.** Invalid or revoked credential on the primary provider.

**Wrong assumption (NOVA's, not the user's).** *Falling back to a local model
preserves the capability.* It preserved the *call* while silently destroying the
*quality*, and nothing surfaced the degradation to the user at the time.

**Fix.** Requires a valid credential from Ahmed — no engineering work clears it.
Recorded as `BLOCKED_EXTERNAL` so it blocks only the acceptance run and notes
quality, not unrelated workstreams.

**Reusable rule.** **Silent degradation is a failure mode, not a fallback.**
When a fallback materially changes output quality, that must be visible in the
artifact — not only in a log line nobody reads during class.

---

## F-007 — A fabrication corroborated itself

**Date** 2026-08-31 · **Severity** high · **Status** fixed

**Attempted.** Verify generated lecture definitions against the course's own
materials, to catch a mishearing that had become a stated definition.

**Failed.** On the first run against real data the reviewer flagged **nothing** —
including the known-bad `"The condition GNRO >= N is a property stated in the
lecture slide"`.

**Evidence.** `CourseContextLibrary.build_context` returned 8 sources: 3
`course_material` decks and **5 `prior_note` files** — `Lecture.md`, `Study.md`,
`Questions.md`, `Evidence.md`, `Presentation Outline.md`. Those are NOVA's own
generated notes. `"GNRO" in materials` → `True`, entirely because NOVA had
written it there itself.

**Root cause.** The evidence pool used for *verification* included NOVA's own
prior output, so the claim under suspicion was among its own corroborating
sources.

**Wrong assumption.** *"Course context" is one thing.* It is two. Grounding a
live answer benefits from prior notes — continuity across lectures is real
value. Verifying generated content must exclude them, because a witness cannot
vouch for itself. The same data serves one purpose and disqualifies the other.

**Fix.** `CourseContextLibrary.verification_material()`, admitting only
human-authored sources (`course_material`, `session_attachment`). `build_context`
is unchanged, because its inclusion of prior notes was never wrong *for what it
does*.

**Verified.** With human-only evidence, the reviewer flags exactly the
fabricated definition on the real session and leaves all 4 genuine ones — zero
false positives.

**Reusable rule.** **Ask what an evidence pool is FOR before reusing it.** A
corpus that is correct for grounding can be disqualifying for verification.
Whenever a system checks its own output, enumerate what is in the reference set
and remove anything the system authored — this is the `HUMAN_PROVENANCE`
boundary that `nova_capture/evidence.py` already draws, applied one layer up.

---

## Cross-cutting pattern

F-001, F-002, F-005 and the recovery design in `nova_runtime/store.py` are the
same failure wearing different clothes:

> **A record asserted something it had no basis for, and was believed.**

A status file said `running` with no way to know. A metrics field said `false`
with nothing measured. An exit code said `0` for a command that never ran. In
each case the fix was the same shape — *make the reader verify, and give the
data a way to say "unknown"* — which is why it is now a standing invariant in
`DEVELOPMENT.md` rather than a fix applied a fourth time.
