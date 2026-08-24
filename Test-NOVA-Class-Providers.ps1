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

from nova_core.configuration import load_configuration
from nova_core.provider_registry import create_provider_registry

async def main():
    config = load_configuration()
    registry = create_provider_registry(config)
    results = await registry.health_check_all()

    print("=== NOVA CLASS PROVIDERS ===")
    for name in ("groq", "openai", "ollama"):
        item = results.get(name)
        if item is None:
            print(f"{name:8} NOT REGISTERED")
            continue
        state = "READY" if item["configured"] and item["reachable"] else "UNAVAILABLE"
        print(
            f"{name:8} {state:11} "
            f"configured={item['configured']} "
            f"reachable={item['reachable']} "
            f"model={item['model']}"
        )

asyncio.run(main())
'@ | & $python -
