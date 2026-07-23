---
name: nova-code-review
description: Use when reviewing diffs, PRs, or newly written code in this NOVA LiveKit repo before accepting it.
---

# NOVA code review (this repo — LiveKit + Gemini Realtime)

Review for correctness, security, and regression risk. Style comments only
when they hide a bug.

## Checklist

1. **Secrets:** any hardcoded keys/tokens, anything that logs/prints/returns
   `.env` content, or a path check that could let a tool read `.env*` or
   `.spotify_cache`? Reject.
2. **Sandbox:** every file path from the LLM goes through
   `resolve_safe_path` or the Obsidian vault resolver. Any raw
   `Path(user_input)` use is a finding.
3. **Whitelist:** `open_app`/`close_app` stay approved-list only. Raw model
   input must never reach a shell (`shell=True`, string commands → reject).
4. **Tool contract:** every `@function_tool` returns a speakable string and
   cannot raise — broad `except Exception` + `logger.exception` + graceful
   message present?
5. **Registration completeness:** new tool imported in `tools/__init__.py`
   (+ `__all__`) AND listed in `agent.py`? Half-registered tools are a
   classic silent failure.
6. **Realtime loop safety:** any synchronous/blocking work (network without
   timeout, long CPU, `time.sleep`) inside a tool? Gemini Realtime stalls —
   flag it and suggest `asyncio.to_thread` / `wait_for`.
7. **Driver:** were driver checks added for new behavior? Were existing
   checks EDITED to pass instead of fixing code? Reject the latter
   outright. Is the canonical driver under `.agents/` current and tested?
8. **Windows:** POSIX-only APIs, hardcoded `/` paths, missing
   `encoding="utf-8"` on file I/O? Flag.
9. **Protected things** (need Ahmed's explicit OK): removing Gemini
   Realtime/LiveKit/SYSTEM_PROMPT/working tools, flipping
   `video_input`, changing his voice tuning in agent.py, new pip packages.
10. **Docs:** ROADMAP.md + HACKATHON_LOG.md updated per AGENTS.md
    "After EVERY completed task"? Tool count still correct in
    AGENTS.md/DEVELOPMENT.md?

## Output format

- Verdict: APPROVE / APPROVE WITH NITS / REQUEST CHANGES
- Numbered findings with file:line and a suggested fix
- One line: what could break the live voice demo?
