<#
.SYNOPSIS
    Watch a real, running NOVA class recording for a long stretch of wall clock.

.DESCRIPTION
    Automated tests prove the capture logic survives a simulated three hours.
    Only a real run proves this machine, this microphone, this network, and
    this LiveKit account do. Start a class, then run this beside it.

    This script only observes. It never starts or stops a recording.

.EXAMPLE
    .\Test-NOVA-Class-Endurance.ps1 -Minutes 150
#>
param(
    [double]$Minutes = 150,
    [double]$IntervalSeconds = 30,
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
    $env:PYTHONIOENCODING = "utf-8"

    & $python -m nova_capture.control status
    Write-Host ""

    $arguments = @(
        "scripts\nova_class_endurance.py",
        "--minutes", $Minutes,
        "--interval-seconds", $IntervalSeconds
    )
    if ($Session) { $arguments += @("--session", $Session) }

    & $python $arguments
    $code = $LASTEXITCODE

    Write-Host ""
    if ($code -eq 0) {
        Write-Host "ENDURANCE SOAK: PASS" -ForegroundColor Green
    }
    else {
        Write-Host "ENDURANCE SOAK: FAIL - see the failures listed above." -ForegroundColor Red
        Write-Host "The recording itself is untouched; check it before stopping the class." -ForegroundColor Yellow
    }
}
finally {
    Pop-Location
}
