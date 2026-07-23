# NOVA dashboard launcher (no browser).
#
# The NOVA dashboard now ships as a standalone Tauri desktop app that starts
# its own Python data server silently. This script just launches that app.
# If the app has not been built yet it falls back to running the data server
# (Dashboard/server.py) for development — it never opens Edge or a browser.
$root = Split-Path $PSScriptRoot -Parent

$exeCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\NOVA\NOVA.exe"),
    (Join-Path $PSScriptRoot "nova-app\src-tauri\target\release\NOVA.exe")
)
$exe = $exeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($exe) {
    Start-Process -FilePath $exe
    return
}

Write-Host "NOVA app not built yet — starting the data server only (dev)."
$pythonw = Join-Path $root "venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = Join-Path $root "venv\Scripts\python.exe" }
$port = if ($env:NOVA_DASHBOARD_PORT) { $env:NOVA_DASHBOARD_PORT } else { "8787" }
$existing = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $existing) {
    Start-Process -FilePath $pythonw -ArgumentList "`"$PSScriptRoot\server.py`"" `
        -WorkingDirectory $root -WindowStyle Hidden
}
