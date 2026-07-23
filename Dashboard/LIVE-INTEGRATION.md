# NOVA Dashboard Live Integration

This Dashboard folder is a drop-in update for the existing NOVA project. It
keeps the supplied desktop design while connecting it to NOVA's local Python
bridge on `127.0.0.1:8787`.

## Connection states

- **LIVE** means the WebSocket is connected and supported surfaces are using
  real local NOVA data.
- **Demo Data** means the bridge is unavailable and the built-in simulated
  fallback is active.

The browser/backend contract is version `1.0.0`. The browser API is available
as `window.NOVAIntegration`; the backend exposes `GET /health` and `/ws`.

## Live sources

- CPU and RAM
- Spotify playback state and media controls
- weather
- Obsidian notes, memories, and tasks
- NOVA phase, activity, model usage, approvals, and conversation logs
- Windows apps, quick folders, and recent files

Calendar remains Demo Data until a calendar adapter is selected. Dashboard
approval buttons and command-palette delegations use a private local bridge to
the active LiveKit agent process. The bridge accepts only validated approval
decisions and bounded text turns, claims commands atomically, expires them after
two minutes, and never carries credentials or arbitrary executable code.

## Run from the NOVA project root

```powershell
powershell -ExecutionPolicy Bypass -File ".\Dashboard\start_dashboard.ps1"
```

For backend debugging:

```powershell
& ".\venv\Scripts\python.exe" ".\Dashboard\server.py"
```

Open `http://127.0.0.1:8787/health` to verify the bridge. The response should
show `status: ok`, `mode: live`, and `contractVersion: 1.0.0`.
`agentBridge: active` appears while `agent.py console` or `agent.py dev` has an
active session; otherwise it reports `waiting`.

## Verify

```powershell
npm --prefix Dashboard run lint
npm --prefix Dashboard run build
npm --prefix Dashboard test
& ".\venv\Scripts\python.exe" -m py_compile agent.py nova_bridge.py nova_agent_bridge.py Dashboard\server.py Dashboard\feeds.py Dashboard\actions.py
& ".\venv\Scripts\python.exe" -m unittest discover -s Dashboard\tests -p "test_*.py" -v
```

## Build the Windows app

Install the Rust and Tauri Windows prerequisites, then run:

```powershell
Set-Location ".\Dashboard\nova-app"
npm install
npm run build
```

The NSIS installer is created under
`Dashboard\nova-app\src-tauri\target\release\bundle\nsis\`.

Never place `.env`, `.env.local`, `.spotify_cache`, conversation logs, Obsidian
vault contents, or tokens inside a dashboard build or support archive.
