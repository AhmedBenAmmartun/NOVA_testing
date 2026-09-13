# NOVA Unified Persistent — U2

## Status

**U2.1 VERIFIED TESTING CHECKPOINT / NOT ACTIVE.**

- Worktree: `C:\Projects\NOVA-Labs\nova-persistent-runtime-u2`
- Branch: `lab/nova-persistent-runtime-u2-20260912`
- Base: `0ea0e6158b50d144738ebe5ce852573d9efee0a2`
- U1 implementation: `8cd7bd1dc8da8ed3b8d6e30af9d76e8f5f68b51c`
- U1 final branch HEAD: `0ea0e6158b50d144738ebe5ce852573d9efee0a2`
- U2.1 implementation checkpoint: `b46c9d536b9e777627beb0d97880a36356e0e0fa`
- Remote: **`testing` only**
- Production/main: **not active / not promoted**

U2 makes NOVA itself persistent and provider-independent. U2.1 is the first
verified slice; it does not claim the whole U2 phase is complete.

## Goal

Turn NOVA from a system whose practical lifetime is too closely tied to a
realtime provider/session into a local Windows core that can exist before,
during, and after provider availability.

Target availability rule:

> Cloud services may improve NOVA, but losing a cloud service must never kill
> NOVA.

## Verified starting state

At U2 start, the repository already contained two useful but disconnected
halves:

1. `nova_startup.py` — a long-running startup/standby supervisor owning the
   Windows single-instance mutex, Guardian, and safe integration startup.
2. `nova_runtime` — `NovaRuntime`, EventBus, BackgroundJobManager, health, and
   durable `TaskStore`, but the runtime was constructed inside the LiveKit
   session after realtime provider construction.

That meant provider construction could fail before a `NovaRuntime` existed, and
a LiveKit job shutdown ended that session runtime.

The U2 branch was created clean from final U1 HEAD `0ea0e615...`.
Focused baseline before source edits: **81 passed / 0 failed**.

## U2.1 implementation

### 1. Persistent Core owns canonical durable storage

`NovaRuntime` is an in-process runtime container. It can receive an injected
`TaskStore`, but generic/session/worker runtimes do not create one implicitly.

`nova_startup.py` is the persistent NOVA Core composition root.
`build_core_runtime()` explicitly constructs the canonical durable `TaskStore`
and injects it into the persistent Core runtime.

`agent.py` keeps a session-local `NovaRuntime()` and does not recover or write
the canonical durable store. Full session-to-Core IPC/control-plane attachment
is not part of U2.1.

This ownership correction prevents generic/session workers from becoming
competing canonical writers. The existing `TaskStore` synchronization is
process-local, so implicit multi-process ownership would risk split-brain or
colliding durable-state writes rather than provide safe persistence.

### 2. Provider-independent local composition root

`nova_startup.py` now calls `build_core_runtime()` before Guardian or integrations.
That composition root creates `NovaRuntime(task_store=TaskStore())`, so canonical
durable recovery belongs to the persistent Core rather than a LiveKit session.

Task recovery runs at local-core startup. A recovery exception marks the
`task_store` component degraded and is logged safely; it does not kill NOVA
Core.

No LiveKit/model-provider import is required for this Tier-0 local process.

### 3. Optional subsystems are failure-isolated

Guardian startup, summary, and shutdown are wrapped so subsystem failure
degrades Guardian health instead of terminating NOVA Core.

Email/calendar integration startup retains its existing safe degradation
boundary and is reflected in core health.

This implements the availability-tier rule: a higher-level subsystem failing is
not the same thing as NOVA dying.

### 4. Runtime machine state moved outside Git

Startup status and logging no longer belong under repository `logs/`.

Current local runtime state:

```text
%LOCALAPPDATA%\NOVA\runtime\nova_status.json
%LOCALAPPDATA%\NOVA\runtime\nova_startup.log
```

This keeps machine/runtime evidence out of source control and aligns with the
existing durable runtime-root convention.

### 5. One local core per Windows user session

The existing Windows mutex `Local\NOVAStandbySupervisor` remains the
single-instance guard.

The final real Windows gate launched one core, then launched a second while the
first still held the mutex. The second reported:

```text
NOVA local core is already running.
```

Primary exit code: `0`. Duplicate invocation exit code: `0`.

## Verification

| Gate | Result |
| --- | --- |
| U2 focused baseline before edits | **81 passed** |
| U2.1 hardened targeted runtime suite | **92 passed** |
| P1 ownership reconciliation + U2 tests | **12 passed** |
| Full NOVA suite after ownership correction | **924 passed, 0 failed** |
| Real Windows local-core check | **PASS, exit 0** |
| Windows duplicate-instance guard | **PASS** |
| Runtime state outside Git | **PASS** |
| `git diff --check` | **PASS** |

Known warning: one non-blocking `google.genai.types` deprecation warning for
Python 3.17.

## Problems encountered and resolutions

### A. Patcher falsely rejected the correct Windows worktree

The first patcher compared Git's `C:/...` path string against Python's
`C:\...` string literally.

**Root cause:** representation comparison instead of path identity.

**Resolution:** convert both to resolved `Path` objects before comparing.

### B. Hardening guard corrupted `git status --porcelain`

The first hardening script called `.strip()` on porcelain output. That removed
the first line's leading status column, so ` M agent.py` became `M agent.py` and
the parser treated the path incorrectly.

**Root cause:** whitespace in porcelain output is data.

**Resolution:** preserve leading whitespace and remove only trailing CR/LF.

### C. Tests encoded the superseded session-owned persistence mechanism

The earlier U2.1 slice and source-string tests treated the LiveKit session as a
canonical-store owner and expected durable recovery inside `agent.py`.

**Root cause:** the tests pinned a superseded ownership mechanism. Making those
tests green by adding more locking would have preserved the wrong process
boundary instead of fixing it.

**Resolution:** correct ownership semantics instead. The persistent NOVA Core
owns the canonical `TaskStore`; generic/session/worker runtimes do not implicitly
own it. Stale tests were removed or reframed to assert that the LiveKit session
does not construct, recover, or write the canonical store.

Final full run after the ownership correction: **924 passed / 0 failed**.

### D. The first PowerShell process gate read a blank exit code

The original `Start-Process -PassThru` harness showed normal process output but
did not give a reliable primary `ExitCode` in that test shape.

**Resolution:** final gate uses `System.Diagnostics.Process`, waits for process
termination, and reads the actual exit code. Both primary and duplicate
invocations returned `0`.

### E. First slice still placed state under the repository

The initial U2.1 slice proved the core could start, but its status/log paths
still pointed into repository `logs/`.

**Resolution:** move machine/runtime state to `%LOCALAPPDATA%\NOVA\runtime`.

### F. Guardian needed a stronger isolation boundary

The initial local composition root could still let Guardian startup/summary
problems influence the core too strongly.

**Resolution:** Guardian attach/read/stop are now safe boundaries; failure is
recorded as degraded subsystem health while Tier-0 core stays available.

### G. A zero-byte test file produced misleading green evidence

During a repair, `tests/test_nova_provider_resilience_p1.py` was accidentally
written as a zero-byte file. A targeted pytest run then appeared green because
pytest collected no tests from that file.

**Root cause:** test-file integrity was not re-verified after a failed write path.

**Resolution:** restore that single test file from HEAD, verify its size/line
count, then rerun the targeted and full verification gates. A green test run is
not trustworthy when expected tests may have disappeared.

## What remains for U2

U2.1 is a foundation, not the end of U2.

**PLANNED / NOT IMPLEMENTED YET:**

- reconcile `Start-NOVA.ps1` so the persistent core starts independently of
  Vision/LiveKit without breaking the current Vision surface;
- configure/verify Windows user-session autostart/lifecycle;
- run a longer-lived standby/restart/recovery acceptance test;
- define an honest process boundary between persistent core and LiveKit/provider
  sessions — in-memory `NovaRuntime` cannot be shared across OS processes;
- add IPC/control-plane attachment if that is the approved U2 design;
- do not absorb U3's durable Task Manager work into U2;
- keep desktop automation in the interactive user session rather than pretending
  a Session-0 Windows service can control Ahmed's desktop.

## Still NEEDS VERIFICATION

- live Gemini/LiveKit failure behavior;
- cross-process core/session attachment design;
- Windows login/autostart behavior;
- long-duration standby/restart recovery;
- whether U4 later supersedes per-lane provider-health isolation.

## Approval boundary

Nothing in U2.1 is committed or pushed as of this document update.

Ahmed approved the U2.1 checkpoint on 2026-09-13. Implementation commit
`b46c9d536b9e777627beb0d97880a36356e0e0fa` is checkpointed on the `testing`
remote only. Production/main remains untouched.
