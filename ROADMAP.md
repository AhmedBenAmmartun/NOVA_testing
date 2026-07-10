# NOVA Roadmap

_Last updated: 2026-07-09_

## Mission

NOVA is Ahmed's personal AI operating assistant: voice-first, vision-capable,
tool-using — for coding, school, research, desktop control, media, email,
calendar, files, and daily productivity. This LiveKit + Gemini Realtime repo
is the main NOVA going forward (fast, smooth speech-to-speech voice).

## Current status (verified 2026-07-09)

Done and working:

- [x] LiveKit agent runs (console mode and LiveKit Cloud dev mode)
- [x] Gemini Realtime voice conversation (voice "Achird")
- [x] Camera/video input enabled
- [x] ai_coustics noise cancellation
- [x] NOVA persona (`SYSTEM_PROMPT` in prompts.py)
- [x] 12 basic tools: weather, web search, open website, open app, YouTube
      search, system info, time, save/read notes, list/read/create files
- [x] `.env` credential loading fixed (was silently loading nothing)
- [x] `requirements.txt` completed (ai-coustics added)
- [x] Test harness + run skill (`.claude/skills/run-ai-agent/` — `tools`,
      `chat`, `console-check`, `dev-check` all pass)
- [x] **Phase 1 complete (2026-07-09)** — see below
- [x] Music controls with zero setup: `control_music` (play/pause, next,
      previous via media keys), `change_volume`, `get_current_song` (Spotify
      window title), `is_app_running` — all live-tested
- [x] `play_spotify_song` tool (spotipy) — code ready, waits for Spotify API
      credentials (see Phase 4)

## Phase 1 — Stabilize & secure ✅ DONE 2026-07-09

- [x] `git init` + `.gitignore` + first commit
- [x] `open_app` whitelisted — raw model input never reaches a shell
- [x] File tools sandboxed to approved folders; `.env*` always blocked
- [x] `notes.txt` absolute path next to agent.py
- [x] `Google_API_Key` → `GOOGLE_API_KEY` in `.env`
- [x] Deps trimmed (mem0ai, langchain-community out; DuckDuckGo called
      directly; spotipy added)
- [x] Tool call + error logging to `nova_tools.log`
- [x] Driver extended with security-regression checks (12 checks)

## Phase 2 — Tool structure

Split `tools.py` into modules as it grows past ~15 tools:

```
tools/
  __init__.py  weather.py  search.py  desktop.py  browser.py
  files.py  system.py  notes.py  spotify.py  calendar.py
  email.py  school.py
```

Keep one tool = one small function with error handling. Update the driver's
`tools` check when modules move.

## Phase 3 — Desktop control

- [ ] Close app / restart app (confirmation required)
- [ ] Check if an app is running, wait for app to open
- [ ] Focus / minimize / maximize windows
- [ ] All destructive actions ask Ahmed first

## Phase 4 — Spotify / media

Already done (no setup needed): pause/resume/next/previous (`control_music`),
volume (`change_volume`), current track (`get_current_song`), open/check
Spotify (`open_app`/`is_app_running`), and `play_spotify_song` is coded.

Remaining — needs Ahmed to create a (free) Spotify Developer app at
developer.spotify.com and put `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`
in `.env` (redirect `http://127.0.0.1:8888/callback`; playback needs Premium):

- [ ] First-run OAuth login (browser opens once, token cached)
- [ ] Verify `play_spotify_song` end-to-end
- [ ] Play playlist / album; queue song

## Phase 5 — Custom NOVA website

Replace the LiveKit playground: Next.js + React + LiveKit React SDK + a
token backend route. Features: connect button, mic toggle, camera toggle,
transcript panel, tool-activity panel, status indicator, settings; voice
selector and standby toggle later.

## Phase 6 — Standby / always-on

1. Website standby first: stay connected while the site is open; mute/unmute,
   camera on/off, manual standby button.
2. Desktop standby later: background process + tray icon, wake word
   "NOVA"/"Hey NOVA" (reuse the old Nova repo's vosk wake-word listener),
   connects to LiveKit only when activated, sleeps after silence, can be
   fully disabled. Retire the old repo's listener when this lands (one mic
   owner only).

## Phase 7 — Canvas / school

Port from `nova/integrations.py` in the old repo (working code exists):

- [ ] Assignments due today / this week / next assignment
- [ ] Class schedule, study planner, assignment + exam reminders

## Phase 8 — Email & calendar

Port Outlook (Graph device flow) from the old repo, or add Gmail:

- [ ] Summarize unread, search, draft, reply-draft
- [ ] Calendar summary, create event
- Safety: NOVA never sends an email without explicit confirmation.

## Phase 9 — Screen understanding

- [ ] Screenshot + analyze screen (Gemini vision)
- [ ] Read visible errors, explain code on screen, OCR, read PDFs/images

## Phase 10 — Memory

Long-term memory (mem0ai or similar): preferences, project details, coding
style, workflows, school schedule, favorite apps, NOVA settings.
Never store passwords, API keys, tokens, or sensitive data unless asked.

## Phase 11 — Mission mode

"NOVA, help me finish my assignment" / "start coding mode" / "morning
briefing" → create a plan, use tools, track progress, ask before risky
actions, summarize what was done.

## Update rule

When Ahmed says a feature is done:

1. Move it to Current status with the date.
2. Note any bugs found.
3. Add the next recommended step.
4. Update the "Last updated" date here and in `CLAUDE.md` if the stack or
   rules changed.
