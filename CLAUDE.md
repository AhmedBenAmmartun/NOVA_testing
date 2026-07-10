# CLAUDE.md — NOVA (LiveKit)

_Last updated: 2026-07-09_

## What this is

NOVA (Neural Operations Virtual Assistant) is Ahmed's personal AI operating
assistant: voice-first, vision-capable, tool-using. This repo is the main
NOVA going forward — a LiveKit Agents app on Gemini Realtime, chosen because
its speech-to-speech voice is fast and smooth. See `ROADMAP.md` for phases;
update it whenever a feature lands.

There is an older NOVA (Flask + local voice listener) at
`C:\Users\ahmed\OneDrive\Desktop\Nova`. Don't merge them, but DO reuse its
working code when a phase overlaps (Canvas/Outlook in `nova/integrations.py`,
file sandbox `_resolve_safe_path`, vosk wake-word listener). Never run both
voice listeners at once — they will talk to each other out loud.

## Layout

```
agent.py            LiveKit AgentServer wiring: session, Gemini Realtime
                    (voice "Achird", temp 0.8), ai_coustics noise
                    cancellation, video_input=True, greeting
prompts.py          SYSTEM_PROMPT (NOVA persona)
tools.py            17 function tools (weather, search, open app/site,
                    music/Spotify, system info, time, notes, file ops) +
                    safety helpers (_resolve_safe_path sandbox, app
                    whitelist) + logging to nova_tools.log
requirements.txt    deps (venv\ is the provisioned Python 3.14 venv)
.env                secrets: LIVEKIT_URL/API_KEY/API_SECRET, GOOGLE_API_KEY;
                    SPOTIFY_CLIENT_ID/SECRET go here when created
.claude/skills/run-ai-agent/   run skill + driver.py test harness
```

## Run & test (all verified)

```powershell
# from the project root
$env:PYTHONIOENCODING = 'utf-8'
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" tools           # local tools, no keys
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" chat "..."      # full agent turn, text
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" console-check   # real app launch (SPEAKS ALOUD)
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" dev-check       # LiveKit Cloud registration
& ".\venv\Scripts\python.exe" agent.py console                                        # human path: live voice chat
```

After ANY change to `prompts.py`, `tools.py`, or `agent.py`, run `tools` +
one `chat` before calling it done. Never claim something works untested.
See `.claude/skills/run-ai-agent/SKILL.md` for gotchas and troubleshooting.

## Non-obvious facts (learned the hard way)

- **Secrets**: `agent.py` loads `.env.local` first, then falls back to
  `.env`. The real file is `.env`. Keep that fallback; never print or
  commit either file; never hardcode keys.
- **Gemini models (free-tier key)**: `gemini-2.5-flash` is retired (404),
  2.0 models have zero free quota (429), and `gemini-flash-latest` 400s on
  tool calls because livekit-plugins-google keys thought_signature handling
  on the model *name* (`gemini-2.5`/`gemini-3` only). Always use explicit
  `gemini-3*` names for text LLM work; the driver uses `gemini-3.5-flash`.
- dev mode registers worker `my-agent` and needs explicit dispatch (e.g.
  LiveKit playground). Console mode is fully local, no LiveKit server.
- Music control is two-tier: media keys + Spotify window title work with no
  setup (pause/next/volume/current song); `play_spotify_song` needs
  SPOTIFY_CLIENT_ID/SECRET in `.env` and Spotify Premium for playback.

## Rules

Do not break the working agent. Do not remove: Gemini Realtime, LiveKit,
`video_input=True`, `SYSTEM_PROMPT`, existing working tools.

Before editing: read the relevant files, say what exists, make the smallest
safe change, one feature at a time. Prefer small functions, clear names,
docstrings, error handling on every tool. No giant files, no placeholder
implementations, no new packages unless genuinely required.

Tool safety: validate tool inputs; anything destructive (delete/overwrite/
move files, send email, purchases, shutdown/restart, system settings) must
ask Ahmed for confirmation first. `create_file` never overwrites.

## Known issues

- Phase 1 (security) is DONE as of 2026-07-09: open_app whitelisted, file
  tools sandboxed (`.env*` always blocked), notes path absolute, git repo
  initialized, GOOGLE_API_KEY renamed, deps trimmed, tool logging added.
- `play_spotify_song` returns setup instructions until Ahmed creates a
  Spotify Developer app and adds SPOTIFY_CLIENT_ID/SECRET to `.env`.
- `mem0ai`/`langchain-community` are still installed in the venv but no
  longer in requirements.txt (harmless; gone on a fresh install).
