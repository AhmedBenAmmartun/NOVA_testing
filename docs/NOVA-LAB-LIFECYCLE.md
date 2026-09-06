# NOVA Lab Lifecycle

Status: LAB foundation, V1A + V1B (model-facing `development` capability).
This is a LAB checkpoint, not a production-ready or ACTIVE milestone.

NOVA remains one user-facing agent. "NOVA Lab" is an internal development
lifecycle, not a separate mode or persona. "development" is a capability of
the one NOVA agent, not a separate agent or persona.

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

## V1B: model-facing `development` capability

V1B adds an inactive-by-default (`default_active=False`) NOVA OS capability,
`development` (`nova_os/catalog.py`), giving the model a narrow, read/register
surface over V1A's primitives. Its only tools (`tools/development.py`) are:

- `lab_status`
- `list_lab_features`
- `get_lab_feature`
- `list_lab_test_profiles`
- `register_lab_feature`

There is no model-facing test execution, lifecycle transition, promotion,
retirement, restart, rollback, deletion, shell, or approval tool. Activating
the capability (via the existing generic `activate_capability` control tool)
only adds these five tools to the live session; it grants no additional
authority beyond what they do.

`register_lab_feature` (`nova_lab/service.py: DevelopmentService
.register_existing_feature`) enforces every V1A provenance check plus one
more:

- safe validated feature id and capability id
- **`capability_id` must be one of NOVA's real capabilities** — validated
  against `nova_os.capabilities.CANONICAL_CAPABILITY_IDS`, the same canonical
  id set `nova_os.catalog.build_default_capability_manager()` asserts its
  registered, tool-wired capabilities against (the two are checked for
  equality at every manager construction, so they cannot silently drift).
  This is the single source of truth for capability identity; NOVA Lab does
  not maintain a second, separately-hardcoded list.
- branch matches `lab/*`
- path is the exact root of an existing Git worktree
- worktree is under the approved NOVA Labs root
- worktree shares the same NOVA Git repository (`git-common-dir` match)
- worktree is clean
- branch matches the branch the caller claimed
- test profile is one of the named, approved profiles
- `base_ref` resolves to an immutable commit SHA
- that resolved SHA is verified as an ancestor of the Lab worktree's HEAD
- registration always enters `LAB` state only; no transition tool exists
- an existing `feature_id` cannot be silently overwritten
- registry/journal state lives outside Git (`%LOCALAPPDATA%\NOVA\Lab\`)

`CapabilitySpec.permissions`/capability metadata remain informational, not an
authorization boundary — real authority still only flows through
`nova_policy` and explicit trusted-user approval, neither of which V1B
touches.

### Known limitation: same-turn dynamic tool activation (unresolved, tracked)

Verified against the real runtime (`livekit-agents==1.6.6`,
`livekit-plugins-google==1.6.6`): in a live Assistant session,
`search_capabilities` -> `activate_capability("development")` reports success
and does add the new tools to `Agent._tools`, but the model calling one of
those newly-activated tools (e.g. `list_lab_test_profiles`) within the SAME
`session.run()` tool-calling chain gets LiveKit's "Unknown function" error.
Traced to `livekit/agents/voice/agent_activity.py`: the tool list used for an
in-progress turn is captured once (`all_tools = self.tools.copy()` at
`_generate_reply()` for the pipeline/text path, or
`tool_ctx = llm.ToolContext(self.tools)` per realtime `GenerationCreatedEvent`
for the production voice path) and a same-turn recursive tool-response
continuation reuses that original snapshot instead of re-reading the
already-updated tool list. The production voice path is additionally gated by
Gemini Live only learning a new tool schema after a full session reconnect
(`google/realtime/realtime_api.py`'s `_mark_restart_needed()`).

- **VERIFIED**: same-turn use of a newly activated capability's tools fails.
- **NEEDS VERIFICATION**: whether those tools become usable on the
  *following* `session.run()` turn — blocked on Gemini free-tier daily quota
  for the two-turn diagnostic, not on anything in this codebase.
- Do not claim next-turn activation works. Do not claim dynamic activation is
  fixed or completely broken beyond the observed same-turn case.
- This is a NOVA OS capability-kernel property affecting every optional
  capability, not something specific to `development`, and its fix (most
  likely a stable dispatcher/gateway tool that never changes the
  model-visible schema, or gating always-registered tools through
  `CapabilityManager`/`nova_policy` instead of the tool list itself) is a
  separate future architecture decision, out of scope for this LAB
  checkpoint.

## Next phases

V1C: trusted candidate gating and `nova_policy` integration; background Lab
test execution through `NovaRuntime` with durable test evidence.

V2: out-of-process release supervisor, transactional activation, health check,
rollback, restart, and retirement after explicit user approval.

Separately, evaluate a stable capability-kernel dispatcher/gateway
architecture to resolve the dynamic-tool-activation limitation above; this is
its own design decision, not implied by V1C/V2.
