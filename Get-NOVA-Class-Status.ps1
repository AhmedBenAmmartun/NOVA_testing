param(
    [string]$Session = "",
    [switch]$Json,
    [switch]$Watch,
    [int]$IntervalSeconds = 10
)

$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$python = Join-Path $project "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "NOVA virtual environment was not found:" -ForegroundColor Red
    Write-Host $python
    return
}

function Show-NovaClassStatus {
    param([string]$Project, [string]$Python, [string]$SessionPath, [bool]$AsJson)

    $arguments = @("-m", "nova_capture.status")
    if ($SessionPath) { $arguments += @("--session", $SessionPath) }
    if ($AsJson) { $arguments += "--json" }

    $env:PYTHONIOENCODING = "utf-8"
    & $Python $arguments
}

Push-Location $project
try {
    Write-Host ""
    Write-Host "=== CLASS CAPTURE LIFECYCLE ===" -ForegroundColor Cyan
    & $python -m nova_capture.control status
    Write-Host ""

    if ($Watch) {
        Write-Host "Watching class health. Press Ctrl+C to stop watching." -ForegroundColor Cyan
        Write-Host "(This only watches. It never stops the recording.)" -ForegroundColor DarkGray
        while ($true) {
            Clear-Host
            Write-Host ("Refreshed {0}" -f (Get-Date -Format "HH:mm:ss")) -ForegroundColor DarkGray
            Show-NovaClassStatus -Project $project -Python $python -SessionPath $Session -AsJson:$Json.IsPresent
            Start-Sleep -Seconds ([Math]::Max(2, $IntervalSeconds))
        }
    }
    else {
        Show-NovaClassStatus -Project $project -Python $python -SessionPath $Session -AsJson:$Json.IsPresent
    }
}
finally {
    Pop-Location
}
