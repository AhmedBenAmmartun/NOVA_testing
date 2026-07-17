# NOVA Desktop Companion

This folder contains NOVA's native desktop skin and the larger React/Vite
dashboard prototype.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File .\start_desktop_widget.ps1 -Mode mini
..\venv\Scripts\python.exe -m py_compile .\desktop_widget.py
..\venv\Scripts\python.exe -m unittest Dashboard.test_desktop_skin
..\venv\Scripts\python.exe .\desktop_widget.py --self-test
```

## Rules

- `desktop_widget.py` plus `desktop_host.py`, `skin_state.py`,
  `skin_registry.py`, `status_service.py`, and `command_service.py` are the
  actual desktop surface. Do not replace them with a browser-only flow when
  Ahmed asks for something that sits on the desktop.
- The default skin experience is a desktop profile, not a marketing page.
- Keep safe command-bar actions read/search/open/memory oriented. Sensitive
  actions should stay blocked there and go through voice NOVA for
  confirmation.
- Keep the NOVA runtime behind the typed service boundary in
  `src/novaClient.ts`; mock data is allowed until the Python bridge exists.
- Widget definitions live in `src/widgetRegistry.tsx` and shared contracts live
  in `src/types.ts`.
- Do not display private chain-of-thought, hidden prompts, secrets, tokens, or
  raw sensitive files in the UI.
- Preserve reduced-motion support and keyboard access when changing the shell.
- Do not add Tauri-specific behavior directly to widgets; keep desktop shell
  behavior in a future adapter.
