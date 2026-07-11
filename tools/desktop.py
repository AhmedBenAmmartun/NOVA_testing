import subprocess
import webbrowser

import psutil
from livekit.agents import RunContext, function_tool

from .common import logger


# Only approved applications can be opened.
APP_WHITELIST = {
    "chrome": "chrome",
    "google": "chrome",
    "edge": "msedge",
    "vscode": "code",
    "vs code": "code",
    "notepad": "notepad",
    "calculator": "calc",
    "spotify": "spotify:",
    "cmd": "cmd",
    "powershell": "powershell",
    "explorer": "explorer",
    "file explorer": "explorer",
}


# Friendly names mapped to real Windows process names.
PROCESS_ALIASES = {
    "google": "chrome",
    "vs code": "code",
    "vscode": "code",
    "edge": "msedge",
    "calculator": "calculatorapp",
    "file explorer": "explorer",
}


@function_tool()
async def open_website(context: RunContext, url: str) -> str:
    """Open a website in the default browser."""
    try:
        cleaned_url = url.strip()

        if not cleaned_url.startswith(("http://", "https://")):
            cleaned_url = "https://" + cleaned_url

        webbrowser.open(cleaned_url)

        logger.info("open_website: %s", cleaned_url)

        return f"Opened {cleaned_url}"

    except Exception:
        logger.exception("open_website failed")
        return "I could not open that website."


@function_tool()
async def open_app(context: RunContext, app_name: str) -> str:
    """Open an approved Windows application."""
    cleaned_name = app_name.lower().strip()

    command = APP_WHITELIST.get(cleaned_name)

    if command is None:
        logger.warning("open_app rejected: %r", app_name)

        approved_apps = ", ".join(
            sorted(set(APP_WHITELIST.keys()))
        )

        return (
            f"{app_name} is not in the approved application list. "
            f"I can open: {approved_apps}."
        )

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", command],
            shell=False,
        )

        logger.info(
            "open_app: %s -> %s",
            cleaned_name,
            command,
        )

        return f"Opened {app_name}."

    except Exception:
        logger.exception("open_app failed")
        return f"I could not open {app_name}."


@function_tool()
async def is_app_running(
    context: RunContext,
    app_name: str,
) -> str:
    """Check whether an application is currently running."""
    try:
        cleaned_name = app_name.lower().strip()

        target = PROCESS_ALIASES.get(
            cleaned_name,
            cleaned_name,
        )

        target = target.replace(" ", "")

        running = any(
            (process.info["name"] or "")
            .lower()
            .removesuffix(".exe")
            == target
            for process in psutil.process_iter(["name"])
        )

        if running:
            return f"Yes, {app_name} is running."

        return f"No, {app_name} is not running."

    except Exception:
        logger.exception("is_app_running failed")
        return f"I could not check whether {app_name} is running."
    
@function_tool()
async def close_app(
    context: RunContext,
    app_name: str,
) -> str:
    """Close an approved application on Windows."""
    cleaned_name = app_name.lower().strip()

    process_map = {
        "chrome": "chrome.exe",
        "google": "chrome.exe",
        "edge": "msedge.exe",
        "vscode": "Code.exe",
        "vs code": "Code.exe",
        "notepad": "notepad.exe",
        "calculator": "CalculatorApp.exe",
        "spotify": "Spotify.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
    }

    process_name = process_map.get(cleaned_name)

    if process_name is None:
        logger.warning("close_app rejected: %r", app_name)

        approved_apps = ", ".join(
            sorted(process_map.keys())
        )

        return (
            f"{app_name} is not in the approved close-app list. "
            f"I can close: {approved_apps}."
        )

    try:
        result = subprocess.run(
            [
                "taskkill",
                "/IM",
                process_name,
                "/T",
            ],
            capture_output=True,
            text=True,
            shell=False,
        )

        if result.returncode == 0:
            logger.info(
                "close_app: %s -> %s",
                cleaned_name,
                process_name,
            )

            return f"Closed {app_name}."

        logger.warning(
            "close_app failed: %s",
            result.stderr.strip(),
        )

        return (
            f"I could not close {app_name}. "
            "It may not be running."
        )

    except Exception:
        logger.exception("close_app failed")
        return f"I could not close {app_name}."

@function_tool()
async def restart_app(
    context: RunContext,
    app_name: str,
) -> str:
    """Restart an approved application."""
    close_result = await close_app(context, app_name)

    if "Closed" not in close_result and "not be running" not in close_result:
        return close_result

    return await open_app(context, app_name)