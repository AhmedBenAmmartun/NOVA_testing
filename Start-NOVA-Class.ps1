param(
    [string]$Course = ""
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
    & $python -m nova_capture.control guard-start
    if ($LASTEXITCODE -ne 0) {
        return
    }

    $hadCourse = Test-Path Env:NOVA_CLASS_COURSE
    $previousCourse = $env:NOVA_CLASS_COURSE

    try {
        if ($Course.Trim()) {
            $env:NOVA_CLASS_COURSE = $Course.Trim()
        }
        else {
            Remove-Item Env:NOVA_CLASS_COURSE -ErrorAction SilentlyContinue
        }

        $env:PYTHONIOENCODING = "utf-8"
        & $python "class_capture.py" console
    }
    finally {
        if ($hadCourse) {
            $env:NOVA_CLASS_COURSE = $previousCourse
        }
        else {
            Remove-Item Env:NOVA_CLASS_COURSE -ErrorAction SilentlyContinue
        }
    }
}
finally {
    Pop-Location
}
