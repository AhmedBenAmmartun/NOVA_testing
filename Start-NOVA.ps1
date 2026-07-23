# Safe manual launcher for the existing NOVA project.
# Starts at most one voice agent and one dashboard app. It does not enable
# Windows startup and it never reads or prints .env values.
[CmdletBinding()]
param(
    [switch]$DashboardOnly,
    [switch]$AgentOnly
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root 'venv\Scripts\python.exe'
$Agent = Join-Path $Root 'agent.py'
$AppDir = Join-Path $Root 'Dashboard\nova-app'
$InstalledExe = Join-Path $env:LOCALAPPDATA 'NOVA\NOVA.exe'
$ReleaseExe = Join-Path $AppDir 'src-tauri\target\release\NOVA.exe'

if (-not (Test-Path $Python)) {
    throw "NOVA virtual environment was not found at .\venv\Scripts\python.exe"
}
$env:NOVA_PROJECT_ROOT = $Root

function Test-NovaAgentRunning {
    $agentEscaped = [regex]::Escape($Agent)
    return [bool](Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            ($_.CommandLine -match $agentEscaped -or $_.CommandLine -match '(^|[\\/])agent\.py\s+console')
        } |
        Select-Object -First 1)
}

function Start-NovaAgent {
    if (Test-NovaAgentRunning) {
        Write-Host 'NOVA voice agent is already running.'
        return
    }
    Start-Process -FilePath $Python -ArgumentList @("`"$Agent`"", 'console') -WorkingDirectory $Root
    Write-Host 'Started the NOVA voice agent.'
}

function Start-NovaDashboard {
    if (Get-Process -Name 'NOVA' -ErrorAction SilentlyContinue) {
        Write-Host 'NOVA dashboard is already running.'
        return
    }
    $Executable = @($InstalledExe, $ReleaseExe) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($Executable) {
        Start-Process -FilePath $Executable -WorkingDirectory $Root
        Write-Host 'Started the NOVA dashboard.'
        return
    }
    if (-not (Test-Path (Join-Path $AppDir 'package.json'))) {
        throw 'Dashboard\nova-app was not found.'
    }
    $command = "Set-Location -LiteralPath '$($AppDir.Replace("'", "''"))'; npm run dev"
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoExit', '-NoProfile', '-Command', $command) -WorkingDirectory $AppDir
    Write-Host 'Started NOVA dashboard development mode.'
}

if (-not $DashboardOnly) { Start-NovaAgent }
if (-not $AgentOnly) { Start-NovaDashboard }
