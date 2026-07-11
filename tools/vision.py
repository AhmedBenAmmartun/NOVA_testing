from datetime import datetime

from PIL import ImageGrab
from livekit.agents import RunContext, function_tool

from .common import PROJECT_ROOT, logger


SCREENSHOT_DIR = PROJECT_ROOT / "screenshots"

SCREENSHOT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


@function_tool()
async def capture_screen(context: RunContext) -> str:
    """Capture all connected screens after the user requests it."""
    try:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        screenshot_path = (
            SCREENSHOT_DIR
            / f"screen_{timestamp}.png"
        )

        screenshot = ImageGrab.grab(
            all_screens=True
        )

        screenshot.save(screenshot_path)

        logger.info(
            "capture_screen: %s",
            screenshot_path,
        )

        return (
            f"Captured the screen and saved it to "
            f"{screenshot_path}."
        )

    except Exception:
        logger.exception("capture_screen failed")
        return "I could not capture the screen."