# Start NOVA

> **Project boundary — 2026-08-15**
>
> The legacy Dashboard is no longer part of NOVA. NOVA Vision remains part of
> NOVA. Valo/dashboard work lives as a separate project.

## Start NOVA Vision

From PowerShell:

```powershell
Set-Location "C:\Projects\AI Agent"
.\Start-NOVA-Vision.ps1
```

Camera and microphone start off and remain user-controlled from the NOVA Vision
window.

## Start the agent without the Vision window

```powershell
Set-Location "C:\Projects\AI Agent"
.\Start-NOVA.ps1 -AgentOnly
```

## Project boundary

NOVA contains the realtime agent, NOVA OS capability kernel, tools, skills,
integrations, security/policy code, and `vision-client/`.

The old `Dashboard/` application and its local dashboard command bridge are not
NOVA runtime components anymore. Any future Valo/NOVA connection must use a
separate, explicit interface rather than importing Dashboard code into NOVA.
