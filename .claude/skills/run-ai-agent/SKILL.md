---
name: run-ai-agent
description: Run, start, launch, test, or drive the NOVA LiveKit voice agent (agent.py) — smoke-test its tools, chat with the real Assistant+Gemini in text, and launch-check console/dev modes.
---

# Run the NOVA LiveKit voice agent

LiveKit Agents app (`agent.py`): the NOVA persona on Google's Gemini Live
realtime model (voice "Achird") with 12 local function tools (`tools.py`).
It is driven programmatically via
`.claude/skills/run-ai-agent/driver.py`, which runs the agent's brain
(same Assistant, same tools) on the **text** Gemini model without needing a
mic, speakers, or a LiveKit room. All paths below are relative to the
project root (`AI Agent/`).

## Prerequisites

- `venv\` in the project root is already provisioned (Python 3.14,
  livekit-agents 1.6.4, all plugins). Nothing global is needed.
- `.env` in the project root must define `LIVEKIT_URL`, `LIVEKIT_API_KEY`,
  `LIVEKIT_API_SECRET` (for dev mode) and `GOOGLE_API_KEY` (for everything).
  Never print its contents.

There is no build step and no test suite; the driver's checks are the test
suite.

## Run (agent path) — the driver

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"
$env:PYTHONIOENCODING = 'utf-8'

# 1. Local tools directly, no API keys or network (get_time, system info, notes, files)
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" tools

# 2. One full agent turn: real Assistant + its tools on text Gemini.
#    Prints [tool call] / [tool output] lines and the final "NOVA:" reply.
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" chat "What time is it right now?"

# 3. Launch the REAL app in console mode, wait for the Gemini Live greeting, kill it.
#    NOVA speaks ALOUD through the laptop speakers for a few seconds - expected.
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" console-check

# 4. Launch dev mode, wait for "registered worker" (validates LiveKit Cloud creds), kill it.
& ".\venv\Scripts\python.exe" ".claude\skills\run-ai-agent\driver.py" dev-check
```

All four exit 0 on success. Use `chat` to verify any change to
`prompts.py` or `tools.py` end-to-end (e.g. `chat "What is the weather in
Tunis?"` exercises a networked tool through the LLM).

## Run (human path)

```powershell
& ".\venv\Scripts\python.exe" agent.py console
```

Interactive voice chat in the terminal using the laptop mic/speakers —
NOVA greets Ahmed aloud immediately. Ctrl+C to stop. `agent.py dev`
instead registers a worker named `my-agent` with LiveKit Cloud and waits
for explicit dispatch (e.g. from the LiveKit Agents playground); it makes
no sound locally.

## Gotchas

- **`.env` loading**: `agent.py` originally loaded only `.env.local`, which
  doesn't exist — so no credentials ever loaded and console mode died at
  startup. Fixed 2026-07-09: it now falls back to `.env` (`.env.local`
  still wins if present). Don't revert.
- **Gemini model minefield (free-tier key, as of 2026-07)**:
  `gemini-2.5-flash` → 404 "no longer available to new users" (even though
  `models.list` still returns it); `gemini-2.0-flash` → 429 with
  `limit: 0` (free tier has zero quota for old models);
  `gemini-flash-latest` → 400 "missing thought_signature", because
  livekit-plugins-google gates its thought-signature handling on the model
  *name* containing `gemini-2.5`/`gemini-3` (see
  `_requires_thought_signatures` in the plugin's `llm.py`) and the alias
  matches neither. **Use an explicit `gemini-3*` name** — the driver uses
  `gemini-3.5-flash`.
- The Google key env var was renamed `Google_API_Key` → `GOOGLE_API_KEY` on
  2026-07-09 (the old casing only worked because Windows env vars are
  case-insensitive).
- **Console mode under redirected stdout** never prints its interactive
  banner ("Press [Ctrl+B]...") — poll the log for `conversation_item_added`
  (the greeting) instead, which is what `console-check` does.
- **Console mode uses the real mic**: while it runs, it will happily hold a
  conversation with anyone (or any TTS, e.g. the other NOVA in the Nova
  repo) audible in the room. Kill it when done; `driver.py` kills child
  processes too (dev mode spawns a job runner child that outlives a plain
  parent kill).
- `requirements.txt` was missing `livekit-plugins-ai-coustics` (imported by
  `agent.py`); added 2026-07-09. The venv already had it.

## Troubleshooting

- **404 / 429 / 400 from Gemini** → see the model minefield above. To see
  which models the key can use right now:
  ```powershell
  & ".\venv\Scripts\python.exe" -c "from dotenv import load_dotenv; load_dotenv('.env'); from google import genai; c = genai.Client(); [print(m.name) for m in c.models.list() if 'generateContent' in (m.supported_actions or [])]"
  ```
- **`api_key` error at startup** → `.env` missing or the `load_dotenv`
  fallback in `agent.py` was removed; commands must run from the project
  root (dotenv paths are CWD-relative — the driver chdirs itself).
- **`console-check`/`dev-check` time out** → read the full launch log at
  `%TEMP%\nova_agent_console_check.log` / `%TEMP%\nova_agent_dev_check.log`.
