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
    Write-Host ""
    Write-Host "=== CLASS CAPTURE ===" -ForegroundColor Cyan
    & $python -m nova_capture.control status

    $captureRoot = Join-Path $env:LOCALAPPDATA "NOVA\ClassCapture"
    $latest = Get-ChildItem -LiteralPath $captureRoot -Directory -Recurse -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName "session.json") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -ne $latest) {
        Write-Host ""
        Write-Host "=== LATEST SESSION ===" -ForegroundColor Cyan
        Write-Host $latest.FullName
        $post = Join-Path $latest.FullName "postprocess.json"
        if (Test-Path -LiteralPath $post) {
            $state = Get-Content -LiteralPath $post -Raw | ConvertFrom-Json
            Write-Host "Post-class intelligence:" $state.status
            if ($state.output_folder) {
                Write-Host "Notes:" $state.output_folder
            }
            if ($state.error) {
                Write-Host "Post-process error:" $state.error -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "Post-class intelligence: not started"
        }
    }
}
finally {
    Pop-Location
}
