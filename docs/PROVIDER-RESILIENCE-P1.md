# NOVA Provider Resilience P1

## Status

**LAB / NOT ACTIVE.**

P1 starts from the frozen Provider Resilience P0 checkpoint
`b8f59e16f4f9e8ca3bfa2130208466f1485570be` in
`C:\Projects\NOVA-Labs\nova-provider-resilience-p1` on branch
`lab/nova-provider-resilience-p1-20260907`.

P0 remains untouched. No Git checkpoint has been created for P1 yet.

## Goal

P1 makes NOVA remember provider failures long enough to avoid retry storms, and
adds structured health reporting for the Gemini native realtime lane.

It extends the existing provider registry/router. It does not add a second
router, a model-broker dependency, or a new generic runtime health system.

## Text-provider circuit breaker

`nova_core.provider_health.ProviderHealthTracker` is process-local and stores
only safe operational metadata. It never stores prompts, responses, API keys,
or raw provider error messages — only a failure category and the exception
class name.

Rules:

- request-specific rejections do not poison provider availability;
- rate-limit/quota failures open the circuit immediately;
- connection, timeout, and server-unavailable failures open after the
  configured consecutive-failure threshold;
- while OPEN, the router skips the provider instead of spending latency,
  cloud-budget allowance, and another doomed API request;
- after cooldown, exactly one HALF_OPEN probe is admitted;
- a successful probe or response closes and resets the circuit;
- a failed HALF_OPEN probe reopens immediately without restarting the
  threshold count;
- explicit `ProviderRegistry.health_check*()` probes feed the same state,
  **except** while a rate-limit circuit is standing (see below).

Cooldowns use `time.monotonic` by default so a wall-clock change cannot
silently extend or cancel one. Tests inject a fake clock instead of sleeping.

Defaults (operational tuning only — no secrets, safe to publish in
`.env.example`):

- `NOVA_PROVIDER_CIRCUIT_BREAKER_ENABLED=true`
- `NOVA_PROVIDER_FAILURE_THRESHOLD=2`
- `NOVA_PROVIDER_TRANSIENT_COOLDOWN_SECONDS=30`
- `NOVA_PROVIDER_RATE_LIMIT_COOLDOWN_SECONDS=120`
- `NOVA_PROVIDER_CONFIGURATION_COOLDOWN_SECONDS=300`
- `NOVA_PROVIDER_UNEXPECTED_COOLDOWN_SECONDS=30`

### Only a real generation clears a rate-limit circuit

`ProviderRegistry.health_check()` is a generic reachability probe — it lists
models or pings a base URL. A rate-limited provider answers that call happily
while still refusing completions, so the probe proves nothing about the
generation quota in either direction.

While a rate-limit circuit is OPEN or HALF_OPEN,
`ProviderHealthTracker.record_probe_result()` therefore ignores generic probes
entirely and returns `False`:

- a **successful** probe does not close the circuit or shorten the cooldown;
- a **failed** probe does not overwrite `rate_limit` with `unavailable`, which
  would replace the 120s cooldown with the 30s transient one.

Recovery is proven by the routed HALF_OPEN **generation** attempt after the
cooldown expires. A configuration failure (`configured=False`) is still
recorded, because a missing key is not a quota question.

`rate_limit_circuit_is_authoritative()` exposes this predicate.

## One shared health tracker

`ProviderRegistry` and `ModelRouter` must observe the same circuit state. Two
independent trackers would mean a provider a probe has already marked unhealthy
still looks healthy to routed traffic.

```
ProviderHealthTracker
  |
  +---- ProviderRegistry
  |
  +---- ModelRouter
```

`create_model_router()` resolves the tracker once, *before* the registry is
built, and passes the same instance into both. `ModelRouter` also defaults to
`registry.health_tracker` when it is constructed directly, so the invariant
holds on the non-factory path too.

## Failure classification

P1 adds `ProviderRateLimitError`, a subtype of `ProviderUnavailableError`, so
quota/rate-limit failures can receive a longer cooldown while every existing
`except ProviderUnavailableError` caller keeps working.

`classify_provider_error` maps NOVA's provider errors onto five safe
categories:

| Category         | Source                                            | Effect on health              |
| ---------------- | ------------------------------------------------- | ----------------------------- |
| `not_configured` | `ProviderNotConfiguredError`, auth/config failures | opens, long cooldown          |
| `rate_limit`     | `ProviderRateLimitError`, 429                      | opens immediately, longest    |
| `unavailable`    | timeout, connection, 408, 5xx                      | opens at the threshold        |
| `request`        | ordinary request-specific 4xx                      | **never** opens the circuit   |
| `unexpected`     | anything else                                      | opens at the threshold        |

Adapter mapping:

All three adapters classify `APIStatusError` identically: 429 becomes
`ProviderRateLimitError`, 408 and 5xx become `ProviderUnavailableError`, and
other 4xx stay `ProviderRequestError`. OpenAI and Groq additionally map the
SDK's own `RateLimitError` to `ProviderRateLimitError`.

Ollama is usually local, but an Ollama-compatible proxy or hosted endpoint can
rate-limit, and a divergent adapter would silently deny the circuit breaker the
one signal it most needs.

## Gemini native realtime health

P1 does not replace Gemini Live with a text provider.

`nova_core.realtime.classify_realtime_error` classifies realtime failures into
`RealtimeFailureKind` (authentication / rate_limit / unavailable / request /
unknown) from the status code first, then from the exception class name and
message tokens. Only the resulting category and the exception class name are
kept — never the raw message.

**It must be given the provider exception, not LiveKit's wrapper.** LiveKit
does not hand the observer the provider's error directly: it wraps it in
`livekit.agents.llm.RealtimeModelError`, a pydantic model that owns the
`recoverable` flag and carries the real exception in `.error`.

The wrapper has no `status_code`, and its class name is always
`RealtimeModelError`. Classifying it produced `unknown` for every
status-code-driven failure (429, 503, 401, 403, 400 all collapsed to
`unknown`), and the stored class name was the wrapper's, which identifies
nothing. Worse, the message-token fallback then read `str(wrapper)` — and
pydantic's repr embeds the inner exception's **raw message**, exactly the
surface P1 promises never to touch.

`agent._unwrap_realtime_error(error)` returns `(provider_exception,
recoverable)`: the category comes from the inner exception, the `recoverable`
flag stays LiveKit's, and only the category plus the inner exception's class
name are stored or published.

`agent.py` installs `_install_realtime_provider_health(...)`, an
`AgentSession` error observer that records safe metadata into the **existing**
`NovaRuntime` health registry under `provider:<name>:realtime`:

- HEALTHY on session start and while configured;
- DEGRADED when LiveKit reports the error as recoverable;
- FAILED when it is not, and on agent startup failure.

The same safe state is published on the `nova.provider-status` LiveKit text
topic for future UI use. The payload carries provider, lane, state, failure
kind, LiveKit's recoverable flag, and the exception class name — no prompts,
transcripts, or raw provider text.

Two deliberate constraints:

1. P1 does **not** mutate LiveKit's `recoverable` field. Existing LiveKit
   session recovery/close semantics remain authoritative; the observer reads
   that flag and never writes it.
2. A realtime provider failure marks **one component** degraded or failed. It
   is deliberately not a statement that NOVA as a whole is dead, and it does
   not touch the `runtime` component the durable task layer owns.

The observer is installed immediately after `runtime = NovaRuntime()` and
before durable task recovery, so the lane has a health component before any
traffic runs. Durable task recovery, permission cleanup, session logging, the
personality stream, `video_input=True`, all-video turn coverage, and the
interruption tuning are unchanged.

## Still deferred

Actual non-Gemini voice fallback remains a later Provider Resilience milestone:

`LiveKit audio -> STT -> existing ModelRouter -> TTS`

Groq, OpenAI, and Ollama are text-generation adapters. P1 continues to fail
closed if one of them is selected as if it were a native realtime provider.
That lane needs explicit latency, interruption, privacy, and vision tests
before it can become a fallback for normal NOVA conversation.

## Implementation note — why P1 was not installed by patch

The v1.0.2 one-shot installer failed on a single operation, `agent.py` /
"agent installs realtime health monitor". It anchored on this exact string:

```
    runtime = NovaRuntime()

    # Recover durable task state before anything new is dispatched.
```

The real frozen P0 source has a three-line comment there, so the anchor never
matched. A read-only simulation confirmed 42 of the 43 intended operations
matched both the clean worktree and the frozen P0 blobs — this was a brittle
exact-string installer bug, not source drift and not an architectural
mismatch.

P1 was therefore implemented structurally against the real current source.
The full multiline durable-task comment is intentionally preserved verbatim,
and `tests/test_nova_provider_resilience_p1.py` asserts both that comment and
the ordering `runtime = NovaRuntime()` → health install → `TaskStore().recover()`,
so the same class of mis-anchoring is caught by the suite rather than by a
failed install.

## Verification

Run from the worktree root with the project venv:

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& "C:\Projects\AI Agent\venv\Scripts\python.exe" -m pytest -q
& "C:\Projects\AI Agent\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
```

Recorded on 2026-09-09, after the three review blockers below were fixed:

- targeted P1 suite: **57 passed**;
- P0 provider-resilience + agent runtime wiring: **25 passed**;
- vision contracts (phase 1, transport V3.2, session V3.3, typed camera V3.4,
  glass personality): **34 passed**;
- A1 / core-intelligence / capability / security / learning regressions:
  **59 passed**;
- out-of-suite router/provider simulation: **16/16 checks**;
- full suite: **880 passed** (frozen-P0 baseline was 823; +57 new P1 tests, no
  regressions);
- NOVA local tools driver: **35/35**;
- `git diff --check`: clean.

One full-suite run before these numbers showed a single failure in
`tests/test_nova_class_recovery.py::test_recorder_survives_a_hard_crash_of_the_intelligence_process`.
It passes in isolation (10/10) and on a repeat full run, spawns real OS
subprocesses with wall-clock waits, and references nothing in `nova_core`,
`providers`, or `agent.py`. Recorded as pre-existing load-dependent flakiness,
not a P1 regression — **NEEDS VERIFICATION** as its own item.

### Review blockers fixed

1. **Realtime wrapper not unwrapped.** `classify_realtime_error()` was given
   LiveKit's `RealtimeModelError`, so every status-code-driven failure
   classified as `unknown`, the stored class name was always the wrapper's, and
   the message fallback read the wrapper's repr — which embeds the raw provider
   message.
2. **Generic probe could clear a rate-limit circuit.** A successful
   `health_check()` closed it outright; a failed one rewrote `rate_limit` to
   `unavailable` and cut the 120s cooldown to 30s.
3. **Ollama 429 mapped to `ProviderRequestError`**, so a rate-limited
   Ollama-compatible endpoint never opened a circuit.

Each fix is covered by a test that was confirmed to fail against the pre-fix
behavior.

NOVA's venv has no `pytest-asyncio`, so the P1 tests drive async scenarios
through `asyncio.run(...)` inside sync tests — the convention the rest of the
NOVA suite already uses.
