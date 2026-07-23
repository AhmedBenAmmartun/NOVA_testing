# NOVA

NOVA is Ahmed's personal AI operating assistant: a voice-first, tool-using
desktop agent built on LiveKit Agents with Gemini Realtime audio. It can use
local tools for desktop control, files, notes, media, search, weather, system
info, screen capture, and specialist model routing.

This repository is being prepared for OpenAI Build Week. Pre-existing work and
new hackathon work are tracked in [HACKATHON_LOG.md](HACKATHON_LOG.md).

## Build Week Status

- Challenge: OpenAI Build Week
- Working title: NOVA Companion
- Suggested category: Apps for Your Life
- Submission deadline: July 21, 2026 at 5:00 PM PT / 8:00 PM ET
- Required evidence: a working project, repository URL, README setup
  instructions, public YouTube demo under 3 minutes, and the `/feedback` development assistant
  session ID for the main build thread

The Build Week feature adds explicit GPT-5.6 reasoning, screen-help tools,
Obsidian memory reading and writing, sandboxed course-material PDF/text
extraction, prompt-driven Study Mode / Quiz Mode, saved conversation logs, and
expanded file/window control on top of the existing Gemini/LiveKit voice
agent. It also includes a first Conversation Mode runtime pass for barge-in
and queued-reply reliability. The desktop dashboard now lives in
`Dashboard/`: the final design-handoff shell — a five-page desktop control
center (widgets, NOVA + Second Brain, Apps & Files, Calendar, Agent) served
by a local Python bridge that streams real CPU/RAM, Spotify, weather,
Obsidian vault notes/memories/tasks, agent phase and tool activity, the
approval queue, and the real Windows app catalog. GPT-5.6 is opt-in: NOVA only
calls it when Ahmed
asks for GPT-5.6/OpenAI reasoning, confirms that a screenshot may be shared
for screen analysis, or starts Quiz Mode over extracted course material.

The dashboard includes per-page Edit Mode layouts, pin/hide/restore, undo,
responsive normalized geometry, fully clipped page canvases, managed mock
windows, a versioned local integration contract, and an explicit Demo Data
badge whenever the Python bridge is offline. Its required web runtimes and font
are self-hosted for offline desktop startup. A private local command bridge now
connects Ctrl+K delegation and Approve/Deny to the active LiveKit agent process;
commands are validated, atomically claimed, expire after two minutes, and never
carry credentials or arbitrary executable code.

## Current Capabilities

- LiveKit voice agent in [agent.py](agent.py)
- NOVA system prompt in [prompts.py](prompts.py)
- Desktop app controls with approved app names
- Window controls: focus, minimize, maximize, restore, and snap left/right/up/down
- Windows notifications, quick settings, and virtual desktop shortcuts
- File and note tools with sandboxing and `.env*` protection
- File finder/open workflow for approved folders
- Desktop creation tools that create new files/folders on Ahmed's OneDrive
  Desktop without overwriting
- Course-material reader for PDFs, Markdown, and text files in
  `course_materials/`
- Study Mode and Quiz Mode prompt flow over course materials, with GPT-5.6
  quiz generation when quota is available
- Conversation Mode first pass: explicit Gemini realtime turn handling,
  start-of-activity interruption, shorter AEC warmup, and local state logs
- Obsidian memory write path: `save_memory_note` creates new Markdown notes
  under the vault's `NOVA/` folder without overwriting and refuses obvious
  secrets
- Obsidian vault search/read covers existing Markdown notes across the vault,
  including long ChatGPT/development assistant exports; long reads return capped excerpts
  when a query is provided
- Session conversation memory: timestamped Markdown transcripts in
  `conversation_logs/`, with search/read tools for later sessions; live voice
  sessions are also mirrored to `NOVA/Conversations/` in the Obsidian vault
  when `OBSIDIAN_VAULT_PATH` is configured
- Weather, web search, system info, and time tools
- YouTube, Spotify, media key, and volume tools
- Groq and Ollama specialist model tools
- GPT-5.6 specialist reasoning tool
- Screen capture tool that saves screenshots locally
- Confirmed screen analysis through GPT-5.6
- Local test driver for tools, chat, console launch, and LiveKit dev launch
- NOVA Dashboard in `Dashboard/` (implemented 2026-07-20 from the final
  design handoff): five swipeable pages — widget dashboard (clock, weather,
  NOVA status, tasks, now playing, system, Obsidian notes, daily briefing),
  NOVA + Second Brain (orbiting vault graph, model route chips, live
  conversation, execution timeline), Apps & Files (real Start Menu catalog,
  quick folders, recent files), Calendar, and Agent (activity feed, approval
  queue, memory browser) — plus dock, Ctrl+K command palette, notifications,
  quick settings, focus modes, and a lock screen. A local aiohttp bridge
  (`Dashboard/server.py`) streams the real data over one WebSocket; with the
  server offline the shell runs the design's simulated demo mode. Widget
  layout and settings persist in the browser.

## Repository Layout

```text
agent.py          LiveKit AgentServer wiring and realtime voice session
prompts.py        NOVA persona and system behavior
tools/            Function tools for desktop, files, information, media,
                  models, Obsidian, memory/search, and vision
core/             Task routing/orchestration work in progress
offline_agent.py  Local Ollama-only text mode
requirements.txt  Python dependencies
Dashboard/        NOVA desktop shell: design handoff web app (web/) plus the
                  aiohttp data bridge (server.py, feeds.py, actions.py)
ROADMAP.md        NOVA feature roadmap
HACKATHON_LOG.md  Old-vs-new Build Week evidence log
HACKATHON_SUBMISSION.md  Devpost submission and contribution cheat sheet
```

## Requirements

- Windows desktop environment
- Python environment in `venv\` or a compatible fresh virtual environment
- LiveKit credentials for LiveKit dev mode
- Google Gemini API key for the current realtime voice path
- OpenAI API key for GPT-5.6 reasoning and confirmed screen analysis
- Optional: Spotify API credentials for Spotify playback
- Optional: Groq API key for `ask_groq`
- Optional: Ollama running locally for `ask_ollama` and `offline_agent.py`

Secrets must be stored in `.env` or `.env.local`. Do not commit either file.
Use [.env.example](.env.example) as the non-secret template.

## Setup

From PowerShell in the project root:

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"

# If the checked-in machine already has the provisioned venv, use it.
$env:PYTHONIOENCODING = 'utf-8'

# For a fresh environment, create a venv and install dependencies.
py -m venv venv
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
```

Create `.env` from `.env.example`, then fill only the credentials needed for
the mode you want to run.

GPT-5.6 is configured with:

```env
OPENAI_API_KEY=replace_me
OPENAI_MODEL=gpt-5.6
OPENAI_MAX_OUTPUT_TOKENS=800
OPENAI_TIMEOUT_SECONDS=60
```

The key is only used when NOVA calls `ask_gpt56` or
`analyze_screen_with_gpt56`.

## Run

Local tool smoke test:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
```

One text chat turn through the NOVA assistant and tools:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "What time is it right now?"
```

Study/quiz mode examples:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Study mode: teach me course_materials/biology.pdf."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Quiz mode: quiz me on course_materials/biology.pdf."
```

Quiz Mode depends on Gemini chat plus GPT-5.6 quota. If either service is
rate-limited, NOVA should say so and offer a simpler review from the extracted
material.

Conversation history examples:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "What did we talk about last session?"
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Search my conversation history for quiz mode."
```

Live voice sessions save local Markdown logs under `conversation_logs/`.
That folder is gitignored. When `OBSIDIAN_VAULT_PATH` is configured, live
voice sessions are also copied into the vault under
`NOVA/Conversations/YYYY/MM/`.

Memory write examples:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Remember this: for NOVA, prefer small safe tools with driver checks."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Search my memory for driver checks."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Search my memory for NOVA project improvements."
```

File and desktop-control examples:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Find my file called schedule and open it."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Create a Desktop file called project ideas with three bullets."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Snap Chrome to the left and VS Code to the right."
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "Open a new desktop."
```

Interactive voice console. This uses the real microphone and speakers:

```powershell
& ".\venv\Scripts\python.exe" agent.py console
```

LiveKit Cloud worker registration:

```powershell
& ".\venv\Scripts\python.exe" agent.py dev
```

Local Ollama-only text mode:

```powershell
& ".\venv\Scripts\python.exe" offline_agent.py
```

NOVA Dashboard (design shell + real data bridge):

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"
powershell -ExecutionPolicy Bypass -File ".\Dashboard\start_dashboard.ps1"
```

That starts `Dashboard\server.py` (aiohttp on `127.0.0.1:8787`, real data
over one WebSocket) and opens the shell in a chromeless Edge app window. A
teal LIVE pill next to the clock confirms the bridge is connected; without
the server, opening `Dashboard\web\index.html` directly shows the same design
in simulated demo mode. See `Dashboard/README.md` for what is real and the
current gaps. Run `agent.py console` or `agent.py dev` at the same time to make
Ctrl+K delegation and the approval buttons reach the live agent. The `/health`
endpoint reports `agentBridge: active` while an agent session is available.

## Verification

After changes to `agent.py`, `prompts.py`, or `tools/`, run:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "What can you help me with?"
```

For launch checks:

```powershell
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" console-check
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" dev-check
```

`console-check` may briefly play audio through the speakers. Do not run this
near another voice assistant listener.

Dashboard checks:

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"
npm --prefix Dashboard run lint
npm --prefix Dashboard run build
npm --prefix Dashboard test
& ".\venv\Scripts\python.exe" -m py_compile ".\agent.py" ".\nova_bridge.py" ".\nova_agent_bridge.py" ".\Dashboard\server.py" ".\Dashboard\feeds.py" ".\Dashboard\actions.py"
& ".\venv\Scripts\python.exe" ".\Dashboard\server.py"   # then open http://127.0.0.1:8787 and look for the LIVE pill
```

## Safety Notes

- `.env`, `.env.local`, `.spotify_cache`, logs, screenshots, and notes are
  private runtime files and should not be committed.
- File tools are sandboxed and block `.env*`.
- Desktop app control is restricted to approved app names.
- GPT-5.6 screen analysis requires explicit screen-share confirmation.
- Destructive actions should require explicit user confirmation.
- Do not submit copyrighted characters, music, logos, private files, or other
  third-party assets unless permission is documented.

## Hackathon Documentation

- [HACKATHON_LOG.md](HACKATHON_LOG.md) records what existed before Build Week
  and what development assistant adds during the submission period.
- [HACKATHON_SUBMISSION.md](HACKATHON_SUBMISSION.md) tracks the Devpost form,
  demo video plan, repo readiness, and final submission checklist.
- [THIRD_PARTY_SERVICES.md](THIRD_PARTY_SERVICES.md) tracks the services,
  APIs, model providers, and license/terms checks used by NOVA.
