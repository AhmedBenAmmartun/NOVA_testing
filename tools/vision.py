"""Legacy screenshot vision compatibility module.

NOVA's old screenshot-based vision path is intentionally retired.
Visual input must come from the trusted live NOVA Vision client, which will
publish one explicitly selected visual track at a time through LiveKit.

These compatibility callables are deliberately *not* LiveKit function tools.
They exist only so older imports fail safely instead of capturing pixels.
"""

from livekit.agents import RunContext


_RETIRED_MESSAGE = (
    "Screenshot vision has been retired. Use the NOVA Vision live-sharing "
    "client to explicitly share a camera, window, display, or browser tab."
)


async def capture_screen(context: RunContext) -> str:
    """Refuse the retired screenshot-capture path without capturing pixels."""
    return _RETIRED_MESSAGE


async def analyze_screen_with_gpt56(
    context: RunContext,
    question: str = "",
    user_confirmed_screen_share: bool = False,
) -> str:
    """Refuse the retired screenshot-upload path without capturing pixels."""
    del question, user_confirmed_screen_share
    return _RETIRED_MESSAGE
