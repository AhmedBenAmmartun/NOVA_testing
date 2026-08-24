param(
    [Parameter(Mandatory=$true)]
    [string]$Path,
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
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if ($Session.Trim()) {
        & $python -m nova_school.cli attach-session $resolved --session $Session
    }
    else {
        & $python -m nova_school.cli attach-session $resolved
    }
}
finally {
    Pop-Location
}
