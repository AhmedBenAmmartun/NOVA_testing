"""Local, privacy-first ambient vision for NOVA Guardian."""

from __future__ import annotations

import asyncio
import base64
import ctypes
import io
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
from PIL import (
    Image,
    ImageChops,
    ImageGrab,
    ImageStat,
)

from .config import (
    GuardianConfiguration,
    VisionMode,
    load_guardian_configuration,
)
from .events import (
    GuardianEventCategory,
    GuardianEventSeverity,
    GuardianEventType,
    create_guardian_event,
)
from .state import (
    GuardianState,
    get_guardian_state,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LocalVisionResult:
    """Result from one local screenshot-analysis attempt."""

    analyzed: bool
    text: str
    model: str
    reason: str | None
    captured_at: datetime
    image_width: int | None = None
    image_height: int | None = None

    def safe_summary(self) -> dict[str, Any]:
        """Return result information without image contents."""

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
    """
    Perform local screenshot understanding through Ollama.

    Screenshots are kept in memory. This component does not save
    screenshots to disk and does not send them to a cloud provider.
    """

    def __init__(
        self,
        *,
        configuration: GuardianConfiguration | None = None,
        state: GuardianState | None = None,
        model: str | None = None,
        ollama_base_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.configuration = (
            configuration
            if configuration is not None
            else load_guardian_configuration()
        )

        self.state = (
            state
            if state is not None
            else get_guardian_state()
        )

        configured_model = os.getenv(
            "NOVA_LOCAL_VISION_MODEL",
            "gemma3:4b",
        ).strip()

        self.model = (
            model
            or configured_model
            or "gemma3:4b"
        )

        configured_base_url = os.getenv(
            "NOVA_OLLAMA_BASE_URL",
            "http://localhost:11434",
        ).strip()

        self.ollama_base_url = (
            ollama_base_url
            or configured_base_url
            or "http://localhost:11434"
        ).rstrip("/")

        self.timeout_seconds = (
            self._environment_float(
                "NOVA_LOCAL_VISION_TIMEOUT_SECONDS",
                default=240.0,
                minimum=5.0,
            )
            if timeout_seconds is None
            else max(5.0, timeout_seconds)
        )

        self.change_threshold = self._environment_float(
            "NOVA_VISION_CHANGE_THRESHOLD",
            default=8.0,
            minimum=0.0,
        )

        self.maximum_image_dimension = self._environment_int(
            "NOVA_LOCAL_VISION_MAX_DIMENSION",
            default=512,
            minimum=256,
        )

        self.maximum_output_tokens = self._environment_int(
            "NOVA_LOCAL_VISION_MAX_OUTPUT_TOKENS",
            default=100,
            minimum=20,
        )

        self.context_size = self._environment_int(
            "NOVA_LOCAL_VISION_CONTEXT_SIZE",
            default=2048,
            minimum=512,
        )

        self.keep_alive = (
            os.getenv(
                "NOVA_LOCAL_VISION_KEEP_ALIVE",
                "10m",
            ).strip()
            or "10m"
        )

        self._previous_thumbnail: Image.Image | None = None
        self._last_result: LocalVisionResult | None = None

    @staticmethod
    def _environment_float(
        name: str,
        *,
        default: float,
        minimum: float,
    ) -> float:
        """Read a floating-point environment value safely."""

        raw_value = os.getenv(name)

        if raw_value is None:
            return default

        try:
            value = float(raw_value)

        except ValueError:
            logger.warning(
                "Invalid %s value. Using %s.",
                name,
                default,
            )
            return default

        return max(minimum, value)

    @staticmethod
    def _environment_int(
        name: str,
        *,
        default: int,
        minimum: int,
    ) -> int:
        """Read an integer environment value safely."""

        raw_value = os.getenv(name)

        if raw_value is None:
            return default

        try:
            value = int(raw_value)

        except ValueError:
            logger.warning(
                "Invalid %s value. Using %s.",
                name,
                default,
            )
            return default

        return max(minimum, value)

    def health_check(self) -> bool:
        """Return whether Ollama and the vision model are available."""

        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=5,
            )

            response.raise_for_status()
            payload = response.json()

        except (
            requests.RequestException,
            ValueError,
        ):
            return False

        if not isinstance(payload, dict):
            return False

        models = payload.get(
            "models",
            [],
        )

        if not isinstance(models, list):
            return False

        for model_information in models:
            if not isinstance(
                model_information,
                dict,
            ):
                continue

            model_name = model_information.get(
                "name"
            )

            if (
                isinstance(model_name, str)
                and model_name == self.model
            ):
                return True

        return False

    @staticmethod
    def _foreground_window_bounds(
    ) -> tuple[int, int, int, int] | None:
        """Return the foreground-window rectangle on Windows."""

        if os.name != "nt":
            return None

        try:
            user32 = ctypes.WinDLL(
                "user32",
                use_last_error=True,
            )

            window_handle = (
                user32.GetForegroundWindow()
            )

            if not window_handle:
                return None

            rectangle = wintypes.RECT()

            succeeded = user32.GetWindowRect(
                window_handle,
                ctypes.byref(rectangle),
            )

            if not succeeded:
                return None

            left = int(rectangle.left)
            top = int(rectangle.top)
            right = int(rectangle.right)
            bottom = int(rectangle.bottom)

            width = right - left
            height = bottom - top

            if width < 100 or height < 100:
                return None

            return (
                left,
                top,
                right,
                bottom,
            )

        except Exception:
            logger.debug(
                "Could not read foreground-window bounds.",
                exc_info=True,
            )
            return None

    def _capture_frame(
        self,
    ) -> Image.Image | None:
        """Capture the foreground window into memory."""

        runtime = self.state.snapshot()

        if not runtime.running:
            return None

        if not runtime.vision_active:
            return None

        if runtime.vision_paused:
            return None

        bounds = self._foreground_window_bounds()

        try:
            if bounds is not None:
                screenshot = ImageGrab.grab(
                    bbox=bounds,
                    all_screens=True,
                )

            else:
                screenshot = ImageGrab.grab(
                    all_screens=True
                )

        except Exception:
            logger.exception(
                "NOVA local vision could not capture the screen."
            )
            return None

        return screenshot.convert("RGB")

    def _resize_for_model(
        self,
        image: Image.Image,
    ) -> Image.Image:
        """Resize a frame to reduce local inference cost."""

        width, height = image.size

        largest_dimension = max(
            width,
            height,
        )

        if (
            largest_dimension
            <= self.maximum_image_dimension
        ):
            return image

        scale = (
            self.maximum_image_dimension
            / largest_dimension
        )

        resized_width = max(
            1,
            int(width * scale),
        )

        resized_height = max(
            1,
            int(height * scale),
        )

        return image.resize(
            (
                resized_width,
                resized_height,
            ),
            Image.Resampling.LANCZOS,
        )

    @staticmethod
    def _create_thumbnail(
        image: Image.Image,
    ) -> Image.Image:
        """Create a grayscale thumbnail for change detection."""

        return (
            image
            .convert("L")
            .resize(
                (160, 90),
                Image.Resampling.BILINEAR,
            )
        )

    def _screen_changed_meaningfully(
        self,
        image: Image.Image,
    ) -> bool:
        """Return whether the screen changed enough to analyze."""

        current_thumbnail = (
            self._create_thumbnail(
                image
            )
        )

        previous_thumbnail = (
            self._previous_thumbnail
        )

        self._previous_thumbnail = (
            current_thumbnail
        )

        if previous_thumbnail is None:
            return True

        difference = ImageChops.difference(
            previous_thumbnail,
            current_thumbnail,
        )

        statistics = ImageStat.Stat(
            difference
        )

        if not statistics.mean:
            return False

        average_difference = (
            sum(statistics.mean)
            / len(statistics.mean)
        )

        return (
            average_difference
            >= self.change_threshold
        )

    @staticmethod
    def _encode_image(
        image: Image.Image,
    ) -> str:
        """Convert an in-memory frame to a base64 JPEG."""

        with io.BytesIO() as buffer:
            image.save(
                buffer,
                format="JPEG",
                quality=70,
                optimize=True,
            )

            return base64.b64encode(
                buffer.getvalue()
            ).decode("ascii")

    def _call_local_vision_model(
        self,
        *,
        image: Image.Image,
        question: str,
    ) -> str:
        """Send an in-memory frame only to local Ollama."""

        encoded_image = self._encode_image(
            image
        )

        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are NOVA's local visual-awareness "
                        "component. Describe only information relevant "
                        "to the user's question. Do not guess passwords, "
                        "hidden text, identities, private information, "
                        "or anything that is not clearly visible. "
                        "Be concise and mention uncertainty."
                    ),
                },
                {
                    "role": "user",
                    "content": question,
                    "images": [
                        encoded_image
                    ],
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_predict": (
                    self.maximum_output_tokens
                ),
                "num_ctx": self.context_size,
            },
        }

        response = requests.post(
            f"{self.ollama_base_url}/api/chat",
            json=payload,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        response_payload = response.json()

        if not isinstance(
            response_payload,
            dict,
        ):
            raise RuntimeError(
                "Ollama returned an invalid response."
            )

        message = response_payload.get(
            "message"
        )

        if not isinstance(message, dict):
            raise RuntimeError(
                "Ollama returned no vision message."
            )

        content = message.get(
            "content"
        )

        if not isinstance(content, str):
            raise RuntimeError(
                "Ollama returned invalid vision content."
            )

        cleaned_content = content.strip()

        if not cleaned_content:
            raise RuntimeError(
                "Ollama returned an empty vision response."
            )

        return cleaned_content

    def _skipped_result(
        self,
        *,
        reason: str,
        text: str,
    ) -> LocalVisionResult:
        """Create a result for a safely skipped frame."""

        return LocalVisionResult(
            analyzed=False,
            text=text,
            model=self.model,
            reason=reason,
            captured_at=datetime.now(
                timezone.utc
            ),
        )

    async def analyze_once(
        self,
        question: str = (
            "Briefly describe the active application, "
            "important visible content, and whether anything "
            "appears to require the user's attention."
        ),
        *,
        force: bool = False,
    ) -> LocalVisionResult:
        """Capture and locally analyze one foreground-window frame."""

        cleaned_question = question.strip()

        if not cleaned_question:
            cleaned_question = (
                "Briefly describe what is visible."
            )

        if not self.configuration.enabled:
            return self._skipped_result(
                reason="guardian_disabled",
                text="Guardian is disabled.",
            )

        if not self.configuration.local_vision_only:
            return self._skipped_result(
                reason="local_vision_required",
                text=(
                    "Ambient vision is restricted "
                    "to local processing."
                ),
            )

        if (
            self.configuration.vision_mode
            == VisionMode.OFF
        ):
            return self._skipped_result(
                reason="vision_mode_off",
                text="Local vision is turned off.",
            )

        runtime = self.state.snapshot()

        if not runtime.running:
            return self._skipped_result(
                reason="guardian_not_running",
                text="Guardian is not running.",
            )

        if not runtime.vision_active:
            return self._skipped_result(
                reason="vision_not_active",
                text="Local vision is not active.",
            )

        if runtime.vision_paused:
            return self._skipped_result(
                reason="vision_paused",
                text=(
                    "Local vision is paused: "
                    f"{runtime.vision_pause_reason}"
                ),
            )

        frame = self._capture_frame()

        if frame is None:
            return self._skipped_result(
                reason="capture_failed",
                text=(
                    "NOVA could not capture the "
                    "active window."
                ),
            )

        original_width, original_height = (
            frame.size
        )

        if (
            not force
            and not self._screen_changed_meaningfully(
                frame
            )
        ):
            return LocalVisionResult(
                analyzed=False,
                text=(
                    "The active window has not changed "
                    "enough to require another analysis."
                ),
                model=self.model,
                reason="screen_unchanged",
                captured_at=datetime.now(
                    timezone.utc
                ),
                image_width=original_width,
                image_height=original_height,
            )

        if force:
            self._previous_thumbnail = (
                self._create_thumbnail(
                    frame
                )
            )

        resized_frame = self._resize_for_model(
            frame
        )

        try:
            text = await asyncio.to_thread(
                self._call_local_vision_model,
                image=resized_frame,
                question=cleaned_question,
            )

        except requests.Timeout:
            return LocalVisionResult(
                analyzed=False,
                text=(
                    "The local vision model took too "
                    "long to respond."
                ),
                model=self.model,
                reason="ollama_timeout",
                captured_at=datetime.now(
                    timezone.utc
                ),
                image_width=original_width,
                image_height=original_height,
            )

        except requests.RequestException:
            logger.exception(
                "Local Ollama vision request failed."
            )

            return LocalVisionResult(
                analyzed=False,
                text=(
                    "NOVA could not reach the local "
                    "Ollama vision model."
                ),
                model=self.model,
                reason="ollama_unavailable",
                captured_at=datetime.now(
                    timezone.utc
                ),
                image_width=original_width,
                image_height=original_height,
            )

        except Exception:
            logger.exception(
                "Local screenshot analysis failed."
            )

            return LocalVisionResult(
                analyzed=False,
                text=(
                    "NOVA could not understand the "
                    "current screen."
                ),
                model=self.model,
                reason="analysis_failed",
                captured_at=datetime.now(
                    timezone.utc
                ),
                image_width=original_width,
                image_height=original_height,
            )

        result = LocalVisionResult(
            analyzed=True,
            text=text,
            model=self.model,
            reason=None,
            captured_at=datetime.now(
                timezone.utc
            ),
            image_width=original_width,
            image_height=original_height,
        )

        self._last_result = result

        return result

    def _record_vision_event(
        self,
        *,
        event_type: GuardianEventType,
        severity: GuardianEventSeverity,
        title: str,
        message: str,
    ) -> None:
        """Record one local-vision lifecycle event."""

        event = create_guardian_event(
            event_type=event_type,
            category=(
                GuardianEventCategory.VISION
            ),
            severity=severity,
            title=title,
            message=message,
            source="ambient_vision",
            metadata={
                "model": self.model,
                "local_only": True,
            },
            requires_attention=False,
        )

        self.state.record_event(
            event
        )

    async def run(
        self,
        stop_event: asyncio.Event,
    ) -> None:
        """Run local ambient vision until stopped."""

        if not self.configuration.enabled:
            return

        if self.configuration.vision_mode not in {
            VisionMode.AMBIENT,
            VisionMode.TEMPORARY_SESSION,
        }:
            return

        self.state.start()

        started_vision_here = (
            not self.state.snapshot().vision_active
        )

        if started_vision_here:
            self.state.start_vision()

            self._record_vision_event(
                event_type=(
                    GuardianEventType.VISION_STARTED
                ),
                severity=(
                    GuardianEventSeverity.INFO
                ),
                title="Local vision started",
                message=(
                    "NOVA started a local-only "
                    "ambient-vision session."
                ),
            )

        interval = max(
            5.0,
            self.configuration
            .capture_interval_seconds,
        )

        maximum_seconds = (
            self.configuration
            .maximum_vision_session_minutes
            * 60
        )

        while not stop_event.is_set():
            runtime = self.state.snapshot()

            if (
                self.configuration.vision_mode
                == VisionMode.TEMPORARY_SESSION
            ):
                session_started = (
                    runtime.vision_session_started_at
                )

                if session_started is not None:
                    elapsed = (
                        datetime.now(timezone.utc)
                        - session_started
                    ).total_seconds()

                    if elapsed >= maximum_seconds:
                        self.state.stop_vision()

                        self._record_vision_event(
                            event_type=(
                                GuardianEventType
                                .VISION_SESSION_EXPIRED
                            ),
                            severity=(
                                GuardianEventSeverity.INFO
                            ),
                            title="Vision session expired",
                            message=(
                                "The temporary local-vision "
                                "session ended automatically."
                            ),
                        )
                        break

            await self.analyze_once(
                force=False
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=interval,
                )

            except TimeoutError:
                continue

        if (
            started_vision_here
            and self.state.snapshot().vision_active
        ):
            self.state.stop_vision()

            self._record_vision_event(
                event_type=(
                    GuardianEventType.VISION_STOPPED
                ),
                severity=(
                    GuardianEventSeverity.INFO
                ),
                title="Local vision stopped",
                message=(
                    "NOVA stopped the local "
                    "ambient-vision session."
                ),
            )

    def last_result(
        self,
    ) -> LocalVisionResult | None:
        """Return the latest successful local analysis."""

        return self._last_result