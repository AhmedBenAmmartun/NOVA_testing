# A1 Context Broker

## Goal

Provide enough current context to improve NOVA's reasoning without dumping the
entire repository/history into every turn.

## Two tiers

### Tier 1 — tiny base packet

Always cheap:

- NOVA identity
- project id
- Git branch
- Git HEAD
- dirty flag
- fact statuses

### Tier 2 — project packet

Generated only when the task text is materially project/technical:

- root
- milestone
- changed files
- capability ids
- selected issue/decision documents
- failed-approach entries
- trusted test evidence
- conflicts

The packet is bounded before rendering.

## Shadow behavior

A1 defaults to:

```text
project_status = SHADOW_ONLY
influence_allowed = false
```

A SHADOW_ONLY packet is advisory evaluation output. It cannot replace direct
verification for protected technical decisions.

Influence becomes possible only when:

1. `ShadowEvaluationStore.metrics().eligible` is true; and
2. trusted environment configuration explicitly sets
   `NOVA_CORE_PROJECT_INFLUENCE` to an enabled value.

The language model cannot change either requirement through a tool call.

## Cache

The broker caches generated ProjectState for a short TTL. Cache state is
derived/non-authoritative. A forced rebuild is always possible internally.

## Tool behavior

`get_nova_core_context(task)` is read-only. It returns a bounded textual packet
containing:

- packet status;
- influence flag;
- evidence rules;
- compact JSON data.

The tool never writes source files, changes Git, activates capabilities,
approves actions, or changes release state.
