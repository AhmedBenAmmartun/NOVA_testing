# OpenAI Build Week Submission Prep

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
- [x] GPT-5.6 and Codex are central to the new feature
- [x] Clear old-vs-new documentation in [HACKATHON_LOG.md](HACKATHON_LOG.md)
- [ ] Dated commits showing Build Week work
- [ ] Repo URL
- [ ] Public YouTube demo video under 3 minutes
- [ ] Audio in the demo explaining how Codex and GPT-5.6 were used
- [ ] `/feedback` Codex session ID from the main build thread
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
| `/feedback` Codex Session ID | Yes | TODO |
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

- Codex
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
- React
- Vite
- Tailwind CSS
- Tkinter

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
and now includes local file pull-up plus richer Windows window/desktop
controls. It also now includes a native Windows desktop skin that launches
with `pythonw.exe`, attaches independent Rainmeter-style modules to the
desktop wallpaper host when Windows allows it, supports
minimal/focus/study/system profiles, persists monitor-relative layout, and
offers a safe local command bar. A React/Vite command-center prototype remains
available for the future larger dashboard. Gemini Realtime remains the fast
voice layer, while GPT-5.6 is
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
- Explain what Codex built or accelerated. DONE: Codex added tool wiring,
  safety gates, docs, smoke-test updates, the course-material extraction path,
  the Study/Quiz prompt choreography, and the first Conversation Mode runtime
  turn-handling pass, local saved-conversation memory, Obsidian memory writes
  and transcript mirroring, the expanded file/window/virtual-desktop control
  tools, the native desktop skin, and the modular dashboard frontend.
- Add the commit range for Build Week work.
- Add a short testing path for judges.

## Codex And GPT-5.6 Evidence

Fill this before submission:

- Main Codex task/session ID: TODO
- `/feedback` session ID: TODO
- Baseline commit before Build Week feature: TODO
- Build Week commit range: TODO
- Files added or changed for the new feature: `tools/models.py`,
  `tools/vision.py`, `tools/obsidian.py`, `tools/common.py`,
  `tools/files.py`, `tools/desktop.py`, `tools/conversations.py`,
  `tools/__init__.py`, `agent.py`, `prompts.py`, `.env.example`,
  `requirements.txt`, driver scripts, `Dashboard/`, README/submission docs,
  and roadmap.
- What Codex accelerated: API integration, tool safety design, agent routing,
  course-material PDF extraction, Study/Quiz prompt choreography,
  Conversation Mode turn-handling, saved-conversation memory, Obsidian memory
  writes, transcript mirroring, file pull-up, Desktop creation,
  window/virtual-desktop controls, the native desktop companion widget, the
  modular dashboard prototype, documentation, and verification setup.
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
  still need a console session. The native desktop skin compiles, passes its
  7-test unit suite, self-tests against the desktop WorkerW layer, and
  launches with `pythonw.exe`; the React dashboard passes typecheck/build.
  Both still need the live NOVA HTTP/WebSocket bridge.

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
11. Optional desktop skin test:
   powershell -ExecutionPolicy Bypass -File .\Dashboard\start_desktop_widget.ps1 -Mode mini
   The skin should appear as frameless desktop modules. Use Ctrl+Alt+N or
   double-click the NOVA orb for the safe command bar.
12. Optional dashboard prototype test:
   cd Dashboard
   pnpm install
   pnpm run typecheck
   pnpm run build
   pnpm run dev
   Open the printed Vite URL. The dashboard currently uses mock NOVA events.
13. Optional voice mode:
   .\venv\Scripts\python.exe agent.py console

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
4. 1:35-2:10 - Show the Desktop Companion widget sitting on the desktop, or
   confirmed screen help if time allows.
5. 2:10-2:45 - Explain how Codex and GPT-5.6 were used and show evidence.
6. 2:45-3:00 - Close with the use case and impact.

Required audio points:

- What was built
- How Codex was used
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
- [ ] Demo audio covers Codex and GPT-5.6
- [ ] Devpost required fields are filled
- [ ] `/feedback` session ID is entered
- [ ] Submission status says submitted, not draft
