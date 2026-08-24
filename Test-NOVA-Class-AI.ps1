$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "NOVA virtual environment was not found:" -ForegroundColor Red
    Write-Host $python
    exit 1
}

@'
import asyncio
from dotenv import load_dotenv

load_dotenv(".env.local")
load_dotenv(".env")

from nova_capture.class_budget import get_class_cloud_usage_budget
from nova_capture.intelligence import _route

async def main():
    budget = get_class_cloud_usage_budget().status()
    print("=== NOVA CLASS AI ===")
    print(
        "Class cloud budget: "
        f"used={budget['used_today']} "
        f"remaining={budget['remaining_today']} "
        f"limit={budget['daily_request_limit']}"
    )
    answer = await _route(
        "In 2-3 sentences, explain the difference between aggregation and composition in UML."
    )
    if not answer:
        print("Generation: FAILED")
        raise SystemExit(1)
    print("Generation: READY")
    print()
    print(answer)

asyncio.run(main())
'@ | & $python -
exit $LASTEXITCODE
