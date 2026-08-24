from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .recorder import LocalWaveRecorder


class LocalMicrophoneCapture:
    """Attach explicit local mic input to the shared LocalWaveRecorder.

    Nothing activates until start() is called. A stream factory can be injected
    so the adapter is testable without microphone hardware.
    """

    def __init__(
        self,
        recorder: LocalWaveRecorder,
        *,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.recorder = recorder
        self._stream_factory = stream_factory
        self._stream: Any = None

    @property
    def active(self) -> bool:
        return self._stream is not None and self.recorder.active

    def start(self) -> None:
        if self.active:
            raise RuntimeError("Microphone capture is already active.")

        if self._stream_factory is None:
            import sounddevice as sd  # type: ignore
            factory = sd.RawInputStream
        else:
            factory = self._stream_factory

        self.recorder.start()
        try:
            self._stream = factory(
                samplerate=self.recorder.sample_rate,
                channels=self.recorder.channels,
                dtype="int16",
                blocksize=0,
                callback=self._callback,
            )
            self._stream.start()
        except Exception:
            self._stream = None
            self.recorder.close_safely()
            raise

    def _callback(self, indata, frames, time_info, status) -> None:
        _ = frames, time_info, status
        self.recorder.write_pcm(bytes(indata))

    def stop(self) -> None:
        stream = self._stream
        self._stream = None

        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

        self.recorder.close_safely()
