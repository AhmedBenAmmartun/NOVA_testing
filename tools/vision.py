from datetime import datetime
from nova_core.cloud_budget import get_cloud_usage_budget

from PIL import ImageGrab
from livekit.agents import RunContext, function_tool

from .common import PROJECT_ROOT, logger
from .models import (
    ModelUnavailableError,
    run_gpt56_with_image,
)


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


@function_tool()
async def analyze_screen_with_gpt56(
    context: RunContext,
    question: str,
    user_confirmed_screen_share: bool = False,
) -> str:
    """
    Capture the screen and send it to GPT-5.6 only after explicit consent.
    """
    if not user_confirmed_screen_share:
        return (
            "Before I send a screenshot to GPT-5.6, please confirm "
            "that the screen does not show private information or "
            "that you are okay sharing what is visible."
        )

    try:
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        screenshot_path = (
            SCREENSHOT_DIR
            / f"gpt56_screen_{timestamp}.png"
        )

        screenshot = ImageGrab.grab(
            all_screens=True
        )

        screenshot.save(screenshot_path)

        logger.info(
            "analyze_screen_with_gpt56 captured: %s",
            screenshot_path,
        )

        return await run_gpt56_with_image(
            image_path=screenshot_path,
            question=question,
        )

    except ModelUnavailableError as error:
        return str(error)

    except Exception:
        logger.exception(
            "analyze_screen_with_gpt56 failed"
        )
        return (
            "I could not analyze the screen with GPT-5.6."
        )
