# nova-app — the NOVA Desktop Tauri shell

Wraps the existing NOVA dashboard (`Dashboard/web` + `Dashboard/server.py`) as
a standalone Windows app. No browser: the design renders in a borderless
WebView2 window, and the Python data server runs silently as a child process.

## Build / run

```powershell
cd Dashboard\nova-app
npm install            # once: pulls @tauri-apps/cli + api
npx tauri dev          # dev window (debug, hot-reload)
npx tauri build        # release .exe + NSIS installer
```

Building requires the Rust toolchain and the Windows prerequisites documented
by Tauri. The web runtime itself is fully local under `Dashboard/web`; no React,
Babel, or font CDN is contacted when NOVA launches.

Outputs (release):

- exe: `src-tauri/target/release/NOVA.exe`
- installer: `src-tauri/target/release/bundle/nsis/NOVA_1.0.0_x64-setup.exe`
- installs to `%LOCALAPPDATA%\Programs\NOVA\NOVA.exe` (per-user, no admin)

## What the Rust side does (`src-tauri/src/lib.rs`)

- **Backend sidecar** — spawns `venv\Scripts\pythonw.exe Dashboard\server.py`
  with `CREATE_NO_WINDOW` (no console). Reuses an already-listening server if
  one is up. Killed on quit; respawned by *Restart NOVA*.
- **Single instance** — `tauri-plugin-single-instance` focuses the running
  window on a second launch.
- **Tray** — Open / Hide / Desktop Mode / Always on Top / Start with Windows /
  Restart NOVA / Quit NOVA. Left-click shows the window.
- **Close-to-tray** — `CloseRequested` is intercepted; the window hides.
- **Window/Desktop modes & autostart** — commands invoked from the frontend
  (`web/tauri-shell.js`): `enter_desktop_mode` (borderless, always-on-bottom,
  skip-taskbar, sized to the work area), `enter_dashboard_mode`,
  `set_always_on_top`, `set_click_through`, `set_autostart`, plus the window
  controls `win_minimize` / `win_toggle_maximize` / `win_hide`.

## Locating the project

The app needs the venv + `server.py`. It resolves the project root from, in
order: the `NOVA_PROJECT_ROOT` env var, the exe's parent chain (covers dev
builds), then the known install path baked into `project_root()`. If you move
the project, set `NOVA_PROJECT_ROOT` or update that fallback.

## Frontend integration

`web/tauri-shell.js` is loaded by `web/index.html` and is **inert in a normal
browser**. Under Tauri it sets `window.NOVA_BACKEND = '127.0.0.1:8787'`, injects
the custom title bar, wires the tray/mode events, and handles drag + mode
switching. The dashboard design itself is unchanged.
