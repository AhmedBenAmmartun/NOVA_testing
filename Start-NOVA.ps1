param(
    [switch]$AgentOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root 'venv\Scripts\python.exe'
$VisionLauncher = Join-Path $Root 'Start-NOVA-Vision.ps1'

Write-Host '=== NOVA ===' -ForegroundColor Cyan
Write-Host 'The legacy Dashboard is detached from NOVA.'
Write-Host 'NOVA Vision is the supported NOVA desktop surface.'
Write-Host ''

if ($AgentOnly) {
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw "NOVA Python environment not found: $Python"
    }

    Set-Location -LiteralPath $Root
    & $Python '.\agent.py' dev
    exit $LASTEXITCODE
}

if (-not (Test-Path -LiteralPath $VisionLauncher -PathType Leaf)) {
    throw "NOVA Vision launcher not found: $VisionLauncher"
}

& $VisionLauncher
exit $LASTEXITCODE
