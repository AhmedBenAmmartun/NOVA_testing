#!/usr/bin/env bash
# One-command demo: creates a venv if needed, installs requirements, and
# launches the dashboard in demo mode (NOVA_DASHBOARD_DEMO=1) at
# http://127.0.0.1:8787 with clearly-labeled sample data — no NOVA agent,
# Obsidian vault, or Spotify required. Note: several feeds (Spotify window
# title, real app registry) use Windows-only APIs; on Linux/macOS you'll
# still get demo mode's sample data plus real weather/system stats.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -f "venv/bin/python" ] && [ ! -f "venv/Scripts/python.exe" ]; then
    echo "Creating venv..."
    python3 -m venv venv
fi

PYTHON="venv/bin/python"
[ -f "$PYTHON" ] || PYTHON="venv/Scripts/python.exe"

echo "Installing requirements..."
"$PYTHON" -m pip install -q -r requirements.txt

export NOVA_DASHBOARD_DEMO=1
echo "Starting NOVA Dashboard (demo mode) at http://127.0.0.1:8787 ..."
"$PYTHON" server.py
