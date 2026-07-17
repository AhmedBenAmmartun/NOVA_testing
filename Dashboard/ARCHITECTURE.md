# NOVA Desktop Companion Architecture

## Layers

- `desktop_widget.py`: native Tkinter desktop skin host and command-bar shell.
- `desktop_host.py`: Windows monitor, WorkerW, and wallpaper-layer helpers.
- `skin_state.py`: versioned profile/layout persistence under `%APPDATA%\NOVA`.
- `skin_registry.py`: canvas renderers for clock, orb, focus, system, memory,
  and activity modules.
- `status_service.py`: safe local status snapshots from system metrics, tool
  logs, conversation logs, and vault configuration.
- `command_service.py`: deterministic safe command vocabulary for the desktop
  command bar.
- `src/App.tsx`: mode shell, widget layout controls, gallery, command palette,
  and first-run setup.
- `src/types.ts`: shared typed contracts for settings, widgets, tasks, memory,
  assignments, activity events, and the NOVA service client.
- `src/settings.ts`: versioned persisted settings schema backed by
  `localStorage`.
- `src/novaClient.ts`: mock NOVA service adapter. This is the future boundary
  for HTTP commands and WebSocket events.
- `src/widgetRegistry.tsx`: typed widget definitions plus widget renderers.
- `src/index.css`: responsive desktop-widget visual system, themes, focus
  states, and reduced-motion behavior.

## Integration Boundary

The real NOVA runtime should eventually expose:

- WebSocket event stream for agent state, tool calls, memory reads/writes,
  task updates, model health, and system status.
- HTTP command endpoint for safe commands.
- Confirmation flow for sensitive or destructive actions.
- Cached snapshot endpoint for fast startup.

The dashboard must keep showing cached/mock data when the backend is offline
and must clearly label connection state.

## Widget Rules

- Widgets are registered in `widgetRegistry`.
- Widgets receive typed `snapshot`, `client`, and `instance` props.
- Widgets should not call browser APIs directly except for local UI behavior.
- Widgets must have empty/error-friendly rendering once real data is wired.
- Widgets must not expose private prompts, API keys, tokens, email bodies, or
  hidden reasoning.

## Native Desktop Skin

The current desktop surface is the Tkinter skin, not the React prototype. It
uses separate top-level windows for each module, attaches them to the Windows
wallpaper WorkerW host when available, and falls back to bottom-level popup
placement when WorkerW is unavailable.

The React dashboard remains the larger command-center prototype. If Tauri,
WebView2, or another shell is added later, keep shell-specific behavior in an
adapter instead of hardcoding it into widgets.

Remaining desktop-shell work:

- live NOVA HTTP/WebSocket bridge
- tray behavior on clean installs
- startup launch polish
- minimize-to-tray
- multi-monitor placement testing
- persisted live state and animation mapping
