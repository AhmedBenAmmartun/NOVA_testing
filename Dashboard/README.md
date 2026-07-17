# NOVA Desktop Companion

This folder contains two pieces:

1. Native Windows desktop skin files:
   - `desktop_widget.py` runs the Tkinter skin host.
   - `desktop_host.py` handles monitor detection and WorkerW wallpaper
     attachment.
   - `skin_state.py` persists monitor-relative layout and profiles.
   - `skin_registry.py` renders the skin modules.
   - `status_service.py` reads safe local NOVA status.
   - `command_service.py` powers the safe command bar.
   The skin is borderless, desktop-attached when Windows allows it, and
   launched with `pythonw.exe`, so it sits on the desktop instead of opening
   as a browser app.
2. `src/` - the React/Vite command-center prototype used for the larger
   future dashboard.

## What It Does

- Native skin starts in the focus profile by default and supports
  `minimal`, `focus`, `study`, and `system` profiles. Legacy modes
  `orb`, `mini`, `compact`, and `full` map to those profiles.
- It shows separate desktop modules for clock, orb, focus, system, memory,
  and activity.
- It shows local NOVA status: system usage, vault status, latest tool log,
  latest saved conversation, and the current bridge priority.
- It persists layout, profile, lock state, startup preference, and focus text
  under `%APPDATA%\NOVA`.
- It exposes only safe local commands from the command bar. Sensitive actions
  are blocked there and should go through voice NOVA for confirmation.
- It does not use a browser, Vite server, Electron, or Tauri to appear on the
  desktop.
- It shows only observable operational activity. It does not display private
  chain-of-thought.

## Run

Native desktop widget:

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"
powershell -ExecutionPolicy Bypass -File ".\Dashboard\start_desktop_widget.ps1" -Mode mini
```

Profiles: `minimal`, `focus`, `study`, `system`.
Legacy modes: `orb`, `mini`, `compact`, `full`.

React prototype:

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent\Dashboard"
pnpm install
pnpm run dev
```

## Verify

```powershell
Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent"
& ".\venv\Scripts\python.exe" -m py_compile ".\Dashboard\desktop_widget.py"
& ".\venv\Scripts\python.exe" -m unittest Dashboard.test_desktop_skin
& ".\venv\Scripts\python.exe" ".\Dashboard\desktop_widget.py" --self-test

Set-Location "C:\Users\ahmed\OneDrive\Desktop\AI Agent\Dashboard"
pnpm run typecheck
pnpm run build
```

## Next Steps

1. Replace the widget's local polling with a real WebSocket/HTTP bridge from the
   Python NOVA runtime.
2. Add tray, startup, minimize-to-tray, and multi-monitor placement.
3. Decide whether the React command center should be embedded later through
   Tauri/WebView2 or kept as a separate larger dashboard.
