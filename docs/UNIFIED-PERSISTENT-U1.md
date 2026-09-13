# NOVA Unified Persistent — U1

## Status

**VERIFIED LAB CHECKPOINT / NOT ACTIVE.**

- Checkpoint: `8cd7bd1dc8da8ed3b8d6e30af9d76e8f5f68b51c`
- Remote: `testing` only
- Production/main: **not promoted**
- Final checkpoint gate: **914 tests, 0 failures**

U1 is the first phase of the Unified Persistent NOVA build order. It unifies
the two lines that had diverged from `cd6e8d0` and reconciles the one place
they genuinely interact.

## Verified starting state

| | |
| --- | --- |
| Worktree | `C:\Projects\NOVA-Labs\nova-unified-persistent` |
| Branch | `lab/nova-unified-persistent-u1-20260910` |
| Base | `5a820497310761056171f0d62ae6bfc41db58635` (Provider Resilience P1) |
| Merged in | `3e53d33bcc49a707725a245d12395be85ba4daf6` (Class Intelligence) |
| Common ancestor | `cd6e8d00706c002538b1f47320e22a3c0461df44` |

Measured baselines, before any U1 change:

- P1 checkpoint: **880 passed**
- Class Intelligence branch: **708 passed** (measured in a throwaway detached
  worktree, then removed)
- Class-specific files on the Class branch: **26 passed**
- Common ancestor arithmetic: 682 base + 198 P1 + 26 Class = **906 expected**

## Goal

One NOVA that has both provider resilience and Class Intelligence, with the
budget/circuit interaction reconciled deliberately rather than by whatever Git
happened to produce.

## What Git did, and why that was not enough

`merge-tree` reported **zero conflicts**. Exactly one file overlapped:
`nova_core/router.py`. Both branches had inserted code into the *same two*
`except` blocks — P1 added circuit-breaker health recording, Class added cloud
budget refunds — at slightly different anchor points, so Git interleaved them
without complaint.

A clean textual merge said nothing about whether the two mechanisms compose.
They do, but one Class test encoded the old mechanism and failed immediately:

```
tests/test_nova_class_cloud_budget_refund.py
  ::test_a_dead_provider_no_longer_drains_the_shared_class_cap
  AssertionError: openai was attempted every time
  assert 2 == 10
```

## The reserve/refund/skip contract

The merged router's control flow, verified in order:

1. circuit admission — an open circuit `continue`s **before** any budget call;
2. cloud budget reservation;
3. on budget refusal, the half-open probe slot is released (no refund: nothing
   was reserved);
4. `provider.generate()`;
5. on failure, health is recorded **and** the reservation is refunded.

The rule that makes it coherent:

> A reservation is taken only when NOVA actually calls a provider. Anything
> that stops NOVA before the call must not reserve, and must therefore not
> refund either.

`CloudUsageBudget.release()` is guarded (`if reserved <= 0 or used <= 0:
return`), so refunding a provider that holds no reservation is a harmless
no-op. That guard is precisely why the dangerous case needs its own test: a
provider that **already holds a legitimate reservation** and is later skipped.
A spurious refund there would pop a unit that funded a real answer and quietly
inflate the daily cap. `test_skipping_a_provider_never_refunds_an_answer_it_already_gave`
pins that.

## Semantic reconciliation performed

### 1. The superseded Class expectation — SUPERSEDED, not deleted

`test_a_dead_provider_no_longer_drains_the_shared_class_cap` asserted openai
was attempted all ten times, because the refund was the only thing standing
between a dead provider and the shared cap.

P1's circuit breaker stops attempting after
`NOVA_PROVIDER_FAILURE_THRESHOLD` (2) consecutive failures, so the real number
is 2. **The invariant is unchanged and still asserted**: all ten questions
answered, `openai == 0` in the ledger, `groq == 10`, `used_today == 10`. P1
makes the invariant *stronger* — a skipped provider never reserves at all, and
the lecture stops paying a timeout on every question.

The call-count assertion now derives the threshold from
`router.provider_health.failure_threshold` rather than hard-coding it, and
asserts the attempt count is strictly below the question count. The original
reasoning is preserved in the test's docstring, marked as superseded.

### 2. Class Intelligence keeps its own circuit — APPROVED DECISION

`nova_capture/intelligence.py:_get_class_router()` calls
`create_model_router()`, which mints its own `ProviderHealthTracker`. NOVA
therefore runs two circuits: one for conversation, one for the lecture.

Per the approved U1 decision this is kept as **internal isolation**, not a
user-facing mode. A lecture burning a provider's quota must not silence the
conversation Ahmed is having, and vice versa. P1's invariant — a registry and
its router share one tracker — still holds inside each router.

No global `ProviderHealthManager` was introduced. Class-specific cooldowns were
**not** tuned; there is no real-world evidence yet to tune against.

`test_class_intelligence_keeps_a_health_tracker_of_its_own` pins this decision
so it cannot drift back by accident.

### 3. Test stubs completed

P1's `FakeBudget` had no `release()`. Post-merge the router calls it, raising
`AttributeError` into a defensive `except Exception` — tests pass while
silently logging tracebacks. `release()` was added, and the same gap was found
and fixed in the out-of-suite simulation's `AllowBudget`.

## Verification

Every fix is covered by a test confirmed to **fail** against the broken
behavior (mutation-checked, so none pass vacuously):

| Mutation | Caught by |
| --- | --- |
| refund on a skipped provider (double-refund) | `test_skipping_a_provider_never_refunds_an_answer_it_already_gave` |
| drop the refund from the failure handler | 6 budget/circuit tests |
| drop the circuit skip entirely (P1 regression) | reconciled Class refund test |

Regression matrix:

| Tier | Scope | Result |
| --- | --- | --- |
| 0 | compile + import | OK |
| 1 | Provider Resilience P1 | **57 passed** |
| 2 | Class Intelligence (2 files) | **26 passed** — matches pre-merge baseline |
| 2b | U1 budget × circuit integration (new) | **8 passed** |
| 3 | P0 + agent runtime wiring | **25 passed** |
| 4 | Vision contracts ×5 | **34 passed** |
| 5 | A1 / capability / security / learning | **66 passed** |
| 6 | Class capture / recovery / evidence | **81 passed** |
| 7 | Router/provider simulation | **16/16** |
| 8 | Full unified suite | **914 passed**, 0 failed |
| 9 | NOVA tools driver | **35/35** |
| 10 | `git diff --cached --check`, secret guard | clean |

The full-suite arithmetic closes exactly:

```
682  common ancestor cd6e8d0
+198  Provider Resilience P1 lineage
 +26  Class Intelligence
  +8  new U1 budget x circuit integration tests
----
 914  measured
```

Nothing was lost in the merge and nothing regressed. The Class files returned
to their pre-merge baseline of 26 once the superseded expectation was
reconciled.

## Invariants held

Verified on the merged tree and again on the working tree: Gemini remains the
only native realtime lane (`gemini_realtime`,
`RealtimeProviderUnsupportedError` ×3); `video_input=True`;
`llm=realtime_model`; realtime health observer; durable task recovery;
permission cleanup ×2; conversation recording; false-interruption tuning;
`ContextBroker()`; A1 project state and provenance; P1 circuit breaker;
Class refund path; `class_intelligence` registered as a **capability**, not a
mode; no Valo paths; no secrets or recordings.

## Still NEEDS VERIFICATION

- **Live Gemini/LiveKit runtime behavior.** Unchanged from P1 — all evidence
  remains static and unit/integration-level.
- Whether two independent health trackers is right long term, or whether U4's
  Intelligence Fabric should own one capability-aware health model.
- Class-appropriate cooldowns, pending real lecture evidence.
- `test_nova_class_recovery` hard-crash flakiness under full-suite load.

## Next phase

U2 — persistent NOVA runtime/lifecycle. Not started; requires approval.
