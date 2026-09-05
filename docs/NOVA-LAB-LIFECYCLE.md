# NOVA Lab Lifecycle

Status: LAB foundation, V1A.

NOVA remains one user-facing agent. "NOVA Lab" is an internal development
lifecycle, not a separate mode or persona.

## Lifecycle

`LAB -> CANDIDATE -> ACTIVE -> RETIRED`

- **LAB**: isolated experimental work.
- **CANDIDATE**: automated gates passed; waiting for Ahmed's approval.
- **ACTIVE**: the production implementation/provider.
- **RETIRED**: preserved and recoverable, excluded from normal rotation.

A rejected candidate returns to LAB. A retired feature may be reopened in LAB.
There is no direct LAB -> ACTIVE transition.

## V1A security boundary

V1A provides data/state primitives, constrained Git worktree operations and an
allow-listed test runner. It intentionally does **not** provide:

- model-callable promotion;
- model-callable retirement of an ACTIVE feature;
- production restart;
- rollback execution;
- arbitrary shell commands;
- arbitrary pytest arguments;
- deletion of retired implementations;
- direct writes into the production worktree.

Lifecycle state is not authorization. Future promotion/restart operations must
go through `nova_policy`; only the trusted user principal may approve them.

## Storage

Runtime feature state and lifecycle history default outside Git under:

`%LOCALAPPDATA%\NOVA\Lab\`

Tests inject temporary paths and never use the real runtime state.

The JSON registry is authoritative in V1A. Each mutation stores its event id
inside the same atomic registry replacement before the append-only JSONL journal
is updated. If the journal is temporarily unavailable, the next registry
instance reconciles the missing event from authoritative state. V1A remains
single-writer; the future release supervisor will own mutations before
production promotion/restart is exposed.

## Git isolation

Development branches must begin with `lab/`. Worktrees managed by NOVA Lab must
remain under the configured labs root, normally:

`C:\Projects\NOVA-Labs\`

The active NOVA worktree is not a Lab worktree.

## Testing

The test runner accepts named profiles only and verifies that the target is
the root of a real Git worktree on a checked-out `lab/*` branch. A random folder
under the Labs directory is not sufficient. V1A includes:

- `nova_lab`: NOVA Lab's own focused tests.
- `official`: `python -m pytest -q tests`

`pytest.ini` sets `testpaths = tests` so a bare pytest invocation does not
accidentally collect ignored archives or pending repository copies.

## Next phases

V1B: register/read Lab features through an inactive `development` capability,
without promotion/restart tools.

V1C: trusted candidate gating and `nova_policy` integration.

V2: out-of-process release supervisor, transactional activation, health check,
rollback, restart, and retirement after explicit user approval.
