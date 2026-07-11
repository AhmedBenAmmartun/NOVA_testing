from datetime import datetime

import psutil
import requests
from duckduckgo_search import DDGS
from livekit.agents import RunContext, function_tool

from .common import logger


@function_tool()
async def get_weather(context: RunContext, city: str) -> str:
    """Get the current weather for a city."""
    try:
        response = requests.get(
            f"https://wttr.in/{city}?format=3",
            timeout=10,
        )

        if response.status_code != 200:
            return "I could not retrieve the weather right now."

        return response.text.strip()

    except Exception:
        logger.exception("get_weather failed")
        return "I could not retrieve the weather right now."


@function_tool()
async def search_web(context: RunContext, query: str) -> str:
    """Search the web using DuckDuckGo."""
    try:
        results = list(
            DDGS().text(
                query,
                max_results=5,
            )
        )

        if not results:
            return "No search results were found."

        formatted_results = []

        for result in results:
            title = result.get("title", "Untitled result")
            body = result.get("body", "")
            url = result.get("href", "")

            formatted_results.append(
                f"{title}\n{body}\nSource: {url}"
            )

        return "\n\n".join(formatted_results)

    except Exception:
        logger.exception("search_web failed")
        return "I could not complete the web search."


@function_tool()
async def get_system_info(context: RunContext) -> str:
    """Get CPU, RAM, disk, and battery information."""
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        battery = psutil.sensors_battery()

        if battery:
            battery_text = f"Battery: {battery.percent}%"
        else:
            battery_text = "Battery information is not available."

        return (
            f"CPU usage: {cpu}%\n"
            f"RAM usage: {ram.percent}%\n"
            f"Disk usage: {disk.percent}%\n"
            f"{battery_text}"
        )

    except Exception:
        logger.exception("get_system_info failed")
        return "I could not retrieve the system information."


@function_tool()
async def get_time(context: RunContext) -> str:
    """Get the current local date and time."""
    now = datetime.now()

    return now.strftime(
        "Today is %A, %B %d, %Y. The time is %I:%M %p."
    )