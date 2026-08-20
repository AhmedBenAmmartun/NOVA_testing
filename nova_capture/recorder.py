from __future__ import annotations

import wave
from pathlib import Path
from typing import Any


class LocalWaveRecorder:
    """Small local PCM/WAV writer.

    This is the storage primitive only. V1 Foundation does not attach it to the
    user's microphone or LiveKit automatically.
    """

    def __init__(
        self,
        path: Path,
        *,
        sample_rate: int = 48_000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> None:
        self.path = path
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_width = int(sample_width)
        self._wave: wave.Wave_write | None = None
        self._paused = False
        self._frames_written = 0

    @property
    def active(self) -> bool:
        return self._wave is not None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def frames_written(self) -> int:
        return self._frames_written

    def start(self) -> None:
        if self._wave is not None:
            raise RuntimeError("Recorder is already active.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = wave.open(str(self.path), "wb")
        handle.setnchannels(self.channels)
        handle.setsampwidth(self.sample_width)
        handle.setframerate(self.sample_rate)
        self._wave = handle
        self._paused = False
        self._frames_written = 0

    def pause(self) -> None:
        if self._wave is None:
            raise RuntimeError("Recorder is not active.")
        self._paused = True

    def resume(self) -> None:
        if self._wave is None:
            raise RuntimeError("Recorder is not active.")
        self._paused = False

    def write_pcm(self, data: bytes | bytearray | memoryview) -> None:
        if self._wave is None:
            raise RuntimeError("Recorder is not active.")
        if self._paused:
            return
        payload = bytes(data)
        if not payload:
            return
        self._wave.writeframesraw(payload)
        frame_bytes = self.channels * self.sample_width
        self._frames_written += len(payload) // frame_bytes

    def write_audio_frame(self, frame: Any) -> None:
        data = getattr(frame, "data", None)
        if data is None:
            raise TypeError("Audio frame does not expose PCM data.")
        self.write_pcm(data)

    def stop(self) -> Path:
        if self._wave is None:
            raise RuntimeError("Recorder is not active.")
        self._wave.close()
        self._wave = None
        self._paused = False
        return self.path

    def close_safely(self) -> None:
        if self._wave is not None:
            self._wave.close()
            self._wave = None
            self._paused = False
