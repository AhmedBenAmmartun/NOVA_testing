$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "NOVA virtual environment was not found:" -ForegroundColor Red
    Write-Host $python
    exit 1
}

Write-Host "Installing local audio backup dependency..." -ForegroundColor Cyan
& $python -m pip install sounddevice

if ($LASTEXITCODE -ne 0) {
    Write-Host "sounddevice install failed. Transcript mode can still run, but audio backup will be unavailable." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Running syntax check..." -ForegroundColor Cyan
& $python -m py_compile "class_capture.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Syntax check FAILED." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Class Capture files are ready." -ForegroundColor Green
Write-Host "Start with: .\Start-NOVA-Class.ps1"
