$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$classScript = Join-Path $PSScriptRoot "Start-NOVA-Class.ps1"
$visionScript = Join-Path $PSScriptRoot "Start-NOVA-Vision.ps1"

if (-not (Test-Path $classScript)) {
    Write-Host "Missing Class Capture launcher:" -ForegroundColor Red
    Write-Host $classScript
    exit 1
}

if (-not (Test-Path $visionScript)) {
    Write-Host "Missing NOVA Vision launcher:" -ForegroundColor Red
    Write-Host $visionScript
    Write-Host ""
    Write-Host "Class Capture was NOT started because this combined launcher requires both." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " NOVA CLASS + VISION" -ForegroundColor Cyan
Write-Host " Starting Vision and Class Capture..." -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

Start-Process powershell.exe -ArgumentList @(
    "-NoExit",
    "-ExecutionPolicy", "Bypass",
    "-Command",
    "& `"$visionScript`""
)

Start-Sleep -Seconds 2

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $classScript
