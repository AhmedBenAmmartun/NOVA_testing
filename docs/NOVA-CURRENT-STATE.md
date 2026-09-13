# NOVA — Authoritative Current State

Read this first, then verify it against the repo before trusting it. If anything
here disagrees with the repository, **the repository wins** — update this file.

---

# PART A — VERIFIED CURRENT (2026-09-12)

## A1. Git state — Unified Persistent U1 candidate

```
worktree:    C:\Projects\NOVA-Labs\nova-unified-persistent
branch:      lab/nova-unified-persistent-u1-20260910
HEAD:        5a820497310761056171f0d62ae6bfc41db58635
             (Provider Resilience P1 — VERIFIED LAB CHECKPOINT)
MERGE_HEAD:  3e53d33bcc49a707725a245d12395be85ba4daf6
             (Class Intelligence: cloud-first + budget refunds)
merge base:  cd6e8d00706c002538b1f47320e22a3c0461df44
merge state: STAGED, NOT COMMITTED
```

`HEAD` is still P1 because the U1 merge commit has deliberately not been
created. The merge lives in the index and working tree, awaiting Ahmed's
approval gate. Nothing is committed or pushed from U1.

Checkpoint lineage, verified with `git merge-base --is-ancestor`:

```
cd6e8d0 -> 26adfda (V1A) -> 01409c9 (V1B) -> e1fdbea (V1C)
        -> f7bb1db (A0)  -> f9e4f46 (A1)   -> b8f59e1 (P0)
        -> 5a82049 (P1, checkpointed 2026-09-10, testing remote only)
```

## A2. Verified test count

```
914  full suite on the U1 candidate (2026-09-12, 0 failures)
```

Arithmetic, all four terms measured rather than estimated:

```
 682  common ancestor cd6e8d0
+198  Provider Resilience P1 lineage
 +26  Class Intelligence
  +8  new U1 budget x circuit integration tests
----
 914
```

Lab worktrees have no `venv/` of their own. Run with the primary repo's
interpreter from the candidate root:

```
$env:PYTHONIOENCODING = 'utf-8'
& "C:\Projects\AI Agent\venv\Scripts\python.exe" -m pytest -q
& "C:\Projects\AI Agent\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
```

Also verified on the candidate: NOVA tools driver 35/35, router/provider
simulation 16/16, `git diff --check` clean, no secrets staged or committed.

## A3. What U1 changed

Provider Resilience P1 and Class Intelligence had both edited the same two
`except` blocks in `nova_core/router.py`. Git merged them with zero conflicts,
which proved nothing — one Class test encoded a mechanism P1 had superseded and
failed immediately. U1 reconciled that deliberately:

- the obsolete "a dead provider is attempted 10 times" expectation is
  SUPERSEDED; the invariant it protected (a dead provider must not drain the
  shared class cap) is unchanged and still asserted;
- Class Intelligence keeps its own `ProviderHealthTracker` — approved internal
  isolation, recorded as ADR-006, never a user-facing mode;
- `tests/test_nova_unified_budget_circuit.py` pins the reserve/refund/skip
  contract against the real budget and router.

See `docs/UNIFIED-PERSISTENT-U1.md` for the full phase record.

## A4. NEEDS VERIFICATION

- **Live Gemini/LiveKit runtime behavior** — all U1 and P1 evidence is static
  and unit/integration-level. No live session or real Gemini failure has
  exercised the realtime health observer.
- Whether per-lane provider-health isolation survives U4's Intelligence Fabric.
- Class-specific circuit cooldown tuning, pending real lecture evidence.
- `test_nova_class_recovery` hard-crash flakiness under full-suite load.

---

# PART B — HISTORICAL (2026-08-31 handoff, SUPERSEDED by Part A)

Preserved because it records how the project reached the current state. These
numbers and this Git state are **no longer current**. Do not resume from them.

**Written 2026-08-31. This file was the handoff for the next engineering
session.**

## B1. Git state (HISTORICAL)

```
branch:  nova-nextgen-runtime-20260824
HEAD:    72e4d51  Centralize NOVA path authority and protect archives
modified: 33 tracked files
untracked: 50 files
```

**Nothing is committed from this session.** All work is in the working tree,
deliberately: the repo's convention is that Ahmed makes his own checkpoint
commits. Nothing was pushed. `.env` and `.env.bak-121104` are gitignored
(`.gitignore:2-3`); the only tracked env file is `.env.example`.

## B2. Verified test count (HISTORICAL)

```
459  at session start   (this resolved a standing NEEDS VERIFICATION in ROADMAP)
682  at handoff
692  after class cloud-first Phase 1 (2026-09-01, uncommitted)
```

**+223 tests, 0 failures.** Run with:

```
.\venv\Scripts\python.exe -m pytest tests\ -q
```

Every count in `ROADMAP.md` and in this file was observed, not estimated.
The current verified count is **914** — see Part A2.

---

## 3. Architecture decisions made this session

| Decision | Why |
| --- | --- |
| **EXTEND `nova_runtime`, never replace** | 332 lines, 6 call sites, zero persisted state to migrate; its lifecycle semantics were already correct |
| **`core/` stays dead** | It name-collides with live systems: `ModelRouter` exists in both `core/router.py` (47 lines, dead) and `nova_core/router.py` (421, live). Guarded by `tests/test_nova_no_duplicate_runtime.py`. **Deleting it is Ahmed's call** per `DEVELOPMENT.md` |
| **`nova_runtime` duplicates `runtime_root()`** | Importing `nova_school.paths` costs ~372ms (its `__init__` loads all course intelligence) and inverts layering. A test asserts both resolvers return the same path |
| **`web_download` stays REVERSIBLE** | Rejected a worker's recommendation to promote it to SENSITIVE: `approve()` has zero production callers, so that would have deleted the feature, not hardened it. The vulnerability was the *launch*, now closed |
| **Note review makes no model call** | Asking the same model whether it believes itself is not independent evidence. The professor's slides are |
| **SQLite follows `nova_integrations/storage.py`** | WAL, foreign keys, busy timeout, versioned migrations — an existing pattern, not a second one |

---

## 4. Components changed / added

**New source files**

```
nova_knowledge/knowledge_db.py    correction memory (SQLite)
nova_capture/note_review.py       deterministic evidence check on generated notes
nova_capture/note_versions.py     archive previous notes on regeneration
nova_runtime/store.py             durable task state + INTERRUPTED recovery
nova_school/corrections.py        correction file parsing + store sync
docs/NOVA-FAILURE-LEDGER.md       7 entries, evidence + reusable rule each
```

**Modified**

```
nova_capture/postprocess.py   liveness, corrections, review, versioning
nova_capture/status.py        session_metrics() resolver
nova_capture/control.py       process_identity_matches() made public
nova_capture/models.py        metrics_finalized flag
nova_capture/terminology.py   multi-word phrase corrections
nova_runtime/task_state.py    graph vocabulary + new JobState members
nova_runtime/jobs.py          JobSpec + submit() dependency scheduling
nova_policy/engine.py         Principal, worker gating, principal-keyed grants
nova_school/context.py        verification_material()
tools/files.py                LAUNCHABLE_SUFFIXES allowlist
tools/{desktop,web,email_calendar}.py   pass principal=Principal.user()
agent.py                      NovaRuntime construction + recovery + shutdown
```

**13 new test files** (see §12 for which to run).

---

## 5. Security invariants (each has a regression test)

1. **`os.startfile` only ever receives a document or media file.**
   `tools/files.py` checks `is_launchable()` against the `LAUNCHABLE_SUFFIXES`
   **allowlist**. Before this, `web_download` (REVERSIBLE → no prompt) into
   `~/Downloads` (a SAFE_DIR) followed by `open_file_or_folder` was unconfirmed
   code execution using two default-active capabilities, bypassing the declared
   `arbitrary_shell_command: RESTRICTED` policy entirely.
   **Keep it an allowlist** — a denylist loses to `.pif`, `.wsh`,
   `.application`, and whatever Windows makes executable next.
2. **NOVA may not write a runnable file to the Desktop.** `_safe_desktop_child`
   forces a non-launchable suffix.
3. **Containment ≠ safety.** Being inside a SAFE_DIR says the path is allowed,
   never that the contents are safe to act on.
4. **The permission engine knows who is asking.** `run(..., principal=...)` is a
   **required** keyword — a caller cannot omit it and be treated as Ahmed.
   Grants are keyed `"<session>|<principal>"`. `ActionPolicy.worker_invocable`
   defaults **False**. The worker check runs *before* grant lookup, so no prior
   human approval can promote a worker into an action it was never allowed.
   `approve()` refuses non-user principals **in the engine** and audits the
   attempt — not by omitting a `@function_tool` decorator, which is a
   convention, not a boundary.
5. **`nova_runtime` must not import `nova_policy`, `nova_os`, or `nova_school`.**
   The task layer records permissions a task *would* need as data and never
   evaluates them.

---

## 6. Knowledge / Truth architecture

**Transcript is evidence, not fact.** Three stores, one owner each:

| Store | Owns | Never |
| --- | --- | --- |
| Raw files (`%LOCALAPPDATA%\NOVA\ClassCapture\<COURSE>\<SESSION>\`) | audio chunks, `transcript.jsonl`, journals | rewritten by any correction |
| `knowledge.sqlite3` | confidence, status, scope, counts, provenance | large binaries |
| Obsidian vault | human-readable notes Ahmed reads and edits | opaque database rows |

### Raw vs corrected vs vault

- **Raw**: `transcript.jsonl` + `audio/` — immutable. No correction ever touches
  these.
- **Corrected**: the *derived* `SessionEvidence` view, rewritten in memory by
  `apply_course_corrections()` before generation. Originals preserved in
  `item.attributes["raw_text"]`, and the applied pairs in
  `item.attributes["corrections"]`.
- **Vault**: generated notes. Human-readable, versioned, never the source of
  truth about what was said.

### Correction lifecycle

```
candidate ──(user confirmation | independent evidence)──> confirmed
    │                                                          │
    └────────────────── (contradiction) ───────────────────────┘
                                │
                          rejected  (retained, never deleted)
```

- **Only CONFIRMED corrections are applied.** A candidate is counted, kept, and
  inspectable — it does not get to change what NOVA believes.
- **`times_seen` never promotes anything.** Repetition is not verification; the
  recognizer can be wrong the same way twice.
- **Trusted sources arrive confirmed**: `user` and `user_file` (Ahmed's own
  `STT-Corrections.md`). There is nothing to verify about a rule he wrote.
- **Rejected rules are retained** — a retired rule explains why a note was
  revised.
- **Scope is part of the rule**: `global` < `course` < `topic` < `speaker`,
  most specific wins. `consents → constants` is right in an algorithms lecture
  and wrong in a conversation about consent forms.

### Note versioning

`nova_capture/note_versions.py`. A regeneration archives previous notes to
`_versions/vN/` with a manifest recording **when and why**. Current notes keep
their filenames (Ahmed opens `Lecture.md` in Obsidian). Large artifacts are
**referenced, not copied**. Archiving is best-effort — losing an archive is bad,
losing the new notes because bookkeeping failed would be worse.

### ⚠ Verification-material rule — prevents circular AI evidence

**NOVA's own output is never evidence for verifying NOVA's own output.**

`CourseContextLibrary.build_context()` includes `prior_note` sources — NOVA's own
generated notes. That is **correct for grounding** a live answer (continuity
across lectures) and **disqualifying for verification**.

This is not hypothetical. The note reviewer's first real run flagged *nothing*,
because `GNRO` — the mishearing under suspicion — appeared in `Lecture.md`,
`Study.md` and `Questions.md`. The fabrication was corroborating itself.

**Use `CourseContextLibrary.verification_material()`** for any check of NOVA's
own output. It admits only `course_material` and `session_attachment`. Same
boundary `HUMAN_PROVENANCE` draws in `nova_capture/evidence.py`, one layer up.

Recorded as **F-007** in `docs/NOVA-FAILURE-LEDGER.md`.

---

## 7. Database schema / migrations implemented

`nova_knowledge/knowledge_db.py`, default path
`%LOCALAPPDATA%\NOVA\knowledge.sqlite3` (override: `NOVA_RUNTIME_ROOT`).

**Migration 1 — the only one implemented.**

```sql
corrections(
  id, heard_text, heard_key, corrected_text, scope,
  course_code, topic, speaker_id, status, confidence,
  times_seen, times_confirmed, first_seen, last_seen, source,
  UNIQUE (heard_key, scope, course_code, topic, speaker_id)
)
INDEX corrections_lookup (heard_key, course_code)

correction_evidence(
  id, correction_id -> corrections(id) ON DELETE CASCADE,
  source, detail, session_id, recorded_at
)
```

Thresholds (module constants): user confidence `0.95`, candidate start `0.3`,
apply at `>= 0.75`, reject at `<= 0.2`.

**Not yet implemented** (these are migration 2+, not a rewrite): sessions,
transcript segments, concepts, claims, questions/answers, note versions,
learning experiences, lessons, skills.

Durable task state is separate and file-backed:
`nova_runtime/store.py` → `%LOCALAPPDATA%\NOVA\runtime\tasks.ndjson` + `tasks.json`.

---

## 8. Known blockers

| Blocker | Status |
| --- | --- |
| **`GROQ_API_KEY` returns HTTP 403** | `BLOCKED_EXTERNAL` — needs a valid credential from Ahmed. No engineering work clears it. Blocks the real-provider acceptance run and notes quality. Blocks nothing else |
| **`PermissionEngine.approve()` has no production caller** | No SENSITIVE action can be approved by anyone. Safe failure mode, but the tier is unproven and it blocks any hardening that would raise a tool's level |
| **Only 4 of 81 tools route through the permission engine** | The principal governs those 4 |
| **Deleting `core/`** | Requires Ahmed's decision per `DEVELOPMENT.md` |
| **`NOVA_LEARNING_ENABLED` is false and absent from `.env`** | `nova_learning` captures nothing; its store directory has never been created. Verified, not inferred |

---

## 9. Exact unfinished requirements (knowledge directive)

- §7 partial — only corrections tables exist
- §8 — lexical + semantic retrieval layers: **not started**
- §13 — **ClassContext: not started** (next target)
- §14 — incremental lecture understanding: not started
- §15 — full note pipeline: partial (correction + review stages exist)
- §16/§17 — note quality/voice: not addressed
- §20 — cross-class learning: not started
- §21 — concept relationships: schema is versioned so this can land later

Also unfinished from the earlier mission: orchestrator, worker runtime, learning
promotion pipeline, safe self-improvement.

---

## 10. Exact next executable step

**Build the smallest testable `ClassContext` foundation.** Nothing was started —
there is no half-written file to reconcile.

Target: a dataclass + builder assembled **once at session start** and updated
incrementally, so NOVA stops treating each transcript sentence as an isolated
string.

It should carry: course; session/lecture identity; professor identity when
known; recent topics; current likely topic; relevant course materials; prior
lecture concepts; verified terminology; **applicable confirmed corrections**;
known assignments/deadlines; unresolved questions; and **provenance for all of
it**.

Reuse, do not duplicate:

- `nova_school/registry.py` → `CourseProfile` (course identity)
- `nova_school/context.py` → `CourseContextLibrary` (materials; use
  `verification_material()` for any self-check)
- `nova_school/vocabulary.py` → `course_stt_keyterms`
- `nova_knowledge/knowledge_db.py` → `active_corrections(course_code=...)`
- `nova_capture/evidence.py` → `Provenance` for every field's origin
- `nova_capture/understanding.py` → existing topic/section model

Suggested first slice, fully testable: `nova_school/class_context.py` with
`ClassContext` + `build_class_context(course_code, session_path=None)`,
assembling course identity, materials, terminology, and confirmed corrections
with provenance — no LLM call, no new store.

---

## 11. Suggested next-session commit hygiene

Working tree is dirty by design. Before large new work, consider a local
checkpoint commit (Ahmed's call — **do not push**).

---

## 12. Tests to run after continuing

```
# fast affected set while working on ClassContext
.\venv\Scripts\python.exe -m pytest tests\test_nova_correction_memory.py tests\test_nova_class_corrections.py tests\test_nova_note_review.py -q

# full suite before any checkpoint  (expect 914 as of 2026-09-12; 692 was 2026-09-01)
.\venv\Scripts\python.exe -m pytest tests\ -q
```

**Process rules learned the hard way (F-004, F-005):**

- Never edit a file under test while a background suite runs — a raced edit
  produced a garbage 11-failure result this session.
- `pytest ... | tail` reports `tail`'s exit code. Capture `${PIPESTATUS[0]}`.
- Don't do bulk regex surgery on Python source; it left unbalanced parens twice.
