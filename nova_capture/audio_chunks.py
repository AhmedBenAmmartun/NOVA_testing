"""Durable chunked class audio.

The class recording is NOVA's source of truth. Everything else in Class
Capture -- STT, notes, questions, speaker roles, post-processing -- is derived
from it and can be regenerated, so nothing downstream may be allowed to
interrupt or corrupt it.

A single growing ``audio.wav`` could not offer that: its RIFF header is only
correct once the file is closed, so an unexpected process death left a lecture
in a file no player would open, and there was no record of how much audio was
supposed to exist. This module writes short, individually valid WAV chunks
instead::

    capture -> NNNNNN.wav.tmp -> flush -> fsync -> close -> atomic rename
            -> append manifest record

Every completed chunk is a finished, playable WAV before the next one starts,
so a crash can lose at most the current chunk, and ``manifest.jsonl`` records
what should exist so a missing or truncated chunk is *detectable* rather than
silent.

Timestamps come from frames actually written, never from the wall clock, so
chunk boundaries stay sample-exact across a three-hour lecture.
"""

from __future__ import annotations

import json
import os
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


#: Default rolling chunk length. Short enough that an unexpected process death
#: can only lose a few seconds of a lecture, long enough that a three-hour
#: sitting stays a few hundred files rather than tens of thousands.
DEFAULT_CHUNK_SECONDS = 20.0

MANIFEST_NAME = "manifest.jsonl"
RECORDER_STATE_NAME = "recorder.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def chunk_filename(sequence: int) -> str:
    return f"{int(sequence):06d}.wav"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(slots=True)
class ChunkRecord:
    sequence: int
    file: str
    start_seconds: float
    end_seconds: float
    frames: int
    bytes: int
    sample_rate: int
    channels: int
    sample_width: int
    status: str = "complete"
    started_at: str = ""
    completed_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "file": self.file,
            "start_seconds": round(self.start_seconds, 4),
            "end_seconds": round(self.end_seconds, 4),
            "frames": self.frames,
            "bytes": self.bytes,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "sample_width": self.sample_width,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class ChunkedAudioRecorder:
    """Rolling, crash-safe WAV chunk writer with an append-only manifest.

    Deliberately API-compatible with
    :class:`~nova_capture.recorder.LocalWaveRecorder`
    (``sample_rate``/``channels``/``start``/``write_pcm``/``close_safely``) so
    it can be handed straight to
    :class:`~nova_capture.microphone.LocalMicrophoneCapture` without changing
    the microphone adapter.

    ``write_pcm`` runs on the sounddevice callback thread, so it holds a short
    lock and never performs model, network, or otherwise slow work.
    """

    def __init__(
        self,
        audio_dir: Path,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        sample_width: int = 2,
        chunk_seconds: float = DEFAULT_CHUNK_SECONDS,
        fsync: bool = True,
        resume: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.audio_dir = Path(audio_dir)
        self.resume_from_manifest = bool(resume)
        # Injectable so the device-death safety rule, which is defined in terms
        # of elapsed time, can be tested without waiting in real time.
        self._clock = clock
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_width = int(sample_width)
        self.chunk_seconds = max(1.0, float(chunk_seconds))
        self.fsync = bool(fsync)

        self.manifest_path = self.audio_dir / MANIFEST_NAME
        self.state_path = self.audio_dir / RECORDER_STATE_NAME

        self._frame_bytes = max(1, self.channels * self.sample_width)
        self._chunk_frames = max(1, int(self.chunk_seconds * self.sample_rate))

        self._lock = threading.Lock()
        self._wave: wave.Wave_write | None = None
        self._handle: Any = None
        self._sequence = 0
        self._chunk_frames_written = 0
        self._total_frames = 0
        self._chunk_started_at = ""
        self._active = False
        self._paused = False
        self._records: list[ChunkRecord] = []
        self._last_write_monotonic: float | None = None
        self._last_error: str | None = None
        #: Seconds of wall clock the microphone was NOT delivering audio. The
        #: recording timeline has to account for them or every chunk after a
        #: device stall would claim an earlier position than it really holds,
        #: and the transcript would stop lining up with the audio.
        self._gap_seconds = 0.0
        self._gaps: list[dict[str, Any]] = []

    # --- introspection ---------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def frames_written(self) -> int:
        return self._total_frames

    @property
    def recorded_seconds(self) -> float:
        """Seconds of audio actually captured (excludes device gaps)."""
        return self._total_frames / float(self.sample_rate)

    @property
    def timeline_seconds(self) -> float:
        """Position in the session timeline, including any device gaps."""
        return self.recorded_seconds + self._gap_seconds

    @property
    def gap_seconds(self) -> float:
        return self._gap_seconds

    def gaps(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._gaps)

    @property
    def chunk_count(self) -> int:
        return len(self._records)

    @property
    def last_sequence(self) -> int:
        return self._records[-1].sequence if self._records else 0

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_write_age_seconds(self) -> float | None:
        if self._last_write_monotonic is None:
            return None
        return max(0.0, self._clock() - self._last_write_monotonic)

    def records(self) -> tuple[ChunkRecord, ...]:
        return tuple(self._records)

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self._active:
            raise RuntimeError("Chunked audio recorder is already active.")
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.touch(exist_ok=True)
        if self.resume_from_manifest:
            self._resume_from_manifest()
        self._active = True
        self._paused = False
        # Start the liveness clock now. A device that opens but never delivers
        # a single callback must trip the silence check like any other stall.
        self._last_write_monotonic = self._clock()
        self._open_next_chunk()

    def _resume_from_manifest(self) -> None:
        """Continue an interrupted recording instead of overwriting it.

        A restarted recorder process must never reuse sequence 1 -- that would
        silently replace the first chunk of the lecture. Numbering and the
        session clock both continue from what the manifest already claims.
        """
        records = read_manifest(self.audio_dir)
        if not records:
            return
        chunks = [item for item in records if item.get("kind") != "gap"]
        gaps = [item for item in records if item.get("kind") == "gap"]
        self._gap_seconds = sum(float(item.get("seconds", 0.0) or 0.0) for item in gaps)
        self._gaps = list(gaps)
        if not chunks:
            return
        last = max(chunks, key=lambda item: int(item.get("sequence", 0) or 0))
        self._sequence = int(last.get("sequence", 0) or 0)
        self._total_frames = sum(int(item.get("frames", 0) or 0) for item in chunks)

    def pause(self) -> None:
        if not self._active:
            raise RuntimeError("Chunked audio recorder is not active.")
        self._paused = True

    def resume(self) -> None:
        if not self._active:
            raise RuntimeError("Chunked audio recorder is not active.")
        self._paused = False

    def write_pcm(self, data: bytes | bytearray | memoryview) -> None:
        if not self._active or self._paused:
            return
        payload = bytes(data)
        if not payload:
            return

        with self._lock:
            if self._wave is None:
                return

            offset = 0
            total = len(payload)
            while offset < total:
                # Split at the chunk boundary rather than letting one oversized
                # write define the chunk length. Device callbacks are normally
                # far smaller than a chunk, but a chunk's duration must depend
                # on chunk_seconds alone -- integrity checks and manifest
                # timestamps are built on that invariant.
                room_frames = max(0, self._chunk_frames - self._chunk_frames_written)
                if room_frames == 0:
                    self._roll_locked()
                    continue

                take = min(total - offset, room_frames * self._frame_bytes)
                piece = payload[offset : offset + take]
                try:
                    assert self._wave is not None
                    self._wave.writeframesraw(piece)
                except Exception as error:  # pragma: no cover - disk/device failure
                    self._last_error = f"{type(error).__name__}: {error}"
                    raise

                frames = len(piece) // self._frame_bytes
                self._chunk_frames_written += frames
                self._total_frames += frames
                offset += take

                if self._chunk_frames_written >= self._chunk_frames:
                    self._roll_locked()

            self._last_write_monotonic = self._clock()

    def write_audio_frame(self, frame: Any) -> None:
        data = getattr(frame, "data", None)
        if data is None:
            raise TypeError("Audio frame does not expose PCM data.")
        self.write_pcm(data)

    def stop(self) -> Path:
        """Finalize the current chunk and stop accepting audio."""
        with self._lock:
            if self._active:
                self._close_current_locked()
            self._active = False
            self._paused = False
        return self.audio_dir

    def close_safely(self) -> None:
        try:
            self.stop()
        except Exception:  # pragma: no cover - best-effort shutdown
            self._active = False

    # --- durable chunk mechanics ----------------------------------------

    def _open_next_chunk(self) -> None:
        self._sequence += 1
        self._chunk_frames_written = 0
        self._chunk_started_at = _utc_now_iso()
        temporary = self.audio_dir / f"{chunk_filename(self._sequence)}.tmp"
        handle = open(temporary, "wb")
        writer = wave.open(handle, "wb")
        writer.setnchannels(self.channels)
        writer.setsampwidth(self.sample_width)
        writer.setframerate(self.sample_rate)
        self._handle = handle
        self._wave = writer

    def _close_current_locked(self) -> ChunkRecord | None:
        writer, handle = self._wave, self._handle
        self._wave, self._handle = None, None
        if writer is None or handle is None:
            return None

        frames = self._chunk_frames_written
        temporary = self.audio_dir / f"{chunk_filename(self._sequence)}.tmp"
        final_path = self.audio_dir / chunk_filename(self._sequence)

        # wave.close() rewrites the RIFF/data sizes, so the header is only
        # correct once it returns. fsync then guarantees the bytes reached the
        # disk before the rename publishes the chunk as complete.
        writer.close()
        try:
            if self.fsync and not handle.closed:
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, ValueError):  # pragma: no cover - platform dependent
            pass
        finally:
            if not handle.closed:
                handle.close()

        if frames <= 0:
            # Nothing was captured into this chunk; publishing an empty file
            # would create a phantom manifest entry.
            temporary.unlink(missing_ok=True)
            return None

        temporary.replace(final_path)

        end_seconds = self.timeline_seconds
        start_seconds = end_seconds - frames / float(self.sample_rate)
        record = ChunkRecord(
            sequence=self._sequence,
            file=final_path.name,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            frames=frames,
            bytes=final_path.stat().st_size,
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
            status="complete",
            started_at=self._chunk_started_at,
            completed_at=_utc_now_iso(),
        )
        self._append_manifest(record)
        self._records.append(record)
        return record

    def note_gap(self, seconds: float, *, reason: str) -> dict[str, Any]:
        """Record wall-clock time the microphone was not delivering audio.

        Written into the manifest as a first-class record so the recording
        stays honest: the files hold only real audio, and the timeline still
        says where that audio sits relative to the class.
        """
        span = max(0.0, float(seconds))
        with self._lock:
            start = self.timeline_seconds
            self._gap_seconds += span
            record = {
                "kind": "gap",
                "after_sequence": self._sequence,
                "start_seconds": round(start, 4),
                "end_seconds": round(start + span, 4),
                "seconds": round(span, 4),
                "reason": str(reason),
                "status": "gap",
                "at": _utc_now_iso(),
            }
            self._gaps.append(record)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False))
            handle.write("\n")
            if self.fsync:
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                except (OSError, ValueError):  # pragma: no cover
                    pass
        return record

    def _roll_locked(self) -> None:
        self._close_current_locked()
        self._open_next_chunk()

    def _append_manifest(self, record: ChunkRecord) -> None:
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.as_dict(), ensure_ascii=False))
            handle.write("\n")
            if self.fsync:
                try:
                    handle.flush()
                    os.fsync(handle.fileno())
                except (OSError, ValueError):  # pragma: no cover
                    pass

    # --- health ----------------------------------------------------------

    def state(self, *, status: str, **extra: Any) -> dict[str, Any]:
        age = self.last_write_age_seconds
        payload: dict[str, Any] = {
            "status": status,
            "pid": os.getpid(),
            "updated_at": _utc_now_iso(),
            "audio_dir": str(self.audio_dir),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "chunk_seconds": self.chunk_seconds,
            "chunks": self.chunk_count,
            "last_chunk": self.last_sequence,
            "recorded_seconds": round(self.recorded_seconds, 3),
            "timeline_seconds": round(self.timeline_seconds, 3),
            "gap_seconds": round(self._gap_seconds, 3),
            "device_gaps": len(self._gaps),
            "last_write_age_seconds": None if age is None else round(age, 3),
            "error": self._last_error,
        }
        payload.update(extra)
        return payload

    def write_state(self, *, status: str, **extra: Any) -> dict[str, Any]:
        """Persist a small recorder heartbeat readable by any other process."""
        payload = self.state(status=status, **extra)
        atomic_write_json(self.state_path, payload)
        return payload


# --- integrity ------------------------------------------------------------


@dataclass(slots=True)
class AudioIntegrityReport:
    """What the persisted chunks say about a session's recording."""

    chunk_count: int = 0
    recorded_seconds: float = 0.0
    manifest_entries: int = 0
    missing_files: list[str] = field(default_factory=list)
    unlisted_files: list[str] = field(default_factory=list)
    incomplete_files: list[str] = field(default_factory=list)
    #: The chunk currently being written. Normal during class, a problem after.
    in_progress_files: list[str] = field(default_factory=list)
    sequence_gaps: list[int] = field(default_factory=list)
    timestamp_gaps: list[dict[str, float]] = field(default_factory=list)
    truncated_files: list[str] = field(default_factory=list)
    malformed_manifest_lines: int = 0
    #: Stretches where the microphone was not delivering audio. Recorded on
    #: purpose, so they are NOT an integrity failure -- they are the honest
    #: answer to "why is the audio shorter than the class?".
    device_gaps: list[dict[str, Any]] = field(default_factory=list)
    gap_seconds: float = 0.0

    @property
    def timeline_seconds(self) -> float:
        return self.recorded_seconds + self.gap_seconds

    @property
    def healthy(self) -> bool:
        return not (
            self.missing_files
            or self.incomplete_files
            or self.sequence_gaps
            or self.timestamp_gaps
            or self.truncated_files
            or self.malformed_manifest_lines
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "chunk_count": self.chunk_count,
            "recorded_seconds": round(self.recorded_seconds, 3),
            "timeline_seconds": round(self.timeline_seconds, 3),
            "gap_seconds": round(self.gap_seconds, 3),
            "device_gaps": list(self.device_gaps),
            "manifest_entries": self.manifest_entries,
            "missing_files": list(self.missing_files),
            "unlisted_files": list(self.unlisted_files),
            "incomplete_files": list(self.incomplete_files),
            "in_progress_files": list(self.in_progress_files),
            "sequence_gaps": list(self.sequence_gaps),
            "timestamp_gaps": list(self.timestamp_gaps),
            "truncated_files": list(self.truncated_files),
            "malformed_manifest_lines": self.malformed_manifest_lines,
        }


def read_manifest(audio_dir: Path) -> list[dict[str, Any]]:
    path = Path(audio_dir) / MANIFEST_NAME
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def scan_audio_dir(
    audio_dir: Path,
    *,
    gap_tolerance_seconds: float = 0.25,
    verify_sizes: bool = True,
    recording: bool = False,
) -> AudioIntegrityReport:
    """Report what is provably on disk for a session's audio.

    This is the check that makes a lost chunk *detectable*. It is deliberately
    read-only: it never repairs, deletes, or rewrites a recording.

    ``recording=True`` says a recorder is actively writing right now, so the
    single ``.tmp`` immediately after the last manifest entry is the chunk in
    flight rather than damage. The default is strict: once nothing is
    recording, any ``.tmp`` is an interrupted chunk.
    """

    audio_dir = Path(audio_dir)
    report = AudioIntegrityReport()
    if not audio_dir.is_dir():
        return report

    manifest_path = audio_dir / MANIFEST_NAME
    try:
        raw_lines = [
            line
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except OSError:
        raw_lines = []

    records: list[dict[str, Any]] = []
    for line in raw_lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            report.malformed_manifest_lines += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            report.malformed_manifest_lines += 1

    report.manifest_entries = len(records)

    # Device gaps are deliberate, ordered markers -- not chunks. Pull them out
    # first so they neither look like a missing file nor trigger a false
    # timestamp gap across the stretch they already explain.
    gap_records = [item for item in records if item.get("kind") == "gap"]
    records = [item for item in records if item.get("kind") != "gap"]
    report.device_gaps = [
        {
            "start_seconds": float(item.get("start_seconds", 0.0) or 0.0),
            "end_seconds": float(item.get("end_seconds", 0.0) or 0.0),
            "seconds": float(item.get("seconds", 0.0) or 0.0),
            "reason": str(item.get("reason", "unknown")),
        }
        for item in gap_records
    ]
    report.gap_seconds = sum(item["seconds"] for item in report.device_gaps)
    gap_edges = {round(item["end_seconds"], 3) for item in report.device_gaps}

    listed: set[str] = set()
    previous_end: float | None = None
    previous_sequence: int | None = None

    for record in sorted(records, key=lambda item: int(item.get("sequence", 0))):
        name = str(record.get("file", ""))
        listed.add(name)
        path = audio_dir / name
        if not path.is_file():
            report.missing_files.append(name)
            continue

        report.chunk_count += 1
        frames = int(record.get("frames", 0) or 0)
        report.recorded_seconds += frames / float(record.get("sample_rate") or 16_000)

        if verify_sizes:
            expected = int(record.get("bytes", 0) or 0)
            actual = path.stat().st_size
            if expected and actual < expected:
                report.truncated_files.append(name)

        sequence = int(record.get("sequence", 0) or 0)
        if previous_sequence is not None:
            for missing in range(previous_sequence + 1, sequence):
                report.sequence_gaps.append(missing)
        previous_sequence = sequence

        start = float(record.get("start_seconds", 0.0) or 0.0)
        end = float(record.get("end_seconds", 0.0) or 0.0)
        if (
            previous_end is not None
            and start - previous_end > gap_tolerance_seconds
            # A jump that lands exactly on the far side of a recorded device
            # gap is already accounted for; only unexplained jumps are damage.
            and round(start, 3) not in gap_edges
        ):
            report.timestamp_gaps.append(
                {
                    "after_seconds": round(previous_end, 3),
                    "before_seconds": round(start, 3),
                }
            )
        previous_end = end

    for path in sorted(audio_dir.glob("*.wav")):
        if path.name not in listed:
            report.unlisted_files.append(path.name)
    expected_in_progress = (
        f"{chunk_filename((previous_sequence or 0) + 1)}.tmp" if recording else None
    )
    for path in sorted(audio_dir.glob("*.wav.tmp")):
        if expected_in_progress is not None and path.name == expected_in_progress:
            report.in_progress_files.append(path.name)
        else:
            report.incomplete_files.append(path.name)

    return report
