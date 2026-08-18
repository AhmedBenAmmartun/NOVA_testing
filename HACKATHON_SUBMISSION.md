# OpenAI Build Week Submission Prep

> **Project boundary — 2026-08-15**
>
> The legacy NOVA Dashboard has been detached from this repository/runtime.
> NOVA is the agent/AI operating layer. NOVA Vision remains part of NOVA.
> Dashboard/Valo is a separate project and may integrate later only through a
> defined external interface. Older dashboard references below may be historical.

Verified with the Devpost Hackathons plugin on 2026-07-14 UTC.

## Challenge

- Hackathon: OpenAI Build Week
- Devpost slug: `openai`
- URL: https://openai.devpost.com/
- Current phase at verification: submissions open
- Submission deadline: July 21, 2026 at 5:00 PM PT / 8:00 PM ET
- Winners announced: around August 12, 2026 at 2:00 PM PT / 5:00 PM ET

## What Needs To Be Ready

- [x] Working NOVA project with a meaningful Build Week extension
- [x] GPT-5.6 and development assistant are central to the new feature
- [x] Clear old-vs-new documentation in [HACKATHON_LOG.md](HACKATHON_LOG.md)
- [ ] Dated commits showing Build Week work
- [ ] Repo URL
- [ ] Public YouTube demo video under 3 minutes
- [ ] Audio in the demo explaining how development assistant and GPT-5.6 were used
- [ ] `/feedback` development assistant session ID from the main build thread
- [x] README setup and run instructions
- [x] Third-party services and license notes
- [ ] Final category selected
- [ ] Submission is actually submitted, not left as a draft

## Devpost Form Fields

Use this section while filling out the submission form.

| Field | Required | Draft answer |
| --- | --- | --- |
| Submitter Type | Yes | Individual |
| Country of Residence | Yes | United States - confirm before submit |
| Category | Yes | Apps for Your Life |
| Code repo URL | Yes | TODO |
| Project/testing link and instructions | No | See "Judge Testing Instructions" below |
| `/feedback` development assistant Session ID | Yes | TODO |
| Plugin/dev-tool install instructions | No | Not a plugin. Use README run instructions. |

## Project Metadata Draft

Do not submit this blindly. Edit it after the final Build Week feature lands.

### Project Name

NOVA Companion

### Tagline

A voice-first desktop AI companion for personal productivity, screen help, and
safe local actions.

### Category

Apps for Your Life

Use Developer Tools only if the final demo focuses mainly on helping developers
debug, test, or automate code workflows.

### Built With

Draft list:

- development assistant
- GPT-5.6
- Python
- LiveKit Agents
- Gemini Realtime
- Google Gemini API
- Ollama
- Groq
- Spotify API
- DuckDuckGo Search
- pypdf
- psutil
- python-dotenv

Before submitting, remove anything not actually used in the final demo or code.

## Project Description Draft

NOVA Companion is a personal desktop AI assistant that combines fast realtime
voice interaction with practical local tools. It can answer questions, control
approved desktop apps, search the web, manage local notes and files within a
sandbox, control music, inspect system status, route questions to specialist
models, and capture the screen for future visual assistance.

For OpenAI Build Week, the pre-existing NOVA agent was meaningfully extended
with explicit GPT-5.6 reasoning, confirmed screen-analysis tools, Obsidian
memory reading/writing, a sandboxed course-material reader for PDFs/Markdown/text,
prompt-driven Study Mode / Quiz Mode choreography, and a first Conversation
Mode runtime pass for barge-in/queued-reply reliability. It also saves local
timestamped conversation transcripts so later sessions can search/read what
Ahmed talked about before, mirrors live transcripts into the Obsidian vault,
can search/read existing ChatGPT/development assistant Markdown exports from the vault with
capped excerpts for long notes, and now includes local file pull-up plus richer Windows window/desktop
controls. It also includes the NOVA Dashboard (rebuilt 2026-07-20 from the
final design handoff): a full-screen desktop control center with five
swipeable pages — widget dashboard, NOVA + Second Brain, Apps & Files,
Calendar, and the Agent activity/approvals page — plus a dock, Ctrl+K command
palette, notifications, and a lock screen. It is wired to real data through a
local WebSocket bridge (`Dashboard/server.py`, aiohttp on 127.0.0.1): live
CPU/RAM from psutil, real Spotify now-playing with working media controls,
live weather, the real Obsidian vault (note count, recent notes, a memory
browser, and tasks that write back to `<vault>/NOVA/Tasks.md`), the agent's
actual phase and tool-call feed tailed from `nova_tools.log`, the approval
queue from the permission engine's audit trail, conversation bubbles from
saved transcripts, per-model usage counts, and the real Windows app catalog
with real app launches. Without the server it degrades to a simulated demo
mode, so the design always presents. The final integration adds an entirely
local command bridge: Ctrl+K inserts a bounded user text turn into the active
LiveKit session, and dashboard Approve/Deny decisions run through the same
in-memory permission engine that owns the pending action. Command envelopes
are validated, atomically claimed, short-lived, and contain no credentials or
arbitrary executable code.
Gemini Realtime remains
the fast voice layer, while GPT-5.6 is
available for substantial reasoning, planning, screen help, and
material-based quiz generation when Ahmed asks for it. The screen analyzer
requires explicit confirmation before a screenshot is sent to OpenAI.

The newest study-prep path lets Ahmed drop professor PDFs into
`course_materials/` and ask NOVA to extract page-limited text safely. Study
Mode teaches from that extracted material, and Quiz Mode is instructed to call
GPT-5.6 for material-based questions, ask one question at a time, explain
mistakes, repeat weak topics, and save quiz results. Final Study/Quiz
verification is still pending until Gemini and GPT-5.6 quota are available
for that exact flow, but a neutral full chat smoke test succeeded on
2026-07-17.

TODO after implementation:

- Name the exact new feature. DONE: GPT-5.6 reasoning, confirmed screen help,
  Obsidian memory readback, sandboxed course-material PDF/text extraction, and
  prompt-driven Study Mode / Quiz Mode.
- Explain what GPT-5.6 does inside the feature. DONE: it handles explicit
  reasoning requests, analyzes confirmed screenshots through the Responses API,
  and generates quiz questions from extracted course material when quota is
  available.
- Explain what development assistant built or accelerated. DONE: development assistant added tool wiring,
  safety gates, docs, smoke-test updates, the course-material extraction path,
  the Study/Quiz prompt choreography, and the first Conversation Mode runtime
  turn-handling pass, local saved-conversation memory, Obsidian memory writes
  and transcript mirroring, the expanded file/window/virtual-desktop control
  tools, the refined Dashboard shell, documentation, and verification setup.
- Add the commit range for Build Week work.
- Add a short testing path for judges.

## development assistant And GPT-5.6 Evidence

Fill this before submission:

- Main development assistant task/session ID: TODO
- `/feedback` session ID: TODO
- Baseline commit before Build Week feature: TODO
- Build Week commit range: TODO
- Files added or changed for the new feature: `tools/models.py`,
  `tools/vision.py`, `tools/obsidian.py`, `tools/common.py`,
  `tools/files.py`, `tools/desktop.py`, `tools/conversations.py`,
  `tools/__init__.py`, `agent.py`, `prompts.py`, `.env.example`,
  `requirements.txt`, `Dashboard/`, `Dashboard/src-tauri/`, driver scripts,
  README/submission docs, and roadmap.
- What development assistant accelerated: API integration, tool safety design, agent routing,
  course-material PDF extraction, Study/Quiz prompt choreography,
  Conversation Mode turn-handling, saved-conversation memory, Obsidian memory
  writes, transcript mirroring, file pull-up, Desktop creation,
  window/virtual-desktop controls, the native desktop companion widget, the
  refined desktop dashboard shell, documentation, and verification setup.
- Where Ahmed made key product/engineering decisions: Ahmed chose NOVA as the
  Build Week project, kept the repo private while building, and chose to add
  the OpenAI key but avoid automatic GPT-5.6 calls.
- Where GPT-5.6 is used by the final project or build workflow: `ask_gpt56`
  for explicit reasoning/planning, material-based quiz generation, and
  `analyze_screen_with_gpt56` for confirmed screen analysis.
- Current verification gap: Study/Quiz Mode is implemented in `SYSTEM_PROMPT`,
  but final material-based quiz verification still needs Gemini and GPT-5.6
  quota for that exact flow. The local file/window/memory-write tools passed
  direct driver checks, and a neutral full-chat check succeeded on
  2026-07-17. Live manual screen movement and live voice transcript mirroring
  still need a console session. The Dashboard streams real stats/Spotify/
  weather/vault/agent-log data over its local WebSocket bridge. Approve/Deny
  and Ctrl+K delegation are now connected to the active agent process through
  the private local command bridge. The remaining dashboard data gap is the
  calendar page, which is clearly left as Demo Data until Ahmed authorizes a
  Google/ICS adapter.

## Judge Testing Instructions

Draft for the private Devpost testing field:

```text
NOVA is a Windows desktop voice agent. To test locally:

1. Clone the repo.
2. Create a Python virtual environment and install requirements.txt.
3. Copy .env.example to .env and add the required credentials for the mode you
   want to test.
4. Run the local tool smoke test:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py tools
5. Run a text agent turn:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "What can you do?"
6. Optional GPT-5.6 text test after adding OPENAI_API_KEY:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Use GPT-5.6 to make a 3 step plan for testing NOVA."
7. Optional confirmed screen analysis:
   Ask NOVA: "Use GPT-5.6 to analyze my screen. I confirm it is okay to share what is visible."
8. Optional course-material / quiz-mode test:
   Put a PDF in course_materials/ and ask:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Read course_materials/<file>.pdf and summarize it."
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Quiz mode: quiz me on course_materials/<file>.pdf."
9. Optional file/window control test on Windows:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Create a Desktop file called judge test with one sentence."
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Find the file called judge test."
10. Optional memory write test:
   .\venv\Scripts\python.exe .agents\skills\run-ai-agent\driver.py chat "Remember this: NOVA should keep project memories in small safe notes."
   Then search the configured Obsidian vault for "small safe notes".
11. Optional voice mode:
   .\venv\Scripts\python.exe agent.py console
12. Desktop dashboard (real data):
   powershell -ExecutionPolicy Bypass -File Dashboard\start_dashboard.ps1
   (or: .\venv\Scripts\python.exe Dashboard\server.py and open
   http://127.0.0.1:8787). Look for the teal LIVE pill next to the clock:
   CPU/RAM, weather, Spotify, Obsidian notes/memories/tasks, apps, folders,
   and recent files are real. Swipe or arrow-key through the five pages,
   launch a real app from the dock, toggle a task (it writes to the vault's
   NOVA/Tasks.md), and press Ctrl+K for the command palette. Run the voice
   console at the same time to watch the orb phase and activity feed follow
   the real agent. Open http://127.0.0.1:8787/health and confirm
   agentBridge=active, then try a Ctrl+K request and a pending approval.
   Opening Dashboard\web\index.html directly (no server)
   shows the same design in simulated demo mode.

The voice console uses the real microphone and speakers. The local tool smoke
test is the safest first test because it does not require voice input.
```

TODO: Add any temporary judge credentials or demo account details only in the
private Devpost field, never in GitHub.

## Demo Video Plan

Target length: 2:30 to 2:50.

1. 0:00-0:15 - Show NOVA running and state the problem.
2. 0:15-0:45 - Explain what existed before Build Week.
3. 0:45-1:35 - Demo memory/course-material reading and GPT-5.6 reasoning.
4. 1:35-2:10 - Show the NOVA Dashboard live: the LIVE pill, real CPU/RAM and
   weather widgets, Spotify controls actually pausing music, the Second Brain
   page with the real vault note count and model usage, launching a real app
   from the dock, toggling a task that writes into the Obsidian vault, and the
   agent activity feed moving while a voice session runs.
5. 2:10-2:45 - Explain how development assistant and GPT-5.6 were used and show evidence.
6. 2:45-3:00 - Close with the use case and impact.

Required audio points:

- What was built
- How development assistant was used
- How GPT-5.6 was used
- Why the new feature matters

Avoid:

- Copyrighted music
- Third-party character art or logos without permission
- Private messages, private API keys, or private files on screen
- Long setup footage or terminal waiting time

## Post-Demo Roadmap Notes

Added from Ahmed's 2026-07-16 design notes:

- First priority after the study demo: fix conversation delay, queued replies,
  interruption handling, and response cancellation.
- First runtime pass added on 2026-07-16: LiveKit/Gemini realtime turn
  handling is explicit, start-of-activity interruption is enabled, AEC warmup
  is shortened, and conversation state/interruption events are logged locally.
- Then build a model router/specialist registry, offline fallback, task
  manager, permission levels, and standby notifications.
- Speaker recognition and many autonomous specialists should wait until
  conversation control, task state, and permissions are reliable.

## Final Submission Checklist

- [ ] `README.md` is accurate and has setup instructions
- [ ] `HACKATHON_LOG.md` has the final feature entry
- [ ] `THIRD_PARTY_SERVICES.md` is updated
- [ ] `.env` and private runtime files are not committed
- [ ] Repo is public with a selected license, or private and shared with
      `testing@devpost.com` and `build-week-event@openai.com`
- [ ] Demo video is public on YouTube and under 3 minutes
- [ ] Demo audio covers development assistant and GPT-5.6
- [ ] Devpost required fields are filled
- [ ] `/feedback` session ID is entered
- [ ] Submission status says submitted, not draft
