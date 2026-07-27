#!/usr/bin/env pwsh
# One-command demo: creates a venv if needed, installs requirements, and
# launches the dashboard in demo mode (NOVA_DASHBOARD_DEMO=1) at
# http://127.0.0.1:8787 with clearly-labeled sample data — no NOVA agent,
# Obsidian vault, or Spotify required.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    python -m venv venv
}

Write-Host "Installing requirements..."
& ".\venv\Scripts\python.exe" -m pip install -q -r requirements.txt

$env:NOVA_DASHBOARD_DEMO = "1"
Write-Host "Starting NOVA Dashboard (demo mode) at http://127.0.0.1:8787 ..."
& ".\venv\Scripts\python.exe" server.py
