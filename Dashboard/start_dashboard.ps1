# NOVA dashboard launcher (no browser).
#
# The NOVA dashboard ships as a standalone Tauri desktop app that starts
# its own Python data server silently. This script launches that app.
# If the app has not been built, it starts Dashboard/server.py for development.
$root = Split-Path $PSScriptRoot -Parent

$exeCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\NOVA\NOVA.exe"),
    (Join-Path $PSScriptRoot "nova-app\src-tauri\target\release\NOVA.exe")
)

$exe = $exeCandidates |
    Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1

if ($exe) {
    Start-Process -FilePath $exe
    return
}

Write-Host "NOVA app is not built yet - starting the data server only."

$pythonw = Join-Path $root "venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $pythonw)) {
    $pythonw = Join-Path $root "venv\Scripts\python.exe"
}

if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "NOVA Python environment was not found."
}

$serverPath = Join-Path $PSScriptRoot "server.py"
$port = if ($env:NOVA_DASHBOARD_PORT) {
    $env:NOVA_DASHBOARD_PORT
} else {
    "8787"
}

$existing = Get-NetTCPConnection `
    -LocalPort $port `
    -State Listen `
    -ErrorAction SilentlyContinue

if (-not $existing) {
    Start-Process `
        -FilePath $pythonw `
        -ArgumentList @($serverPath) `
        -WorkingDirectory $root `
        -WindowStyle Hidden
}