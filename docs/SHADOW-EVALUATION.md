# A1 Shadow Evaluation

## Purpose

A1 must prove that automatic project context is precise before it is allowed to
influence protected technical decisions.

## Stored data

The local shadow journal stores only structured evaluation fields:

- project_id
- evaluable
- packet_injected
- project_correct
- confident_wrong
- wrong_project
- protected_action_would_change
- abstained
- reason_code
- recorded_at

It does not store user transcript text or full task text.

Default location:

- Windows: `%LOCALAPPDATA%\NOVA\CoreIntelligence\shadow-eval.jsonl`
- fallback: `~/.nova/core-intelligence/shadow-eval.jsonl`

The file is local runtime state and is not committed.

## Graduation bar

All conditions must hold:

- >= 50 evaluable turns
- >= 95% precision on injected/evaluable turns
- <= 2% confident-wrong rate
- zero wrong-project injections that would have changed a protected action

Abstentions/UNKNOWN results are tracked but not treated as confident wrong
answers.

## No automatic graduation

`eligible=true` is a report only.

A1 also requires trusted runtime opt-in before influence can become allowed.
The model has no tool that can grant that opt-in.

## Simulation cases

The A1 test suite includes:

- 49 correct turns -> not eligible
- 50 correct turns -> metrics eligible
- one wrong-project protected-action case -> ineligible
- structured journal round-trip without transcript storage
