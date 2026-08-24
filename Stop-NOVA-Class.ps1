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
    Write-Host "Requesting a clean Class Capture shutdown..." -ForegroundColor Cyan

    & $python -m nova_capture.control stop --wait --timeout 30 --close-launcher
    $code = $LASTEXITCODE

    if ($code -eq 0) {
        Write-Host ""
        Write-Host "NOVA Class Capture stop command completed." -ForegroundColor Green
        return
    }

    Write-Host ""
    Write-Host "NOVA could not confirm a complete Class Capture shutdown." -ForegroundColor Yellow
}
finally {
    Pop-Location
}
