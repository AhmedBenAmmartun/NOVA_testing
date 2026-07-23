# Start the real NOVA dashboard

This package contains the five-page NOVA desktop dashboard and the supplied
NOVA agent/tool source. It does not include credentials, a Python virtual
environment, private notes, logs, or build output.

## 1. Install the NOVA Python environment

From PowerShell in the extracted project folder:

```powershell
py -m venv venv
& ".\venv\Scripts\python.exe" -m pip install -r requirements.txt
Copy-Item ".env.example" ".env.local"
```

Edit `.env.local` locally and add only the credentials you already use for
NOVA. Never send or commit that file.

## 2. Start NOVA and the dashboard

Open two PowerShell windows in the project folder.

Terminal 1 — the real voice agent:

```powershell
& ".\venv\Scripts\python.exe" agent.py console
```

Terminal 2 — the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File ".\Dashboard\start_dashboard.ps1"
```

The dashboard's teal `LIVE` pill means the local data server is connected.
Open `http://127.0.0.1:8787/health`; `agentBridge: active` means Ctrl+K prompts
and Approve/Deny can reach the current agent session.

## 3. Run verification

```powershell
npm --prefix Dashboard install
npm --prefix Dashboard run build
npm --prefix Dashboard run lint
npm --prefix Dashboard test
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" tools
& ".\venv\Scripts\python.exe" ".agents\skills\run-ai-agent\driver.py" chat "What can you help me with?"
```

## 4. Run or build the native Windows shell

Install the Rust/Tauri Windows prerequisites, then:

```powershell
Set-Location ".\Dashboard\nova-app"
npm install
npm run dev
```

To create the NSIS installer:

```powershell
npm run build
```

Calendar is intentionally marked Demo Data until you choose and authorize a
calendar adapter. No Google, Microsoft, Spotify, Obsidian, or AI credentials
are bundled in this archive.
