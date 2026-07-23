"""Local wake-word detector for NOVA.

Temporary wake phrase: "Hey Jarvis"

This test:
- Runs entirely locally.
- Uses the default Windows microphone.
- Does not launch agent.py.
- Does not connect to Gemini.
- Does not activate Guardian vision.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from typing import Any

import numpy as np
import pyaudiowpatch as pyaudio
from openwakeword.model import Model
from openwakeword.utils import download_models


SAMPLE_RATE = 16_000
CHANNELS = 1
CHUNK_SIZE = 1_280

WAKE_WORD_MODEL = "hey_jarvis"
DETECTION_THRESHOLD = 0.50
DETECTION_COOLDOWN_SECONDS = 2.0


def print_input_devices(
    audio: pyaudio.PyAudio,
) -> None:
    """Print all available microphone input devices."""

    print("\nAvailable microphone devices:")

    found_microphone = False

    for device_index in range(
        audio.get_device_count()
    ):
        device = audio.get_device_info_by_index(
            device_index
        )

        input_channels = int(
            device.get(
                "maxInputChannels",
                0,
            )
        )

        if input_channels < 1:
            continue

        found_microphone = True

        device_name = str(
            device.get(
                "name",
                "Unknown microphone",
            )
        )

        print(
            f"  [{device_index}] {device_name}"
        )

    if not found_microphone:
        print(
            "  No microphone input devices were found."
        )


def get_default_microphone(
    audio: pyaudio.PyAudio,
) -> dict[str, Any]:
    """Return the default Windows microphone information."""

    try:
        raw_device = (
            audio.get_default_input_device_info()
        )

    except OSError as error:
        raise RuntimeError(
            "Windows does not have a default "
            "microphone configured."
        ) from error

    device = dict(raw_device)

    input_channels = int(
        device.get(
            "maxInputChannels",
            0,
        )
    )

    if input_channels < 1:
        raise RuntimeError(
            "The default Windows audio device "
            "does not support microphone input."
        )

    return device


def load_wake_word_model() -> Model:
    """Download and load the temporary Hey Jarvis model."""

    print(
        "\nChecking the wake-word model files..."
    )

    download_models(
        model_names=[
            WAKE_WORD_MODEL,
        ]
    )

    print(
        "Loading the local wake-word model..."
    )

    return Model(
        wakeword_models=[
            WAKE_WORD_MODEL,
        ],
        inference_framework="onnx",
    )


def convert_score_to_float(
    value: Any,
) -> float:
    """Convert an openWakeWord score into a regular float."""

    if isinstance(
        value,
        np.ndarray,
    ):
        if value.size == 0:
            return 0.0

        return float(
            value.reshape(-1)[-1]
        )

    if isinstance(
        value,
        (list, tuple),
    ):
        if not value:
            return 0.0

        return convert_score_to_float(
            value[-1]
        )

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return 0.0


def extract_prediction_mapping(
    prediction: object,
) -> Mapping[str, Any]:
    """
    Extract the prediction dictionary.

    Depending on the openWakeWord configuration, Model.predict()
    may return either:

    - A prediction dictionary.
    - A tuple containing the prediction dictionary and features.
    """

    prediction_value = prediction

    if isinstance(
        prediction_value,
        tuple,
    ):
        if not prediction_value:
            return {}

        prediction_value = (
            prediction_value[0]
        )

    if isinstance(
        prediction_value,
        Mapping,
    ):
        return {
            str(model_name): score
            for model_name, score
            in prediction_value.items()
        }

    return {}


def get_prediction_score(
    prediction: object,
) -> tuple[str, float]:
    """Return the model name and highest prediction score."""

    prediction_mapping = (
        extract_prediction_mapping(
            prediction
        )
    )

    if not prediction_mapping:
        return WAKE_WORD_MODEL, 0.0

    converted_scores = [
        (
            str(model_name),
            convert_score_to_float(
                raw_score
            ),
        )
        for model_name, raw_score
        in prediction_mapping.items()
    ]

    if not converted_scores:
        return WAKE_WORD_MODEL, 0.0

    return max(
        converted_scores,
        key=lambda item: item[1],
    )


def run_listener() -> int:
    """Listen continuously for the temporary wake phrase."""

    audio = pyaudio.PyAudio()
    stream: Any | None = None

    try:
        print_input_devices(
            audio
        )

        microphone = get_default_microphone(
            audio
        )

        microphone_index = int(
            microphone["index"]
        )

        microphone_name = str(
            microphone.get(
                "name",
                "Unknown microphone",
            )
        )

        print(
            "\nUsing microphone "
            f"[{microphone_index}]: "
            f"{microphone_name}"
        )

        model = load_wake_word_model()

        stream = audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=(
                microphone_index
            ),
            frames_per_buffer=(
                CHUNK_SIZE
            ),
        )

        print(
            "\nNOVA wake-word test is ready."
        )
        print(
            'Say: "Hey Jarvis"'
        )
        print(
            "Press Ctrl+C to stop.\n"
        )

        last_detection_time = 0.0

        while True:
            audio_bytes = stream.read(
                CHUNK_SIZE,
                exception_on_overflow=False,
            )

            audio_frame = np.frombuffer(
                audio_bytes,
                dtype=np.int16,
            )

            prediction = model.predict(
                audio_frame
            )

            model_name, score = (
                get_prediction_score(
                    prediction
                )
            )

            current_time = (
                time.monotonic()
            )

            cooldown_finished = (
                current_time
                - last_detection_time
                >= DETECTION_COOLDOWN_SECONDS
            )

            if (
                score
                >= DETECTION_THRESHOLD
                and cooldown_finished
            ):
                last_detection_time = (
                    current_time
                )

                print(
                    "\n"
                    "========================================"
                )
                print(
                    "WAKE WORD DETECTED"
                )
                print(
                    f"Model: {model_name}"
                )
                print(
                    f"Score: {score:.3f}"
                )
                print(
                    "========================================"
                    "\n"
                )

            elif score >= 0.10:
                print(
                    f"Listening score: {score:.3f}",
                    end="\r",
                    flush=True,
                )

    except KeyboardInterrupt:
        print(
            "\nStopping NOVA wake-word listener."
        )

        return 0

    except Exception as error:
        print(
            "\nWake-word listener failed:",
            type(error).__name__,
            error,
        )

        return 1

    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()

            except Exception:
                pass

        audio.terminate()


def main() -> int:
    """Run the standalone wake-word test."""

    return run_listener()


if __name__ == "__main__":
    sys.exit(
        main()
    )