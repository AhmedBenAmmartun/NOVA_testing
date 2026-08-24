param(
    [string]$Session = ""
)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$python = Join-Path $project "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "NOVA virtual environment was not found:" -ForegroundColor Red
    Write-Host $python
    return
}

Push-Location $project
try {
    if (-not $Session.Trim()) {
        $root = Join-Path $env:LOCALAPPDATA "NOVA\ClassCapture"
        $latest = Get-ChildItem -LiteralPath $root -Directory -Recurse -ErrorAction SilentlyContinue |
            Where-Object { Test-Path (Join-Path $_.FullName "session.json") } |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        if ($null -eq $latest) {
            Write-Host "No completed NOVA class session was found." -ForegroundColor Yellow
            return
        }
        $Session = $latest.FullName
    }

    & $python -m nova_capture.postprocess --session $Session
}
finally {
    Pop-Location
}
