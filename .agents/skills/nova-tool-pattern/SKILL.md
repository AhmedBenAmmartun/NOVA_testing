---
name: nova-tool-pattern
description: Use when adding or changing a NOVA function tool in this LiveKit repo — module layout, error handling, registration, driver checks, and doc updates.
---

# How a NOVA tool is born

Every tool in this repo follows the exact same pattern. Copy it; do not
invent a new one.

## The pattern

1. **One small async function per tool** in the right module under `tools/`
   (desktop, files, information, media, models, vision, obsidian — or a new
   module if it's a genuinely new area).

```python
from livekit.agents import RunContext, function_tool
from .common import logger

@function_tool()
async def my_tool(context: RunContext, arg: str) -> str:
    """One-line docstring the LLM reads to know when to use this."""
    try:
        ...
        logger.info("my_tool: %s", arg)
        return "Human-friendly result NOVA can speak."
    except Exception:
        logger.exception("my_tool failed")
        return "NOVA could not do that."  # NEVER let a tool raise
```

2. **Errors are spoken sentences, not stack traces.** Catch specific
   exceptions first with helpful messages; end with a broad
   `except Exception` + `logger.exception` + a graceful string.
3. **Validate inputs.** Paths go through `resolve_safe_path`
   (tools/common.py) or the Obsidian vault resolver — never raw. Anything
   destructive (delete/overwrite/send/spend) must refuse without explicit
   confirmation.
4. **Register in BOTH places** or NOVA never sees it:
   - `tools/__init__.py` (import + `__all__`)
   - `agent.py` (`tools=[...]` list in `Assistant`)
5. **Add a driver check** in both driver copies
   (`.claude/skills/run-ai-agent/driver.py` AND
   `.agents/skills/run-ai-agent/driver.py` — keep them identical).
   Isolate side effects: notes go to the temp `NOTES_PATH`, Obsidian checks
   use the temp vault already set up in `check_tools`. Never let a check
   touch Ahmed's real files.
6. **If NOVA should know when to use the tool**, add 1–3 lines to the
   relevant section of `prompts.py` (SYSTEM_PROMPT).
7. **Verify before claiming done** (never skip):

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "<message that uses the new tool>"
```

8. **Update the docs** per AGENTS.md "After EVERY completed task":
   ROADMAP.md, HACKATHON_LOG.md (during Build Week), and the tool count in
   AGENTS.md + CLAUDE.md.

## Hard don'ts

- No new pip packages unless genuinely required — and say so out loud.
- Never log, print, return, or send secrets (`.env*` is always blocked).
- Never edit driver checks to make them pass.
- Never block the realtime loop: network calls get timeouts and, if slow,
  `asyncio.to_thread` / `asyncio.wait_for` (see tools/information.py).
