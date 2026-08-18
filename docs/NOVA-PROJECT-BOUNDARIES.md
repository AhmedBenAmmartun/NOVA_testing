# NOVA Project Boundaries

Status: active as of 2026-08-15.

## Inside NOVA

- Realtime LiveKit/Gemini agent
- NOVA OS capability kernel
- Native NOVA tools and integrations
- Declarative Skills Engine
- Permission/security policy
- NOVA Vision (`vision-client/`)
- Agent-side memory, task, automation, and plugin foundations

## Outside NOVA

- Legacy `Dashboard/`
- Valo dashboard/shell product
- Any future dashboard-specific UI/runtime

NOVA may expose a stable interface for external UI products later, but an
external dashboard must not be imported into `agent.py`, started as a hidden
NOVA child process, or own NOVA security approvals.

NOVA Vision is not the legacy Dashboard. It is a small trusted NOVA surface for
camera, microphone, captions, source selection, and privacy controls.

Historical logs and audits may still mention the old Dashboard. Those references
are retained as project history and do not represent active runtime dependencies.
