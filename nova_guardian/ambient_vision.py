"""Retired screenshot-vision compatibility layer for NOVA Guardian.

NOVA Guardian no longer captures pixels. Visual media must come from the
trusted NOVA Vision client as an explicit LiveKit track. This module preserves
small compatibility types so older internal imports fail closed instead of
falling back to screenshots.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .config import GuardianConfiguration, load_guardian_configuration
from .state import GuardianState, get_guardian_state


RETIRED_REASON = "live_vision_client_required"
RETIRED_MESSAGE = (
    "Guardian screenshot vision is retired. Use the NOVA Vision client and "
    "explicitly enable a live camera, window, display, or browser-tab source."
)


@dataclass(frozen=True, slots=True)
class LocalVisionResult:
    """Compatibility result returned by the retired local-vision API."""

    analyzed: bool
    text: str
    model: str
    reason: str | None
    captured_at: datetime
    image_width: int | None = None
    image_height: int | None = None

    def safe_summary(self) -> dict[str, Any]:
        return {
            "analyzed": self.analyzed,
            "text": self.text,
            "model": self.model,
            "reason": self.reason,
            "captured_at": self.captured_at.isoformat(),
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


class AmbientVisionMonitor:
    """Fail-closed compatibility object; it never captures or stores pixels."""

    def __init__(
        self,
        *,
        configuration: GuardianConfiguration | None = None,
        state: GuardianState | None = None,
        model: str | None = None,
    ) -> None:
        self.configuration = configuration or load_guardian_configuration()
        self.state = state or get_guardian_state()
        self.model = model or "retired-screenshot-vision"

    async def analyze_once(
        self,
        question: str = "",
        *,
        force: bool = False,
    ) -> LocalVisionResult:
        del question, force
        return LocalVisionResult(
            analyzed=False,
            text=RETIRED_MESSAGE,
            model=self.model,
            reason=RETIRED_REASON,
            captured_at=datetime.now(timezone.utc),
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Remain inert until stopped; never acquire a visual source."""
        await stop_event.wait()
