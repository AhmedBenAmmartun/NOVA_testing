# A1 Core Intelligence Architecture

## Status

A1 builds on the verified A0 verification-contract checkpoint. It is a
read-only awareness layer for the unified NOVA agent.

A1 follows the canonical operating loop:

```text
SENSE -> REASON -> ACT -> VERIFY -> REMEMBER
```

A1 implements the SENSE foundation and the context needed for better REASON.
A0 already strengthened VERIFY. Automatic REMEMBER is deliberately deferred to
A2.

## Core boundary

A1 does not create a new user-facing mode and does not create a new NOVA OS
capability ID.

The one model-facing A1 tool,
`get_nova_core_context`, is placed in the always-present intrinsic/control tool
surface. It is not a permission boundary and grants no authority.

`Assistant` owns one `ContextBroker` per session. There is no process-global
broker singleton.

## Components

### ProjectStateBuilder

Reads current project state from bounded, explicit sources:

- configured project root
- read-only Git commands
- `README.md`
- canonical capability definitions
- selected documentation filenames
- trusted local test-evidence file when configured

It does not crawl drives or inspect unrelated projects.

### Provenance

Every material observed fact can carry:

- source kind
- source identifier/path
- observation timestamp
- SHA-256 digest
- bounded note

Raw user transcript/task content is not stored for provenance.

### Freshness

Facts are classified using explicit policies. A previously verified fact can
become STALE/EXPIRED rather than remaining silently trusted.

### Resolver

Project resolution uses explicit candidates only. Exact path, exact configured
alias, or unique cwd containment can resolve. Fuzzy neighboring-project guesses
are rejected as UNKNOWN/AMBIGUOUS.

### FailedApproachIndex

Scans only bounded Markdown sources inside the selected project and extracts
lines containing explicit failure signals such as "root cause", "failed",
"regression", "superseded", "blocked", and "do not assume".

This is read-only. It does not write memory.

### ContextBroker

Produces:

1. tiny base packet — project id, branch, HEAD, dirty state;
2. bounded project packet — milestone, changed files, capability ids, selected
   issues/decisions, failed approaches, test evidence, conflicts.

The project packet is only generated when the task is project-bearing.

### ShadowEvaluationStore

Stores structured booleans/counters only, not task text.

Graduation requires:

- at least 50 evaluable project-bearing turns;
- precision >= 95% on turns where project context was injected;
- confident-wrong rate <= 2%;
- zero wrong-project injections that would have changed a protected action.

Meeting the metrics does not automatically enable influence. Trusted runtime
configuration must also opt in.

## Source authority

A1 encodes this priority:

1. current repository/files
2. Git state
3. tests/logs/runtime
4. current conversation
5. project docs/ADRs
6. older history

When documentation conflicts with verified implementation, implementation wins
and documentation should be corrected.

## Security invariants

A1:

- has no approval tool;
- has no release/promotion tool;
- has no production activation;
- has no arbitrary shell;
- uses `subprocess.run(..., shell=False)` with fixed read-only Git arguments;
- never invokes `git add`, `commit`, `push`, `reset`, `clean`, `checkout`,
  `switch`, or `stash` at runtime;
- stores shadow-eval state outside the repository by default;
- keeps NOVA and Valo separate.

## Relationship to A0 and A2

A0: verification contracts for meaningful mutations.

A1: read-only current-state intelligence with provenance, freshness, UNKNOWN
safety, and shadow evaluation.

A2: automatic REMEMBER, conservative dedupe-on-write, preflight, Definition of
Done enforcement, and broader conflict handling.
