$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (Test-Path ".venv\Scripts\python.exe") {
    $Python = ".venv\Scripts\python.exe"
} elseif (Test-Path "venv\Scripts\python.exe") {
    $Python = "venv\Scripts\python.exe"
} else {
    $Python = "python"
}

& $Python -m nova_integrations.cli accounts list
& $Python -m nova_integrations.cli sync
