# NOVA Roadmap

> **Project boundary — 2026-08-15**
>
> The legacy NOVA Dashboard has been detached from this repository/runtime.
> NOVA is the agent/AI operating layer. NOVA Vision remains part of NOVA.
> Dashboard/Valo is a separate project and may integrate later only through a
> defined external interface. Older dashboard references below may be historical.

_Last updated: 2026-09-12_

> **Resuming engineering? Read `docs/NOVA-CURRENT-STATE.md` first.**
> It is the authoritative handoff: exact Git state, verified test count,
> architecture decisions, security invariants, the Knowledge/Truth architecture,
> the implemented database schema, known blockers, and the exact next executable
> step. If it disagrees with the repository, the repository wins — fix the file.
>
> **VERIFIED CURRENT (2026-09-12): full suite 914 passed** on the Unified
> Persistent U1 checkpoint (`lab/nova-unified-persistent-u1-20260910`).
> Implementation checkpoint: `8cd7bd1dc8da8ed3b8d6e30af9d76e8f5f68b51c`; docs-only closeout:
> `0274574ae45b350d76603f6199b85fd6bdfe1613`; testing remote only; not promoted to production/main.
> The earlier counts — 682 at the `cd6e8d0` handoff and 692 after Class
> cloud-first Phase 1 — are **HISTORICAL**, not current.

## Mission

NOVA is Ahmed's personal AI operating assistant: voice-first, vision-capable,
tool-using — for coding, school, research, desktop control, media, email,
calendar, files, and daily productivity. This LiveKit + Gemini Realtime repo
is the main NOVA going forward (fast, smooth speech-to-speech voice).

## Current status (reconciled 2026-07-27, updated 2026-08-13, originally verified 2026-07-21)

- [x] **Unified Persistent NOVA — U1: unify P1 + Class Intelligence (LAB, merge
      VERIFIED LAB CHECKPOINT / NOT ACTIVE)** (2026-09-12, VERIFIED CHECKPOINT): first phase of the Unified Persistent build order, in the
      isolated worktree `C:\Projects\NOVA-Labs\nova-unified-persistent`
      (`lab/nova-unified-persistent-u1-20260910`), based on the P1 checkpoint
      `5a82049` with Class Intelligence `3e53d33` merged in over the common
      ancestor `cd6e8d0`. Git reported zero conflicts — exactly one file
      overlapped (`nova_core/router.py`, where P1's circuit breaker and Class's
      budget refund had both edited the same two `except` blocks) — but a clean
      textual merge proved nothing, and one Class test failed immediately
      (`assert 2 == 10`). Reconciled semantically: the superseded expectation
      that a dead provider receives all 10 calls was replaced (P1 stops it at
      the failure threshold) while the actual invariant it protected — a dead
      provider must not drain the shared class cap — is unchanged and still
      asserted; Class Intelligence keeps its own `ProviderHealthTracker` as
      approved internal isolation, pinned by a test; `FakeBudget.release()`
      added where the merge made it necessary. New
      `tests/test_nova_unified_budget_circuit.py` pins the reserve/refund/skip
      contract against the REAL `CloudUsageBudget` and router, including the
      reachable double-refund case (a provider that answered, then died, then
      was skipped). Every fix was mutation-checked to confirm it fails against
      the broken behavior. Verified: full suite **914 passed / 0 failed**
      (682 ancestor + 198 P1 + 26 Class + 8 new U1 = 914, no regressions),
      Class files back to their 26-passed pre-merge baseline, tools driver
      35/35, simulation 16/16. Documentation reconciled three-way with the
      uncommitted main-worktree docs (snapshotted read-only first; the main
      worktree was never modified). Live Gemini/LiveKit runtime behavior
      remains NEEDS VERIFICATION. See `docs/UNIFIED-PERSISTENT-U1.md`.
      U1 implementation is checkpointed at `8cd7bd1dc8da8ed3b8d6e30af9d76e8f5f68b51c`; the docs-only
      closeout is `0274574ae45b350d76603f6199b85fd6bdfe1613`. Both are on the `testing` remote only and U1 is
      not production/ACTIVE. **Next step:** U2 (persistent NOVA
      runtime/lifecycle).

- [x] **Provider Resilience P1 — provider health, circuit breaking, and
      realtime health reporting (VERIFIED LAB CHECKPOINT)** (2026-09-09,
      checkpointed 2026-09-10 as commit
      `5a820497310761056171f0d62ae6bfc41db58635` on
      `lab/nova-provider-resilience-p1-20260907`, pushed to the `testing`
      remote only — not origin, not merged, no PR): built on the frozen P0
      checkpoint `b8f59e1` in the isolated worktree
      `C:\Projects\NOVA-Labs\nova-provider-resilience-p1`
      (`lab/nova-provider-resilience-p1-20260907`). Adds
      `nova_core/provider_health.py` (`ProviderHealthTracker`: closed /
      open / half-open circuit, per-category cooldowns, one probe at a time),
      `ProviderRateLimitError`, 429/408/5xx classification in the OpenAI, Groq,
      and Ollama adapters, and `RealtimeFailureKind` +
      `classify_realtime_error` for the native realtime lane. `ProviderRegistry`
      and `ModelRouter` share exactly ONE tracker through the default factory
      path; the router skips a provider whose circuit is open instead of paying
      its timeout and cloud-budget allowance again. Request-specific 4xx
      failures deliberately never poison a reachable provider. `agent.py`
      records realtime health into the EXISTING `NovaRuntime` health registry
      (`provider:<name>:realtime`, HEALTHY/DEGRADED/FAILED) and publishes safe
      state on the `nova.provider-status` topic — no second runtime health
      system, no mutation of LiveKit's `recoverable` flag, and a realtime
      failure never means the whole system is dead. Gemini remains the only
      native audio/video realtime lane; degraded voice fallback stays an
      explicit, still-deferred STT → ModelRouter → TTS design. Verified: full
      suite **880 passed** (frozen-P0 baseline 823, +57 new P1 tests, no
      regressions), tools driver 35/35, simulation 16/16, `git diff --check`
      clean. A later review found three blockers, all fixed and covered by
      tests confirmed to fail against the pre-fix behavior: LiveKit's
      `RealtimeModelError` wrapper was classified instead of the provider
      exception it carries (every status-code failure collapsed to `unknown`,
      and the message fallback read the wrapper repr, which embeds the raw
      provider message); a generic `ProviderRegistry.health_check()` could
      close or shorten an active rate-limit circuit, so only a routed
      HALF_OPEN generation now proves rate-limit recovery; and Ollama mapped
      429 to `ProviderRequestError` instead of `ProviderRateLimitError`. Live
      Gemini/LiveKit runtime behavior remains NEEDS VERIFICATION. See
      `docs/PROVIDER-RESILIENCE-P1.md`. P1 is checkpointed at
      `5a820497310761056171f0d62ae6bfc41db58635`; it is now the base of the
      verified Unified Persistent U1 checkpoint lineage.

- [x] **NOVA Lab V1B — model-facing `development` capability (LAB checkpoint)**
      (2026-09-05, VERIFIED CURRENT): added an inactive-by-default
      (`default_active=False`) `development` NOVA OS capability
      (`nova_os/catalog.py`, `tools/development.py`, `nova_lab/service.py`)
      giving the model exactly five tools — `lab_status`,
      `list_lab_features`, `get_lab_feature`, `list_lab_test_profiles`,
      `register_lab_feature` — all inspection/registration-metadata only. No
      model-callable test execution, lifecycle transition, promotion,
      retirement, restart, rollback, deletion, shell, or approval exists.
      This is a LAB checkpoint, not a production-ready or ACTIVE milestone.
      `register_lab_feature` keeps every V1A provenance check (safe
      feature/capability ids, `lab/*` branch, exact worktree root under the
      approved NOVA Labs root, same Git repository, clean worktree, branch
      match, an approved named test profile, `base_ref` resolved to an
      immutable commit SHA, that SHA verified as an ancestor of Lab HEAD,
      LAB-only entry, no silent feature-id overwrite) and adds one more:
      `capability_id` must be a real NOVA capability. Validated against
      `nova_os.capabilities.CANONICAL_CAPABILITY_IDS`, the single canonical
      capability-id set that `nova_os.catalog
      .build_default_capability_manager()` asserts its tool-wired
      capabilities equal (drift raises `RuntimeError` immediately) — NOVA Lab
      reads the same constant rather than maintaining a second hard-coded
      list. Avoided a `nova_os` <-> `nova_lab` import cycle (`nova_os.catalog`
      imports `tools.development`, which imports `nova_lab.service`) and
      avoided pulling in every `tools/*` module just to validate an id by
      making `nova_os/__init__.py` resolve `build_default_capability_manager`
      lazily via `__getattr__` (PEP 562); existing callers
      (`from nova_os import build_default_capability_manager` in `agent.py`)
      are unaffected. Verified this run: focused NOVA Lab suite **38/38**
      (36 carried over from V1A hardening + 2 new regression tests — unknown
      `capability_id` rejection, and `"development"` being a canonical id),
      full current suite **720/720**, bare `pytest -q` **720/720**,
      `git diff --check` clean (informational CRLF notices only), NOVA local
      tools driver **35/35**.

      **KNOWN LIMITATION (NEEDS VERIFICATION), verified against the real
      runtime** (`livekit-agents==1.6.6`, `livekit-plugins-google==1.6.6`):
      in a live Assistant session, `search_capabilities` ->
      `activate_capability("development")` reports success and does update
      `Agent._tools`, but the model calling a newly-activated tool (e.g.
      `list_lab_test_profiles`) within the SAME `session.run()` tool-calling
      chain gets LiveKit's "Unknown function" error. Traced directly in the
      installed `livekit-agents` source (`voice/agent_activity.py`): the tool
      list for an in-progress turn is snapshotted once
      (`all_tools = self.tools.copy()` in `_generate_reply()` for the
      text/pipeline path, or `tool_ctx = llm.ToolContext(self.tools)` per
      realtime `GenerationCreatedEvent` for the production voice path), and a
      same-turn recursive tool-response continuation reuses that original
      snapshot instead of re-reading the already-updated tool list. The
      production voice path is further gated by Gemini Live only learning a
      new tool schema after a full session reconnect
      (`realtime_api.py`'s `_mark_restart_needed()`). VERIFIED: same-turn use
      of a newly activated capability's tools fails. NEEDS VERIFICATION:
      whether those tools become usable on the FOLLOWING `session.run()`
      turn — the two-turn diagnostic is blocked on Gemini free-tier daily
      quota, not on anything in this codebase. Do not claim next-turn
      activation works, and do not claim dynamic activation is fixed; no
      workaround was added in V1B. This is a NOVA OS capability-kernel
      property affecting every optional capability, not just `development`;
      its resolution (most likely a stable dispatcher/gateway tool that never
      changes the model-visible schema, or gating always-registered tools
      through `CapabilityManager`/`nova_policy` instead of the runtime tool
      list) is a separate future architecture decision, out of scope for this
      LAB checkpoint. Full trace: `docs/NOVA-LAB-LIFECYCLE.md`. Next: V1C
      trusted candidate gating and `nova_policy` integration; background Lab
      test execution through `NovaRuntime` with durable test evidence;
      separately evaluate the capability-kernel dispatcher/gateway redesign.
- [x] **NOVA Lab V1A foundation** (2026-09-05, LAB only): added the
      internal `LAB -> CANDIDATE -> ACTIVE -> RETIRED` lifecycle primitives,
      local feature registry + recoverable append-only lifecycle journal,
      constrained `lab/*` Git worktrees under `C:\Projects\NOVA-Labs`, and
      an allow-listed test runner that refuses non-Git/non-Lab targets. Added
      `pytest.ini` with `testpaths = tests` so ignored/pending repository copies
      are not collected by a bare pytest run. No model-callable promotion,
      retirement, production restart, rollback, arbitrary shell, or direct
      production-worktree write exists in V1A. **18 focused Lab tests** after
      hardening; pre-hardening verification was 14/14 focused plus **696/696**
      full current tests and **696/696** bare pytest. One Windows recorder
      isolation test flaked once during a full run, then passed 3/3 immediately;
      production Class Capture code was unchanged. Next: V1B read/register
      development capability, still without activation/restart authority.
- [x] **CLASS CLOUD-FIRST MIGRATION — Phase 1: no automatic local fallback**
      (2026-09-01, *uncommitted*): active class intelligence no longer escalates
      a cloud failure into heavy local Ollama inference. Root cause was **not**
      the budget number (already raised 60 → 200 on 2026-08-28, which did not
      help): `nova_capture/intelligence.py::_route` carried its own hardcoded
      provider chain ending in `ollama`, and because Ollama is `is_local` the
      router's cloud-budget gate never applies to it. Both failure modes ended
      there. Verified from real session logs, not assumption: 2026-08-28 logged
      215 budget skips for groq *and* openai (the class cap is a single global
      total, so exhaustion blocks both cloud providers at once) followed by 86
      ollama selections and 130 ollama failures; 2026-09-01 never reached the
      cap but, with both cloud providers unreachable, still selected ollama 42
      times.
      The fix reuses what already existed rather than adding anything: the cloud
      tier is now resolved by `ProviderConfiguration.is_local` (so no name-based
      config can smuggle a local model back in), exhaustion returns `None`, and
      the **existing** durable evidence queue + degraded status already treat
      `None` as "keep the evidence, admit reduced intelligence". No new router,
      queue, scheduler, or vault. `last_class_route_outcome()` now carries the
      real reason (`class_cloud_budget_exhausted` vs
      `cloud_providers_unavailable`) into the notes worker `detail`, replacing a
      status line that claimed "no usable model response" when no model had been
      called. `NOVA_CLASS_ALLOW_LOCAL_FALLBACK=1` keeps an explicit escape
      hatch, off by default. **12 new tests; full suite 692 passing.**
      NOT done at Phase 1, deliberately (**HISTORICAL — RESOLVED BY U1**,
      2026-09-12): the budget was reserved *before* the provider call and never
      refunded, and the cap is one global total across providers. On 2026-09-01
      that burned ~180 of 200 daily units on calls that returned nothing. The
      2026-09-01 incident evidence is preserved above as the reason the fix was
      needed. Both halves now exist — Class Intelligence added refund-on-failure
      and Provider Resilience P1 added the circuit breaker — and U1 reconciled
      their interaction. See the Phase 2 entry below and
      `docs/UNIFIED-PERSISTENT-U1.md`.
- [x] **CLASS CLOUD-FIRST MIGRATION — Phase 2: budget truth — SUPERSEDED /
      RESOLVED BY U1** (identified 2026-09-01; delivered 2026-09-12 in the
      verified Unified Persistent U1 checkpoint): the original statement, preserved as
      **HISTORICAL** — "`nova_core/router.py` calls `cloud_budget.try_consume()`
      before `provider.generate()` and never refunds a failed call, and
      `ClassCloudUsageBudget` caps on a single `total_requests` across all
      providers. A permanently failing provider therefore drains the shared cap
      and forces the (now correct) deferred state far too early. Evaluate a
      refund-on-failure, per-provider accounting, and a circuit breaker that
      stops attempting a provider after N consecutive failures."

      **What actually shipped.** Two of the three evaluated items exist and are
      verified: refund-on-failure (`ModelRouter._release_cloud_budget()`, from
      the Class line) and the circuit breaker
      (`nova_core/provider_health.py:ProviderHealthTracker`, from Provider
      Resilience P1 — opens after `NOVA_PROVIDER_FAILURE_THRESHOLD` consecutive
      failures, immediately on a rate limit). A permanently failing provider no
      longer drains the shared cap: once its circuit opens it is skipped
      *before* any reservation is taken, so it costs neither budget nor latency.

      **Per-provider accounting was NOT adopted** and remains **PLANNED**. The
      cap stays one global total across providers, which is now safe because a
      failed or skipped call costs nothing.

      U1 reconciled the interaction between the two halves — they had been
      developed on separate branches and both edited the same two `except`
      blocks in `nova_core/router.py`. The contract: a reservation is taken only
      when NOVA actually calls a provider, so anything that stops NOVA before
      the call must neither reserve nor refund. Pinned by
      `tests/test_nova_unified_budget_circuit.py`. See
      `docs/UNIFIED-PERSISTENT-U1.md` and
      `[[ADR-006 - Per-Lane Provider Health Isolation]]`.
- [ ] **CLASS — cloud providers were unreachable on 2026-09-01** (*needs
      Ahmed's verification*): both `openai` and `groq` report `configured=True`
      (keys present) but that session logged 46 openai and 38 groq
      `ProviderUnavailableError`, plus 4 groq `ProviderRequestError`. No live API
      call was made to diagnose this. Under the old behaviour this produced
      fabricated local notes; under the new behaviour it means class
      intelligence defers entirely, so it now needs fixing on its own merits.
- [x] **SECURITY — unconfirmed code execution chain closed** (2026-08-31,
      *uncommitted*): found by the security threat-model worker, verified
      directly against source. `open_file_or_folder` called
      `os.startfile(path)` (`tools/files.py`) with **no extension check**.
      `os.startfile` runs the Windows shell's default verb — *view* for a
      document, *execute* for `.exe/.bat/.cmd/.vbs/.js/.lnk/.hta/.msi`. That
      composed with the write tools into unconfirmed RCE:
      `web_download` (registered **REVERSIBLE**, so the permission engine runs
      it with no prompt, `tools/web.py:41`) → `~/Downloads`, which is in
      `SAFE_DIRS` → `open_file_or_folder` → the payload runs. Both `files` and
      `web` are `default_active=True`, so no confirmation was required anywhere
      in the chain. No network was even needed:
      `create_file("~/Desktop/x.bat")` → open did the same, and
      `_safe_desktop_child` only forced `.txt` when the suffix was *empty*, so
      an explicit `.bat` passed straight through. **This entirely bypassed the
      declared `arbitrary_shell_command: RESTRICTED` policy** — the real
      execution primitive was never a shell tool.
      Fixed with an extension **allowlist** (`LAUNCHABLE_SUFFIXES` +
      `is_launchable()` in `tools/files.py`): documents and media open,
      everything else is refused, folders still open. A denylist was rejected —
      it loses to the next extension Windows makes executable. **40 new tests.**
      NOT done, and deliberately: `web_download` was left REVERSIBLE. Promoting
      it to SENSITIVE would delete the feature outright, because
      `PermissionEngine.approve()` has **zero production callers** — see the
      approval-path item below. The vulnerability was the launch, and the launch
      is closed.
- [ ] **SECURITY — `PermissionEngine.approve()` has no implementation**
      (found 2026-08-31, *not fixed*): `nova_policy/engine.py:183` is called by
      nothing outside negative assertions in tests. Every SENSITIVE action
      (`close_app`, `restart_app`, `read_email`) therefore mints a confirmation
      id and then expires — the confirmation system has never actually approved
      anything. This is a safe failure mode today, but it means the tier is
      unproven, and it blocks any correct hardening that would move a tool up a
      level. Also found: 8 of 10 `DEFAULT_POLICIES` govern tools that do not
      exist, and only **4 of 81 tools** route through the permission engine.
- [x] **Note quality reviewer + circular-evidence fix** (2026-08-31,
      *uncommitted*): corrections only repair mishearings someone already knows
      about. The one that cost the 2026-08-31 lecture was novel — "GNRO" from
      `g(n) >= 0` — and generation promoted it into a *definition* attributed to
      a slide. `nova_capture/note_review.py` checks generated definitions
      against the course's own materials: a definition whose central term
      appears in **none** of the slides the professor is teaching from is a
      fabrication signal. Deliberately **not** another model call (directive
      §2: independent evidence beats repeated generation) — it is deterministic,
      cheap enough to run every time, and **marks rather than deletes**, since
      dropping content on a heuristic would lose real lecture material.
      **Found while testing against real data — a circular-evidence bug:**
      `CourseContextLibrary.build_context` mixes course materials with
      `prior_note` sources from the Sessions folder, which are **NOVA's own
      generated notes**. "GNRO" appeared in `Lecture.md`, `Study.md` and
      `Questions.md`, so the first real run found "corroboration" and flagged
      **nothing** — the fabrication was vouching for itself. Added
      `CourseContextLibrary.verification_material()`, which admits only
      human-authored sources (`course_material`, `session_attachment`). Prior
      notes remain available for *grounding* a live answer, where continuity
      helps; they are disqualified from *verifying* NOVA's own output. Same
      boundary `HUMAN_PROVENANCE` already draws in `nova_capture/evidence.py`.
      **16 new tests.** Verified end to end on the real session: of 5
      definitions in the generated `Lecture.md`, exactly the fabricated one was
      flagged and all 4 genuine ones passed — zero false positives.
- [x] **Note versioning: a regeneration preserves what it replaces**
      (2026-08-31, *uncommitted*): post-class generation wrote into the session
      folder in place, so a re-run destroyed the previous notes. That was about
      to cost something real — the 2026-08-31 COT3400 notes were written by a
      local fallback model after the Groq credential failed and contain a
      definition fabricated from a mishearing; re-running after the key is
      replaced would have erased both the mistake and the fact that it changed.
      `nova_capture/note_versions.py` archives the previous version into
      `_versions/vN/` with a manifest recording **when and why**, so "why did
      this change?" is answerable from the artifact. Current notes keep their
      filenames — Ahmed opens `Lecture.md` in Obsidian, and versioning must not
      make the common case harder to read. Large artifacts are **referenced,
      not copied** (a 32 KB deck per regeneration is how a vault bloats), and
      archiving is best-effort: losing a version archive is bad, losing the new
      notes because bookkeeping failed would be worse. **10 new tests**;
      verified against a copy of the real COT3400 session — 8 files preserved,
      the `.pptx` referenced, current notes untouched.
- [x] **Correction memory: candidate → evidence → confirmed** (2026-08-31,
      *uncommitted*): first piece of the truth/evidence layer.
      `nova_knowledge/knowledge_db.py` is a local-only SQLite store following
      the conventions already in `nova_integrations/storage.py` (WAL, foreign
      keys, busy timeout, versioned migrations) — not a second pattern, and not
      a second memory system. Ownership is explicit: the **vault file** stays
      Ahmed's human-editable surface, the **database** holds what a flat file
      cannot express (confidence, status, scope, counts, provenance), and **raw
      evidence stays in files**.
      A correction NOVA *infers* enters as a **candidate** and is deliberately
      never applied — `times_seen` alone never promotes anything, because the
      recognizer can be wrong the same way twice. Only user confirmation or
      independent evidence promotes it; contradiction lowers confidence and
      eventually retires the rule, which is **retained, not deleted**, since a
      retired rule explains why a note was revised. Scope is part of the rule
      (global / course / topic / speaker, most specific wins) because
      `consents → constants` is right in an algorithms lecture and wrong in a
      conversation about consent forms.
      Wired into postprocess, which now takes confirmed rules from the store and
      degrades to the hand-written file if the store is unavailable.
      **29 new tests**, using the real failures as fixtures per the directive.
      Found by running against Ahmed's real file: the parser was importing the
      file's own instruction prose (*"One rule per line, `heard => actual`"*) as
      a rule, because that sentence contains the separator. Fixed with a
      phrase-shape guard; his file now yields 19 clean rules instead of 20.
      Not yet done: claims/concepts tables, note versioning, semantic retrieval,
      and the note-quality reviewer.
- [x] **Task runtime: durable state, graph vocabulary, dependency scheduling,
      and agent wiring** (2026-08-31, *uncommitted*): `nova_runtime` held a
      correct job manager that **`agent.py` never imported** — the NOVA Ahmed
      talks to had no task layer at all. A read-only architecture worker
      confirmed EXTEND over REPLACE (332 lines, 6 call sites, zero persisted
      state to migrate) and produced a 13-item compatibility contract, all of
      which is now pinned by tests. Delivered:
      **(a)** `TaskSnapshot` widened additively with `parent_id`, `children`,
      `depends_on`, `priority`, `progress`, `owner`, `attempt`/`max_attempts`,
      `result_ref`, `required_permissions`; `JobState` gained
      `WAITING_DEPENDENCY`, `BLOCKED`, `PAUSED`, `RETRYING`, `INTERRUPTED`.
      The original five names/values are untouched — consumers compare by
      identity. **(b)** `nova_runtime/store.py`: append-only `tasks.ndjson` +
      atomically replaced index, with `recover()` reinterpreting a task left
      RUNNING by a dead process as `INTERRUPTED` (matched on pid **and** process
      create time). `result` is never persisted, only `result_ref`.
      **(c)** `JobSpec` + `submit()` beside the untouched `start()`: a
      **factory**, not a coroutine, because a consumed coroutine cannot be
      re-awaited — which is what blocked deferral and retry structurally. A
      dependency that fails, is cancelled, or does not exist **blocks** its
      dependent rather than letting it run on a broken prerequisite; an unknown
      dependency id fails loudly instead of wedging the runtime forever.
      **(d)** `agent.py` constructs the runtime, recovers durable state at
      startup behind a try/except (task state is valuable; being able to talk to
      NOVA is more valuable), and shuts it down with the job.
      **56 new tests.** `nova_runtime` is guarded from importing `nova_policy`,
      `nova_os`, or `nova_school` — the task layer must never evaluate its own
      authority, and infrastructure must not depend on a domain package.
- [x] **SECURITY — the permission engine now knows WHO is asking**
      (2026-08-31, *uncommitted*): `run()` previously took no principal, every
      live call site passed the literal `"voice"`, and the audit record had no
      actor field. Session grants keyed `(session_id, action_name)` meant that
      once workers could call tools, **one user approval would silently
      authorize unlimited worker invocations of that action for the rest of the
      session**, and a post-incident audit could attribute nothing.
      `Principal` (user / worker / system, with a `parent` for the delegation
      chain) is now minted only by trusted constructors — `kind` is validated
      against a closed set, so a forged kind raises rather than being accepted
      as free text. `run(..., principal=...)` is a **required** keyword: a
      caller cannot omit it and be silently treated as Ahmed. Grants are keyed
      `"<session>|<principal>"`; `ActionPolicy.worker_invocable` defaults
      **False**, so a policy that never considered workers has not authorized
      them; the worker check runs *before* grant lookup, so no prior human
      approval can promote a worker into an action it was never allowed;
      `approve()` refuses any non-user principal **in the engine** and audits
      the attempt, rather than relying on the absence of a `@function_tool`
      decorator as a boundary. All 4 live call sites updated. **14 new
      behavioral tests**, including the load-bearing one: a user's session grant
      does not authorize a worker, while still working for the user.
      Also replaced `test_session_cleanup_removes_pending_state`, which asserted
      a literal source string, with a behavioral test — it broke on this
      refactor and would have passed had cleanup been genuinely broken.
      Still open: only 4 of 81 tools route through the engine at all, so the
      principal governs those 4. Extending coverage is the next security step.
- [!] **BLOCKED_EXTERNAL — `GROQ_API_KEY` returns HTTP 403** (2026-08-31):
      verified directly against `https://api.groq.com/openai/v1/models`. Groq is
      the primary provider for Class Intelligence, so every live-notes fold,
      live answer, and post-class generation on 2026-08-31 fell through to a
      local model; OpenAI answered `/v1/models` fine but returned
      `ProviderUnavailableError` under load, which maps to rate/usage limit or
      timeout (`providers/openai_provider.py:216`). **Requires a valid
      credential from Ahmed — no engineering work can clear it.** Blocks only:
      the real-provider acceptance run, and notes quality. Does NOT block
      runtime, orchestrator, learning, or capture-state work; those proceed.
- [x] **Capture-state single source of truth** (2026-08-31, *uncommitted*):
      during the live COT3400 lecture `session.json` reported
      `audio_chunks: 0`, `recorder_mode: "none"`, `audio_integrity_ok: false`
      while `health.json` simultaneously reported 84 chunks from a healthy
      isolated recorder. Both described the same session; one was false. Root
      cause is not a write bug — those fields are *finalization outputs* held
      in a struct written from session start, so before `finalize()` they are
      dataclass defaults and nothing distinguishes "measured as zero" from
      "never measured". `audio_integrity_ok: false` therefore reads as *the
      recording is damaged* when it means *nobody has checked yet*. Fixed with
      the same shape as the postprocess fix: `metrics_finalized` on
      `ClassSessionMetadata`, set by finalize(), and
      `nova_capture.status.session_metrics()` as the only sanctioned reader —
      finalized sessions answer from session.json, live ones from health.json,
      genuinely unmeasured values answer `None` rather than a placeholder zero.
      Pre-flag sessions stay trusted when stopped. Verified against the real
      2026-08-31 session (no flag present, correctly resolved: 201 chunks,
      4005.07s, 729 segments). **9 new tests.**
- [x] **Class Capture reliability: postprocess liveness + course corrections**
      (2026-08-31, *uncommitted*): a real COT3400 lecture produced **no notes**.
      Post-processing was launched at 13:01:11, died without raising, and
      `postprocess.json` still read `{"status": "running", "error": null}` eight
      hours later with the vault folder never created — the same class of
      failure V1.3.7 fixed for the recorder, left unguarded for postprocess.
      Fixed by making liveness the *reader's* job: `read_postprocess_status()`
      resolves a recorded `running` against process identity (`pid` +
      `pid_created_at`, via the now-public `control.process_identity_matches`)
      and reports `interrupted` when the process is gone. Verified against the
      real stale file, including the no-identity backwards-compatible path.
      Separately, the recognizer's `GNRO`/`consents` mis-hearings reached
      `Lecture.md` as *stated definitions*. `nova_school/corrections.py` loads
      Ahmed's `STT-Corrections.md` (`heard => actual`, longest-phrase-first) and
      `apply_course_corrections()` rewrites the **derived** evidence only —
      `transcript.jsonl` and audio are never touched, originals kept in
      `attributes["raw_text"]`. Verified on the real session: 20 rules, 20/795
      items corrected. **28 new tests; full suite 487 passed.**
- [x] **Windows full-suite verification** (2026-08-31): the item below carried
      a standing NEEDS VERIFICATION for the uncommitted V1.3.7/V1.3.8 work.
      Run on Windows against the project venv: **459 passed in 166.71s**, zero
      failures. The final real-provider acceptance run is still outstanding —
      `GROQ_API_KEY` currently returns **HTTP 403**, so every class-intelligence
      call today fell through to a local model. That key must be replaced before
      the acceptance run means anything.
- [ ] **Class Intelligence final checkpoint hardening** (2026-08-29,
      *uncommitted; Windows full-suite VERIFIED 2026-08-31 (459 passed); one
      final real Groq acceptance run still required, blocked on a valid key*):
      sanitized real-session ASR snippets out of committed regression
      fixtures/comments and replaced the exact session-folder identifier in the
      reliability report with `<SESSION_ID>`. Closed the remaining reduce-scaling
      hole: a long lecture could pass the 180-minute test only because its derived
      sections happened to stay small; one 90-minute semantic topic could still
      exceed the provider envelope. `nova_capture/understanding.py` now checks
      estimated input + actual configured output reservation + safety margin
      before model calls, recursively reduces oversized contiguous section groups,
      compresses child summaries before the parent reduction, and refuses to send
      an oversized singleton/global request. The postprocess guard tracks the
      largest configured Groq/OpenAI/Ollama reservation instead of assuming 4,000.
      New pathological single-topic and multilingual-estimation tests added.
      Local affected verification in the ChatGPT audit copy: **66 passed**
      (`test_nova_class_understanding.py` + `test_nova_class_recovery_v138.py`);
      multiple additional class test files also passed. This Linux container lacks
      NOVA's LiveKit/OpenAI dependencies and has a per-command time cap, so the
      authoritative Windows 456+ full suite and final real provider run remain
      explicitly **NEEDS VERIFICATION** before checkpoint/commit.
- [x] **Class Capture reliability rebuild — V1.3.7** (2026-08-28,
      *uncommitted, pending review*): the 2026-08-27 COP3710 lecture stopped
      recording after **38m37s** while Ahmed was still in class. Root cause is
      verified from the session's own evidence: `audio.wav` ended at 2317.744 s,
      the last transcript segment at 2317.812 s, `status: "completed"`,
      `audio_error: null` — both streams died together because the microphone
      was closed by `finalize()`, which the LiveKit job shutdown callback owned.
      *Which* LiveKit event fired is **unknowable**: Class Capture wrote no log
      file. Fixed by inverting ownership. The microphone now lives in its own OS
      process (`nova_capture/recorder_process.py`) that knows nothing about STT,
      LLMs, or LiveKit; audio is rolling 20 s WAV chunks with an append-only
      `audio/manifest.jsonl` (temp → fsync → atomic rename), so a crash costs at
      most one chunk and loss is *detectable* via `scan_audio_dir`; a new
      `ClassSessionSupervisor` owns one session id for the whole sitting and
      writes `health.json` + `events.jsonl` + `class_capture.log`; an
      `AgentSession` close is now a recovery (`STT_GAP_START` → rebuild with
      backoff → `STT_GAP_END`) instead of the end of class; a live notes worker
      (`nova_capture/live_notes.py`) produces notes within ~60–120 s with a
      durable evidence queue that survives a provider outage; `SpeakerRoleTracker`
      gained a live confidence view and a Guest Speaker role without weakening
      the conservative V1.3.3 finalize-only labels; stop now reports
      `completed` / `completed_with_warnings` / `failed` / `aborted` honestly.
      Also fixed three defects the new tests found: `write_pcm` did not split at
      chunk boundaries, degraded live notes were invisible in `live_notes.md`,
      and guest presenters could never be identified. Side effect: `topics.jsonl`
      is populated for the first time — `LectureContext.set_topic` and
      `TopicTracker.update` had **zero production callers**, so live Q&A always
      said "CURRENT TOPIC: not yet resolved". Suite **388 passed / 0 failed**
      (was 282), including a real subprocess crash test proving audio survives a
      hard kill of the intelligence process, and a real Windows microphone check
      (separate process acquires the device; RSS flat at 9.5 MB; 115 MB/hour).
      A 2026-08-28 follow-up corrected two documentation/test accuracy issues:
      the report implied post-processing already consumed `live_notes.md` (it
      does **not** — `postprocess.py` has no reference to it; that stays P1),
      and the long-session tests used 30-second chunks while production defaults
      to 20, so they asserted 360 chunks for a three-hour class instead of the
      real 540. `tests/test_nova_class_long_session.py` now builds the recorder
      with **no** `chunk_seconds` so the shipped default does the work, and
      asserts exactly 540 chunks, sequences 1..540 with none reused, 8,640,000
      frames, and a last chunk ending at 10800.000000 s.
      **Pipecat 1.8.1: PILOT ONLY** — measured on this runtime, it resolves on
      Python 3.14 but pulls 21 packages including numba/llvmlite/onnxruntime,
      its `local` transport needs PyAudio (no cp314 wheel), and it would need a
      Deepgram key NOVA does not have; the seam and `NOVA_CLASS_PIPELINE` flag
      ship, the dependency does not. **NOT done:** transcript gap backfill (gaps
      are recorded `backfilled: false`), and the **real 150-minute soak has NOT
      been run** — `.\Test-NOVA-Class-Endurance.ps1 -Minutes 150`. Full report:
      `docs/NOVA-CLASS-CAPTURE-RELIABILITY-REPORT.md`.
- [x] **Lecture structure derivation — the professor's progression** (2026-08-27,
      *uncommitted, pending review*): found that the live recorder **never
      records topics** — `LectureContext.set_topic` and `TopicTracker.update`
      have zero production callers, so `topics.jsonl` is empty in every real
      session, every `topic` field on every transcript/question/marker record is
      `None`, and live Q&A always says "CURRENT TOPIC: not yet resolved". The
      intellectual progression that lecture notes most need to preserve was
      structurally absent. Rather than add model calls to the stabilized capture
      hot path, `nova_capture/evidence.py` now reconstructs it *after the fact*
      from lexical cohesion in the professor's own words (deterministic,
      offline, TextTiling-style), exposed as `SessionEvidence.lecture_structure()`
      and `LectureSection`. Captured topics always win if the recorder ever
      starts writing them. Sections carry the new `Provenance.NOVA_DERIVED` and
      render with an explicit "NOT the professor's own section headings" caveat,
      so reconstructed structure can never be quoted as professor speech.
      Measured: 14/50/90/120-minute lectures yield 7/9/12/11 sections at 100%
      coverage in ≤51 ms; evidence schema bumped to 2 with `structure`
      persisted. **Deliberately NOT done:** SessionEvidence → `nova_knowledge`
      retrieval integration — see risks below.
- [x] **Session Evidence Model V1 — grounded Class Intelligence** (2026-08-26,
      *uncommitted, pending review*): added `nova_capture/evidence.py`, one
      authoritative read of every raw session journal into an ordered,
      provenance-carrying, deterministically serializable model (stable IDs,
      `Provenance` separating captured audio / user marks / NOVA answers /
      source material). Post-processing now consumes it, which fixes three
      defects: (1) all five generated documents previously saw only
      `transcript_excerpt[:16000]` — measured at **20.4%** of a 90-minute
      lecture; budgeted salience selection with guaranteed per-window coverage
      now reaches **94.6%** at the same budget; (2) `markers.jsonl`,
      `topics.jsonl` and `attachments.jsonl` were captured and then never read
      by `process_session`, so every `mark_class_moment` call was silently
      discarded — they now reach generation; (3) prompts imposed no structural
      grounding, so notes defaulted to generic Introduction/Key
      Takeaways/Conclusion. Writes `session_evidence.json` (layer:
      working_intelligence) beside the raw journals and a new
      `Lecture Timeline.md` output. Raw evidence is never mutated. 21 new
      behavioural tests.
- [x] **Repair pass — green baseline restored** (2026-08-26, *uncommitted*):
      full suite now **249 passed / 0 failed** (was 222/2). Four fixes:
      (1) removed the UTF-8 BOM `agent.py` had picked up from uncommitted
      learning work — exactly 3 bytes, byte-proven, learning code untouched;
      (2) `test_nova_class_turn_aware_v134` pinned the literal
      `CAPTURE_VERSION = "1.3.4"` while `776c53d` intentionally moved the file
      to `1.3.6` — replaced with a parsed **minimum-version floor**, which is
      strictly stronger (it now rejects 1.3.3 and a missing constant, which the
      sibling `"1.3` prefix checks do not); (3) `_elapsed()` raised
      `ValueError` on a non-numeric timestamp, killing the whole post-class
      job — now coerces; (4) `role_map` was not validated as a dict, so a
      corrupt `speaker_roles.json` raised `AttributeError` — now degrades to
      generic labels. (3) and (4) are pre-existing crash paths at `776c53d`,
      found by hostile-input testing of review point 13. **Known remaining
      brittleness (not fixed, no failure today):**
      `test_nova_class_intelligence_v13` and `test_nova_class_quality_v133`
      assert `'CAPTURE_VERSION = "1.3'` / `'"1.3.'` as substrings — these will
      break on a 1.4.0 bump *and* would silently pass on a 1.3.3 regression.
      Next: have `nova_knowledge` retrieval consume `SessionEvidence` so
      course-material alignment is grounded in the same evidence, then concept
      extraction.
- [x] **NOVA Class Intelligence V1.3.4 — turn-aware live questions** (2026-08-23):
      raw STT remains immediate/authoritative, while live Q&A now waits for a
      committed human turn, merges split question continuations, suppresses
      near-duplicate restatements, and serializes provider work through a
      bounded answer queue. Automated acceptance includes the exact
      `Like, where are you?` + `Getting the data from?` regression. Next:
      Windows live acceptance, then NOVA Class Awareness / natural-language
      class start-stop-control integration.
- [x] **NOVA Vision Phase 1 — camera + mic client** (2026-08-13): added a
      standalone Tauri 2 Windows control surface under `vision-client/`. It
      joins a unique LiveKit room with a short-lived backend-generated token,
      starts camera and microphone OFF, lets the user enable either explicitly,
      previews the exact published camera track, supports pin/minimize/compact
      controls, and releases media before disconnect/close. `agent.py` now
      enables LiveKit realtime `video_input=True`. Window/display/browser-tab
      source pickers remain Phase 2. Guardian's old `ImageGrab` ambient-vision
      backend is retired so there is no screenshot fallback. Added a focused
      Phase 1 regression contract; next acceptance step is a live Windows run
      proving camera preview, mic, remote NOVA audio, and clean device release.
- [x] **Dashboard cleanup slice** (2026-08-05): Escape now closes the Ctrl+K
      command palette even while its search input is focused, preventing the
      modal overlay from trapping dashboard clicks. Windows `user32` loading
      in `tools/desktop.py` is now lazy and platform-guarded so non-Windows
      test collection and code review can import the module safely without
      changing Windows behavior. Dashboard docs now list all six pages,
      including Workspace. Focused regression checks passed. Next: connect
      the dashboard to the already-authorized Gmail account and replace stale
      placeholder connection/status data with the shared integration feed.
- [x] **Guardian security/vision module** (2026-07-22, `nova_guardian/`:
      `ambient_vision.py`, `security_monitor.py`, `window_monitor.py`,
      `runtime.py`, `state.py`, `events.py`, `config.py`): wired into
      `agent.py` via `tools/guardian.py`
      (`check_guardian_security`, `get_guardian_alerts`,
      `get_guardian_status`, `look_at_screen_locally`,
      `start_guardian_vision`, `stop_guardian_vision`). Imports cleanly in
      the venv. **Not covered by the driver or pytest suite** — no
      automated regression protection for this surface yet.
- [x] **Real email/calendar integrations** (2026-07-22, `nova_integrations/`:
      working Google Calendar/Gmail OAuth connector
      (`connectors/google_workspace.py`) and a Microsoft Graph connector
      (`connectors/microsoft_graph.py`), local `IntegrationDatabase`
      storage): wired into `agent.py` via `tools/email_calendar.py`
      (`list_connected_accounts`, `sync_email_calendar`,
      `get_unread_emails`, `read_email`, `get_calendar_agenda`,
      `get_next_event`, `find_calendar_conflicts`, `get_daily_briefing`)
      and into the Dashboard's real Calendar page
      (`Dashboard/integration_feeds.py`). Confirmed 2026-07-27 this is
      genuine wired infrastructure, not demo data — it shows "not
      connected" only because nobody has run the OAuth setup yet. Also
      **no automated test coverage.**
- [x] **Permission/safe-mode engine** (2026-07-22, `nova_policy/engine.py`):
      wired into `agent.py` via `tools/permissions.py`
      (`list_pending_actions`, `deny_action`, `enable_nova_safe_mode`).
      Model self-approval was removed in Phase 0; disabling Safe Mode requires
      a trusted UI action.
- [x] **Specialist routing tool** `ask_specialist` (2026-07-22,
      `tools/specialist.py`, `nova_core/` provider routing; live-agent tool
      exposure fixed 2026-08-03 in `agent.py`): the Gemini realtime assistant
      now exposes the unified specialist/coordinator tool instead of only
      documenting it. `prompts.py` now routes reasoning, coding, and
      private/offline specialist work through `ask_specialist` rather than
      naming direct tools that are not in the live LiveKit tool list. Groq in
      the new `nova_core` provider registry remains a follow-up because
      `providers/groq_provider.py` is still empty.
- [x] **Hermes-style toolset registry and finder** (2026-08-03,
      `nova_core/toolsets.py`, `tools/toolsets.py`): NOVA now has a stable
      grouped map of its live tools and exposes `describe_nova_toolsets` plus
      `find_nova_tools` so the assistant can answer what it can do, recommend
      which current toolset/tools should handle a task, and explain which
      tools are sensitive. This is the first foundation slice for later
      Hermes-inspired skills, dynamic tool loading, and subagent delegation.
      It is read-only and does not change any existing tool behavior.
- [x] **Hermes-style browser slice 1** (2026-08-03, `tools/browser.py`):
      NOVA now exposes `open_browser_page` and `get_browser_status` for an
      isolated controlled Chrome/Edge session using DevTools HTTP endpoints.
      The slice launches a separate browser profile instead of Ahmed's normal
      cookies/profile and rejects unsafe schemes such as `file:`,
      `javascript:`, `data:`, and credential-bearing URLs. This deliberately
      does not add click/type/snapshot/DOM control yet; page content remains
      untrusted and needs a separate hardened follow-up.
- [x] **Exact Hermes browser names, safe read-only pass** (2026-08-03,
      `tools/browser.py`): NOVA now registers the exact Hermes browser tool
      names: `browser_navigate`, `browser_snapshot`, `browser_click`,
      `browser_type`, `browser_scroll`, `browser_press`, `browser_back`,
      `browser_get_images`, `browser_console`, `browser_vision`,
      `browser_cdp`, and `browser_dialog`. The safe subset enabled now is
      isolated http/https navigation plus text accessibility snapshots with
      `@e` refs. High-agency browser actions and raw CDP are intentionally
      blocked until Ahmed explicitly approves that risk boundary.
- [x] **Read-only real-browser attach** (2026-08-03, `tools/browser.py`):
      NOVA now exposes `browser_attach_user_browser`, which attaches only to
      a local `127.0.0.1:<port>` Chrome/Edge DevTools endpoint that Ahmed
      intentionally started. It enables status and snapshot reads of existing
      user-browser tabs without launching the real browser profile, clicking,
      typing, keypresses, raw CDP, screenshots, console, or image extraction.
      `browser_navigate` remains isolated and should not open pages in
      Ahmed's real browser profile.
- [x] **Isolated browser action tools** (2026-08-03, `tools/browser.py`):
      after Ahmed's explicit approval, NOVA now enables `browser_click`,
      `browser_type`, `browser_scroll`, `browser_press`, and `browser_back`
      only inside NOVA's isolated browser profile. These tools refuse to act
      on the attached real browser. Raw CDP, console inspection, image
      extraction, screenshots, and dialog control remain blocked for separate
      approval.
- [x] `agent.py` now wires **71 tools** total (was 38 before 2026-07-22;
      `CLAUDE.md`'s old "38 tools" figure was stale and has been corrected
      — see the `.claude`/`.agents` doc-reorg note below).
- [x] **App launcher/dock fixes** (PRs #1-#5, merged into `main` by
      2026-07-23): real Win32 executables preferred over duplicate UWP
      shortcuts, ChatGPT/Codex entries un-confused, process detection added
      for more apps, dashboard app launches open maximized, the dock
      tracks pinned + running app state instead of static icons.
- [x] **Doc reorg** (2026-07-22): `CLAUDE.md` renamed to `DEVELOPMENT.md`
      (git-tracked, generic across Claude/Codex); skills moved to
      `.agents/skills/` for git tracking, with `.claude/skills/` kept as
      Claude Code's local (gitignored) mirror; `CODEX_PROMPTS.md` renamed
      `PROJECT_TASKS.md`. A stray, untracked, stale `CLAUDE.md` from before
      this rename lingered on disk and fed outdated context into a
      2026-07-26 session — replaced 2026-07-27 with a thin pointer at
      `DEVELOPMENT.md` so this can't recur.
- [x] **Conversation idle observability** (2026-08-02,
      `agent.py`, `nova_bridge.py`, `Dashboard/web/index.html`): Claude
      verified LiveKit `AgentSession.user_away_timeout` is a status-only
      signal, not an automatic disconnect, mic mute, or billing cutoff.
      NOVA now maps LiveKit `user_state=away` to bridge phase `away`,
      preserves that phase through both bridge copies, labels it as
      `Away` / `AGENT AWAY` in the dashboard instead of falling through to
      generic Online, and clears stale `away` state when LiveKit reports the
      user is present again or activity resumes. This is deliberately
      observability-only: deciding
      whether NOVA should mute, disconnect, or switch to standby after idle
      remains part of the Phase 6 always-on/standby decision.
- [x] **Dashboard interruption phase vocabulary** (2026-08-02,
      `nova_bridge.py`, `Dashboard/nova_bridge.py`,
      `Dashboard/web/index.html`): the bridge and dashboard now accept and
      label `stopping`, `waiting`, `paused`, `cancelled`, and `working` as
      first-class display phases. This prepares the UI for the approved
      stop/wait/never-mind/pause/continue behavior without implementing
      those voice commands yet. No Gemini, LiveKit, VAD, voice, microphone,
      or room lifecycle settings changed. Next recommended step: verify
      real barge-in/queued-speech cancellation, then implement explicit
      interruption commands in small tested slices.
- [x] **Explicit `stop` interruption handler** (2026-08-02,
      `agent.py`): final transcripts that are simple stop commands now set
      dashboard phase `stopping`, call LiveKit's existing
      `AgentSession.interrupt(force=True)` path to cancel current and queued
      speech/realtime generation, and return to `listening` when the
      interruption future completes unless newer activity already changed the
      phase. Non-final transcripts do not fire the command. This does not
      cancel running tools yet, and it does not change Gemini, LiveKit model
      settings, VAD, voice, turn detection, microphone state, or room
      lifecycle. Next recommended step: run the manual live voice acceptance
      test by saying "stop" while NOVA is speaking, then implement `wait` /
      `never mind` as separate slices.
- [x] **Explicit `never mind` cancellation handler** (2026-08-02,
      `agent.py`): final transcripts that are simple never-mind commands now
      set dashboard phase `cancelled`, call LiveKit's existing
      `AgentSession.clear_user_turn()` path for any local turn state LiveKit
      can still clear, then call `AgentSession.interrupt(force=True)` to
      cancel current and queued speech/realtime generation. Claude verified
      `clear_user_turn()` is currently near-no-op for Gemini Realtime's
      already-sent audio, so `interrupt(force=True)` is the real cancellation
      mechanism in this stack. NOVA returns to `listening` when the
      interruption future completes unless newer activity already changed the
      phase. Non-final transcripts and longer non-command phrases do not fire
      the command. This does not cancel already-running tools yet, and it does
      not change Gemini, LiveKit model settings, VAD, voice, turn detection,
      microphone state, or room lifecycle.
- [x] **Explicit `wait` interruption handler** (2026-08-02, `agent.py`):
      final transcripts that are simple wait commands now set dashboard phase
      `waiting`, call LiveKit's existing `AgentSession.interrupt(force=True)`
      path to stop current/queued speech, and return to `listening` when the
      interruption future completes unless newer activity already changed the
      phase. Unlike `never mind`, `wait` does not call `clear_user_turn()`, so
      the current request/context is left in place for the user's correction
      or added information. Non-final transcripts and longer non-command
      phrases do not fire the command. This does not change Gemini, LiveKit
      model settings, VAD, voice, turn detection, microphone state, or room
      lifecycle. Next recommended step: run manual live voice acceptance for
      `stop`, `never mind`, and `wait`; then either implement `pause` /
      `continue` as a larger separate slice or do Claude's TTL-cache follow-up.
- [x] **Dashboard integration snapshot TTL cache** (2026-08-02,
      `Dashboard/integration_feeds.py`): `snapshot_messages()` now reuses a
      defensive-copy 5-second in-process cache so repeated dashboard snapshot
      requests do not immediately re-open and re-query the local
      email/calendar database. Tests cover single-compute behavior, cache
      reuse, cache isolation, and expiry recomputation after Claude's
      read-only review. No OAuth tokens, provider APIs, dashboard UI,
      Gemini/LiveKit, voice, microphone, VAD, turn detection, or room
      lifecycle code changed.

Summary of 2026-07-27's dashboard work:

- [x] Dashboard build/version staleness detection (2026-07-27): `server.py`
      reports its running git commit via `/health` and the WebSocket
      snapshot; `nova-app/scripts/stamp-build.mjs` stamps the same commit
      into the packaged Tauri app at build time; the frontend warns if the
      installed app's UI predates the source it's talking to. Directly
      motivated by the installed `NOVA.exe` being found 3 days stale with
      no warning.
- [x] Throttled two unbatched pointermove hot loops (2026-07-27): page-swipe
      drag (`index.html`) and widget drag/resize
      (`dashboard-enhancements.js`) now batch to one `requestAnimationFrame`
      per drag instead of a full re-render per raw pointer event.
- [x] Dashboard extracted to a standalone private repo,
      `github.com/BEN-Ammar-Ahmed/dashboard` (2026-07-27, via
      `git subtree split`): own `.gitignore`/README/`requirements.txt`,
      opt-in `NOVA_DASHBOARD_DEMO=1` demo mode with curated sample data
      (`demo_data.py`), CI (`.github/workflows/test.yml`), and
      `run_demo.ps1`/`.sh` one-command launch. Verified from a clean clone.
      Kept in sync with the main repo's `Dashboard/` via re-split + merge.
- [x] Two local checkouts (`C:\Projects\AI Agent`,
      `C:\Users\ahmed\OneDrive\Desktop\AI Agent`) reconciled onto the same
      `feature-workspace` branch/commit; see the
      `nova-dual-repo-and-shell-skill` memory for the sync workflow.
- [x] `nova-desktop-shell-architecture` skill added (`.agents/skills/` +
      `.claude/skills/`): distilled Seelen UI study + a broader
      desktop-shell vision doc into adopt-now / build-later-in-order /
      never-copy lists for future dock/widget/workspace/window-management
      work.
- [x] **Dashboard windowed page mounting + sound cues** (2026-08-01,
      `Dashboard/web/index.html`, spec at
      `docs/superpowers/specs/2026-07-31-dashboard-performance-and-sound-design.md`,
      plan at
      `docs/superpowers/plans/2026-07-31-dashboard-performance-and-sound-design.md`):
      root cause of the "laggy everywhere" complaint was a single monolithic
      component re-rendering all 6 pages on every ~1s state tick (clock,
      CPU/RAM, Spotify progress) even though only one page is ever visible.
      Fixed using the dc-runtime template engine's own `<sc-if>` primitive
      (confirmed via reading `support.js`: a false branch returns `null` and
      never evaluates its children) to mount only the current page and its
      immediate left/right neighbor — the only pages the swipe-drag
      interaction can ever reveal — cutting mounted pages from 6 to at most
      3. Verified live against the real running instance:
      `document.querySelectorAll('[data-page-canvas]').length` is 3, not 6,
      on every page. Also fixed a regression this surfaced: the "brain"
      canvas animation on the NOVA/Second Brain page used to capture its
      canvas DOM node in a closure once and run forever regardless of
      visibility — after windowed mounting that would have permanently
      frozen the graphic the first time a user navigated away and back.
      Now reads the canvas ref fresh every frame and only animates while
      that page is actually active. A related edge case the reviewer caught
      (unclamped drag distance could reveal blank unmounted pages during an
      aggressive mouse drag) was fixed by clamping `dragX` to one page-width
      in `scheduleDragX`. Added a synthesized (Web Audio, no asset files)
      sound-cue system — `playSfx()` rate-limiter plus 9 named cues for page
      switch, panel open/close, widget add/remove, notifications, NOVA
      agent online/offline (on actual transition only), and a one-shot
      ready chime on first live connect — wired into all the real
      interaction handlers, entirely gated by the existing Settings "Sound
      cues" toggle (no new UI). Live-verified against the real running
      instance by instrumenting `AudioContext.prototype.createOscillator`:
      real clicks produced the correct frequencies (520Hz page-switch,
      640Hz panel-open, 420Hz panel-close), and a rapid double-click
      correctly coalesced into one tone instead of two, confirming the
      rate-limiter works end-to-end, not just in isolated code review. Built
      via subagent-driven-development: 4 implementation tasks, each with an
      independent code-review pass (3 approved on the first pass; 1 needed a
      fix round for the drag-clamp edge case above — the brain-canvas fix
      itself was planned as its own task from the start, not a review
      finding). A final whole-plan review across all 4 tasks combined then
      caught one cross-task regression neither task-scoped review could see
      in isolation: `fitBrain()` (sets the canvas's pixel backing size) only
      ran once, inside the same one-time guard as node/edge generation, so a
      remounted canvas after navigating away and back would render at a
      wrong-sized, blurry 300x150 until the window was resized — fixed by
      moving `fitBrain()` outside that guard so it re-runs on every
      remount. Test suite (`npm --prefix Dashboard test`, 16 JS + 34 Python)
      stayed green throughout.
      **Follow-up not done in this pass:** startup cost from the in-browser
      Babel JSX/template transform (`vendor/babel.min.js`) was not
      rigorously profiled — a real DevTools "reload and record" performance
      trace is needed to know whether it's worth precompiling (would need a
      build step this project doesn't currently have). If idle/switch/drag
      smoothness still isn't "not laggy at all" after this change, the next
      step is Approach B from the spec: true page unmount/remount instead of
      the current current±1 mounting window (deferred, more invasive to the
      swipe-drag mechanics).
      **Still separate/deferred:** wiring Calendar and Tasks to support
      *adding* new items (not just viewing) — Tasks currently only supports
      toggling existing items done (`Dashboard/feeds.py`'s
      `set_task_done`), and Calendar is read-only by design
      (`nova_integrations`'s Google/Microsoft connectors request only
      `*.readonly` scopes, and neither account is connected yet). Ahmed has
      step-by-step instructions for the Google Cloud OAuth Desktop client
      and Azure AD app registration needed before Calendar-add can be built.
- [x] **Dashboard shell redesign — visionOS Glass + Cinematic & Deep**
      (2026-08-02, `Dashboard/web/index.html`, spec at
      `docs/superpowers/specs/2026-08-01-dashboard-visionos-shell-redesign.md`,
      plan at
      `docs/superpowers/plans/2026-08-01-dashboard-visionos-shell-redesign.md`):
      reworked the dashboard shell's visual language from dark glass to
      near-white glass panels floating over a new light gradient environment,
      per Ahmed's "doesn't scream Apple and futuristic" feedback, with a
      slower "Cinematic & Deep" motion personality (~420ms, no-overshoot
      spring, blur-resolve entrances). Scoped to shell chrome only, not the
      other 5 pages' content. 12 tasks, each independently reviewed:
      new `THEME` design-token field (colors/motion values); the dark
      Aurora/Deep-space wallpaper moods replaced by one light gradient
      environment (the dark photo wallpaper stays as the second option, dim
      slider dropped — dimming a light scene reads as grey, not moody); the 3
      top-bar Unicode glyphs (search/notifications/settings) replaced with a
      consistent stroke-based SVG set; top bar restyled as two floating glass
      pills (wordmark, status); dock restyled as a glass pill with
      cursor-distance-based hover magnify/lift (real app icons unchanged,
      only the container and motion); Settings panel trimmed to Lock canvas/
      Dock auto-hide/Reduce motion/Sound cues/Wallpaper and restyled to
      glass, with the unused Focus Modes feature removed entirely (state,
      `setFocus()`, preset table, UI — not just hidden) and the Demo privacy
      toggle removed (a review-caught bug from this removal — stuck
      `st.privacy` persisted state permanently masking chat transcripts —
      was found and fixed in a follow-up commit, `16f08fa`); widget cards
      restyled to light glass; ~140 sites of internal widget teal/violet
      (`#2ee6d6`/`#7c86f8`) swept to the new blue/indigo palette
      (`#0A84FF`/`#5E5CE6`) via a verified one-off script, preserving
      meaningful color pairs (CPU vs RAM bars stayed two distinct colors);
      toast notifications restyled to light glass with a blur-resolve
      entrance; page-switch transitions adopted the Cinematic easing curve
      (rubber-band edge resistance was in the original spec but dropped
      after discovering — and confirming with Ahmed — that page navigation
      is an intentional circular loop, not a bounded range, so there's no
      edge to resist); the brain-canvas graphic recolored for light glass
      plus its hosting card restyled to light glass (a second review-caught
      contrast bug here — two child text elements broken by a color cascade
      — found and fixed in a follow-up commit, `1c6e19c`); and an inline
      "Connect" button added to the Daily Briefing widget and the Calendar
      page's status pill, replacing passive "not connected" text — scoped
      deliberately as a UI signpost only (shows the
      `nova-integrations accounts connect ...` CLI command via a toast), not
      real OAuth from the browser.

      **Task 13 (this task) end-to-end verification** re-walked the whole
      shell live against the running dashboard (state/DOM driven via the
      React fiber, since the Browser pane wasn't compositing frames this
      session — same workaround prior tasks in this plan used) and ran a
      real WCAG contrast check rather than eyeballing it, given two
      contrast bugs had already slipped through task-level review earlier
      in this same plan. It found, and then fixed, two more things review
      missed:
      - **Toast blur-resolve entrance ignored `reduceMotion`/`reduceLocal`.**
        The spec explicitly requires the new blur-resolve and dock-lift
        motion to respect reduced motion "same as it already disables the
        brain-canvas wobble and page-transition animation" — the dock got
        this gate (Task 5), the toast did not (Task 9's brief never called
        it out, and no review caught the gap). Live-confirmed broken (with
        `reduceLocal: true`, the toast button still ran `animation: 600ms
        cubic-bezier(...) toastIn`, unsuppressed), then fixed: the toast's
        `animation` is now driven by a per-toast computed `t.animStyle`
        (`reduce ? 'none' : '600ms cubic-bezier(0.16,1,0.3,1) toastIn'`),
        mirroring the gate pattern used everywhere else in the file.
        Live-reverified both states after the fix: `reduceLocal:false`
        still plays the full curve (`animationName:"toastIn"`);
        `reduceLocal:true` now resolves immediately (`animationName:"none"`,
        `opacity:1`, `transform:none`, `filter:none` — the toast's static
        end-state, no flash-then-freeze). Widget-card entrance (`fadeUp`)
        is still unconditional, but that's a pre-existing,
        explicitly-documented Task 7 scope decision (it reused the old
        `fadeUp` keyframe rather than adding the new blur-enter treatment),
        not a new regression, and was left as-is.
      - **Two label styles measured below WCAG AA 4.5:1 for normal text, one
        borderline — now fixed.** Computed with the real sRGB
        relative-luminance formula against the actual composited background
        (`rgba(255,255,255,.5)` glass over the light environment, not just
        the glass color alone: `#dfe1e7` env base composited with 50% white
        ≈ `rgb(239,240,243)`). Widget-card kicker labels and the Settings
        panel's "Wallpaper" section label (`rgba(30,32,38,.5)` at
        10-10.5px bold/uppercase) measured ≈3.11:1 — clearly under 4.5:1
        (10-10.5px, even bold, doesn't qualify as WCAG "large text").
        Toast subtitles and the brain-card's "Second Brain · Obsidian
        vault" label (the same element the Task 11 contrast fix touched;
        `rgba(30,32,38,.6)` at 11-11.5px) measured ≈4.15:1 — Task 11's fix
        correctly resolved the glaring light-on-light bug it was catching,
        but the result still landed under strict AA. Fixed by bumping both
        to `rgba(30,32,38,.7)`: recomputed ≈5.65:1 against the env-base
        composite and ≈6.02:1 against a pure-white extreme — clears 4.5:1
        with real margin, not a bare pass. Applied consistently to all four
        call sites (two `.5`, two `.6`), and live-reread each element's
        `getComputedStyle(...).color` afterward to confirm the rendered
        (not just declared) value is `rgba(30, 32, 38, 0.7)` everywhere.
        Settings-row toggle labels and the top-bar status text
        (`rgba(30,32,38,.65)` at 12px, ≈4.83:1) already passed and were
        left unchanged; solid `#1e2026` text (≈14.29:1) was never at risk.

      Everything else checked out live: all 6 pages render and the
      page-switcher's circular wrap (0→1→2→3→4→5→0) still works exactly as
      Task 10 verified; widget add/remove and glass styling work; the
      Settings panel shows the exact trimmed list with no Focus Modes/Demo
      privacy; both Connect buttons push the informational toast with the
      real CLI command and make no network call; dock hover-magnify applies
      correctly when not reduced; brain-canvas reduce-gating and recolor
      logic read correctly (live pixel verification was blocked by the same
      non-compositing Browser pane that affected Tasks 5 and 10 — canvas
      layout collapses to 0-height when the pane isn't visually composited).
      Test suite green throughout, both before and after the two fixes
      (16 JS + 34 Python, 50/50). Fixes committed separately from the
      ROADMAP update itself (`539c51e`, "Fix toast reduceMotion gate and
      two contrast-failing text colors").

Done and working:

- [x] **Dashboard v2 from design handoff (2026-07-20)** — the old React/Tauri
      `Dashboard/` and the demo zip were removed (source backed up first);
      the new `Dashboard/` implements `design_handoff_nova_desktop` exactly:
      the high-fidelity 5-page shell (`web/index.html` + `web/support.js`)
      served by `Dashboard/server.py` (aiohttp, 127.0.0.1:8787, no new deps)
      with `feeds.py`/`actions.py`. Wired to REAL data over one WebSocket:
      psutil CPU/RAM, Spotify now-playing (cached-OAuth Web API + window-title
      fallback; controls send real media keys), wttr.in weather, Obsidian
      vault (1,635 notes counted, NOVA/ memory browser, tasks in
      `<vault>/NOVA/Tasks.md` with write-back, forget → `NOVA/.trash`),
      agent phase + activity tailed from `nova_tools.log`, approvals queue
      reconstructed from `audit_logs/nova_actions.jsonl`, chat bubbles from
      `conversation_logs/`, cloud usage chips from `cloud_usage.json`, and
      the real Windows app catalog / Desktop folders / Recent files with real
      launches. Offline it falls back to the design's simulated demo mode.
      Verified: feeds smoke 14/14, driver `tools` 33/33, live browser check
      (LIVE pill, real weather/memories/apps, driver tool calls streaming
      into the activity feed, zero console errors). Driver `chat` was blocked
      by Gemini-side 503/504 (known free-tier issue, not our code).
      The 2026-07-21 integration pass added per-page clipped canvases, complete
      Edit Mode layout controls, self-hosted web runtimes, and a private atomic
      dashboard-to-agent bridge. Approve/Deny now resolves the permission
      engine inside the active agent process, and Ctrl+K delegation becomes a
      real LiveKit user text turn. Remaining adapters: calendar data
      (Google/ICS) and Store-app (UWP) entries in the launcher.

- [x] **Dashboard-to-agent command bridge (2026-07-21)** — added
      `nova_bridge.py` and `nova_agent_bridge.py`: bounded local commands,
      atomic inbox claiming, two-minute expiry, active-session heartbeat,
      result delivery, approval validation, and no transport of secrets,
      arbitrary code, or private file contents. Dashboard health now reports
      whether the agent bridge is active. Automated verification covers the
      five-page layout engine, dashboard contract, command store, delegated
      user turns, in-process permission decisions, and result round trips.

- [x] LiveKit agent runs (console mode and LiveKit Cloud dev mode)
- [x] Gemini Realtime voice conversation (voice "Puck")
- [x] Camera/video input intentionally off (`video_input=False`)
- [x] ai_coustics noise cancellation
- [x] NOVA persona (`SYSTEM_PROMPT` in prompts.py)
- [x] 12 basic tools: weather, web search, open website, open app, YouTube
      search, system info, time, save/read notes, list/read/create files
- [x] `.env` credential loading fixed (was silently loading nothing)
- [x] `requirements.txt` completed (ai-coustics added)
- [x] Test harness + run skill (`.agents/skills/run-ai-agent/` — `tools`,
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
- [x] Full-vault Obsidian Markdown access pass (2026-07-17): memory search
      now scans existing Markdown notes across the vault, including large
      ChatGPT/development assistant exports that previously exceeded the old 100 KB note
      limit. `read_memory_note` can return capped excerpts for long notes
      when given a query, while `.obsidian/` remains blocked and writes still
      stay inside `<vault>/NOVA/`.
- [x] Debug pass (2026-07-16): compile check passed, driver `tools` passed
      19/19, `agent.py console` startup check passed, and `AGENTS.md` /
      `DEVELOPMENT.md` were corrected to say NOVA now registers 29 tools.
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
- [x] Refined desktop dashboard shell selected (2026-07-18): `Dashboard/`
      now contains the active React/Vite visual direction from the refined
      prototype, with a transparent demo-style dashboard canvas, compact page
      dots for Main Dashboard / NOVA Activity / Apps, a separated mac-like
      dock surface, exact `x/y/w/h` widget grid, collision handling,
      pin/duplicate/remove, undo/redo/reset, per-workspace persistence,
      widget gallery, persistent dock editor/settings, NOVA command center
      mock bridge, private-data-safe demo mode, and Ctrl+Alt+N emergency
      desktop exit. The existing native Tkinter skin remains the
      wallpaper-attached desktop surface and now also treats Ctrl+Alt+N as an
      emergency hide shortcut.
- [x] Dashboard packaged as a native Windows app (2026-07-18): added a
      Tauri/WebView2 wrapper under `Dashboard/src-tauri`, generated an
      original NOVA icon, added `desktop:dev`, `desktop:doctor`, and
      `desktop:build` scripts, and built both
      `Dashboard/src-tauri/target/release/nova-desktop.exe` and the NSIS
      installer at
      `Dashboard/src-tauri/target/release/bundle/nsis/NOVA Desktop_1.0.0_x64-setup.exe`.
- [x] Dashboard app default size adjusted (2026-07-18): the packaged Tauri
      shell was tightened for Ahmed's 1280x720 display before the later widget
      split replaced the centered/focused app-style launch behavior.
- [x] Dashboard packaged window converted to a widget (2026-07-18): the Tauri
      wrapper is frameless with no Windows minimize/maximize/close chrome,
      keeps native resizing enabled, exposes native drag/resize commands, and
      adds a bottom-right resize grip to the React shell. Close requests are
      prevented so the widget can be hidden through NOVA controls instead.
- [x] Dashboard blank-start widget layout (2026-07-18): new/refreshed settings
      start with empty workspaces, hide the edit strip until a widget exists,
      and expose widget/search/status/dock shortcuts from the bottom `+` hover
      menu.
- [x] Dashboard DOCX UI/UX refinement pass (2026-07-18): implemented
      Orb/Panel/Dashboard interface modes, Ctrl+Space command palette, selected
      widget highlighting, drag-handle plus three-dot widget controls, and
      auto-dismissing slide-in toast notifications.
- [x] Dashboard desktop-widget refactor (2026-07-18): added Desktop Widget
      mode as the default shell, made the Tauri/WebView2 window transparent
      and frameless, added a shared work-area layout engine for clamp,
      normalization, collision repair, safe popover placement, and widget
      mode sizing, removed forced grid widths so the surface fits smaller
      screens, and upgraded the bottom `+` gallery with search and category
      filters. Verified with `pnpm run typecheck`, `pnpm run build`,
      `pnpm run desktop:build`, Dashboard skin tests 7/7, driver `tools`
      33/33, and a full driver `chat` time check.
- [x] Dashboard default-state cleanup (2026-07-18): Desktop Widget mode now
      launches locked and visually quiet, with no startup notification cards,
      no visible empty-editor grid, one-line `NOVA ready` status, header
      controls collapsed into a compact `...` menu, and the bottom `+` moved
      away from the resize grip. Verified with `pnpm run typecheck`,
      `pnpm run build`, and `pnpm run desktop:build`; final NOVA smoke checks
      are recorded in the task result.
- [x] Dashboard panel usability fix (2026-07-18): replaced independent
      gallery/settings/dock/command booleans with one active-panel state so
      opening one surface closes the previous one, added click-away dismissal,
      made command submission and widget add actions close their panels, and
      replaced cryptic bottom `+` action initials with readable labels.
      Verified with `pnpm run typecheck`, `pnpm run build`, `pnpm run
      desktop:build`, Dashboard skin tests 7/7, driver `tools` 33/33, and a
      full driver `chat` time check.
- [x] Dashboard dynamic desktop-widget refinement (2026-07-18): default
      Desktop Widget mode gained a compact main rounded rectangle, separated
      taskbar, pinned NOVA status/clock/system starter widgets, native
      compact/expanded window sizing, visual widget previews in the add
      gallery, and stricter pinned-widget behavior that hides movement/resize
      controls until unpinned. Verified with `pnpm run typecheck`, `pnpm run
      build`, `pnpm run desktop:build`, Dashboard skin tests 7/7, driver
      `tools` 33/33, and a full driver `chat` time check.
- [x] Dashboard native widget split (2026-07-18): the packaged Tauri shell now
      creates two transparent frameless WebView2 widget surfaces: a resizable
      main widget window (`780x250` default when populated) and a separate
      taskbar window (`720x76`) loaded with `?surface=dock`. Both skip the
      Windows taskbar, stay on top, avoid startup focus stealing, and are
      positioned near the bottom of the desktop. The dock sends add/search/
      settings requests to the main surface through a local storage bridge.
      Verified with `pnpm run typecheck`, `pnpm run build`, `pnpm run
      desktop:build`, Dashboard skin tests 7/7, driver `tools` 33/33, and a
      full driver `chat` time check; the launched process reported no main
      taskbar window handle.
- [x] Dashboard page model and emergency quit bridge (2026-07-18): Dashboard
      mode now uses the agreed three-page model: Main Dashboard for the
      customizable widget canvas, NOVA Activity for orb/runtime talk/model/
      timeline and a safe Obsidian graph visualization, and Apps for pinned
      plus detected Start Menu apps in the packaged widget. The `+` widget
      flow is limited to Main Dashboard, dock-side Tauri commands are allowed
      by the capability file, and `Ctrl+Alt+N` now quits `nova-desktop.exe` in
      the packaged widget while keeping the browser preview fallback as a
      hide/restore state. Verified with local `tsc --noEmit`, Vite build,
      `CI=true` Tauri build, Dashboard skin tests 7/7, driver `tools` 33/33,
      a full driver `chat` time check, and a local launch of the corrected
      packaged widget.
- [x] Dashboard desktop-layer correction (2026-07-18): removed the packaged
      widget's always-on-top behavior so normal app windows can cover NOVA,
      changed the default launch mode to the larger Dashboard widget, bumped
      persisted settings to avoid stale tiny layouts, and resized the main
      surface to `980x540` by default while keeping the separate `720x76`
      dock/taskbar surface.

In progress / blocked:

- [ ] Dashboard Calendar/Tasks "add" support (started 2026-08-01): Tasks
      currently only supports toggling existing items done
      (`Dashboard/feeds.py`'s `set_task_done`) — no add-a-task UI yet.
      Calendar is read-only by design (`nova_integrations`'s Google/Microsoft
      connectors request only `*.readonly` scopes), and neither account is
      connected yet. Ahmed has step-by-step instructions for the Google
      Cloud OAuth Desktop client and Azure AD app registration needed before
      Calendar-add can be built; add-a-task (local, no OAuth) can proceed
      independently.
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
- [x] Desktop dashboard bridge: the final five-page shell uses the local
      HTTP/WebSocket server for real feeds, Windows app discovery/launching,
      approval decisions, and LiveKit text-turn delegation.
- [ ] Obsidian graph bridge: replace NOVA Activity's safe graph contract with
      real vault metadata from `[[links]]`, tags, and safe note identifiers,
      without rendering private note bodies by default or committing vault
      data.
- [ ] Always-on NOVA app shell: add tray startup, standby/listening states,
      minimize-to-tray, and a tray menu for opening/closing the widget while
      the existing LiveKit/Gemini voice pipeline remains the only assistant
      backend.

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
- [x] Large exported conversations — existing ChatGPT/development assistant Markdown exports
      in the vault are searchable, and long reads return query-focused
      excerpts instead of refusing the file.
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

- [x] Choose the final dashboard/HUD design. The refined prototype direction
      has been integrated into `Dashboard/` as the active React/Vite shell.
- [ ] Add a live NOVA event bridge for runtime state, transcript, tool calls,
      permissions, and cancellation.
- [ ] Add Windows app registry and real icon extraction/cache for the dock.
- [ ] Add real Obsidian graph metadata adapter for the NOVA Activity page.
- [ ] Replace mock Tauri commands with the real private Python NOVA bridge.
- [ ] Desktop polish: tray/startup behavior, minimize-to-tray, always-on
      standby/listening, multi-monitor placement, and live state animations.

- Historical reference: the parked website (Phase 5, commit `fea9a3f`) still
  has useful LiveKit transcript/tool-panel patterns.
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
4. Update the "Last updated" date here and in `DEVELOPMENT.md` if the stack or
   rules changed.
<!-- NOVA-A1-CORE-INTELLIGENCE BEGIN -->
## A1 Core Intelligence — Lab checkpoint (2026-09-06)

A1 scope:
- generated ProjectState v1
- provenance and freshness
- UNKNOWN-safe project resolver
- bounded failed-approach awareness
- tiny base + relevant project context packets
- shadow evaluation with >=50 evaluable turns, >=95% precision, <=2%
  confident-wrong rate, and zero wrong-project protected-action injections
- one intrinsic read-only Core Intelligence tool

A1 does not automate REMEMBER/write-back; that remains A2.

A1 transaction state: VERIFIED LAB CHECKPOINT - commit `f9e4f46c41c6a8f027f99f5f2efb53f2f0939ffa` (2026-09-06, "Add NOVA A1 Core Intelligence shadow awareness"), confirmed an ancestor of the verified Unified Persistent U1 checkpoint `8cd7bd1dc8da8ed3b8d6e30af9d76e8f5f68b51c`. LAB only - NOT production/ACTIVE.
<!-- NOVA-A1-CORE-INTELLIGENCE END -->
