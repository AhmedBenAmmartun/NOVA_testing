from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import threading
import wave
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, cli, inference

load_dotenv(".env.local")
load_dotenv(".env")

PROJECT_ROOT = Path(__file__).resolve().parent

# Obsidian is the primary home for class sessions.
# Prefer OBSIDIAN_VAULT_PATH from .env; fall back to Ahmed's current NOVA Vault.
DEFAULT_OBSIDIAN_VAULT = Path.home() / "NOVA Vault"
OBSIDIAN_VAULT = Path(
    os.getenv("OBSIDIAN_VAULT_PATH", str(DEFAULT_OBSIDIAN_VAULT))
).expanduser()

SESSIONS_ROOT = OBSIDIAN_VAULT / "Classes" / "_Class Capture"
SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("nova.class_capture")
server = AgentServer()


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso_now() -> str:
    return now_local().isoformat(timespec="seconds")


class LocalAudioRecorder:
    """Optional local WAV backup using sounddevice.

    Recording failure never prevents transcript capture from starting.
    """

    def __init__(self, wav_path: Path, sample_rate: int = 16000) -> None:
        self.wav_path = wav_path
        self.sample_rate = sample_rate
        self._wave: wave.Wave_write | None = None
        self._stream: Any = None
        self._lock = threading.Lock()
        self.available = False
        self.error: str | None = None

    def start(self) -> None:
        try:
            import sounddevice as sd  # type: ignore

            self._wave = wave.open(str(self.wav_path), "wb")
            self._wave.setnchannels(1)
            self._wave.setsampwidth(2)  # int16
            self._wave.setframerate(self.sample_rate)

            def callback(indata, frames, time_info, status) -> None:
                if status:
                    logger.warning("audio recorder status: %s", status)
                payload = bytes(indata)
                with self._lock:
                    if self._wave is not None:
                        self._wave.writeframesraw(payload)

            self._stream = sd.RawInputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                callback=callback,
                blocksize=0,
            )
            self._stream.start()
            self.available = True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            logger.exception("local audio backup could not start")
            self.stop()

    def stop(self) -> None:
        try:
            if self._stream is not None:
                try:
                    self._stream.stop()
                finally:
                    self._stream.close()
        except Exception:
            logger.exception("audio stream shutdown failed")
        finally:
            self._stream = None

        with self._lock:
            if self._wave is not None:
                try:
                    self._wave.close()
                except Exception:
                    logger.exception("wav close failed")
                finally:
                    self._wave = None


class ClassSessionStore:
    def __init__(self) -> None:
        started = now_local()
        self.session_id = started.strftime("%Y-%m-%d_%H%M%S")
        day_folder = SESSIONS_ROOT / started.strftime("%Y-%m-%d")
        day_folder.mkdir(parents=True, exist_ok=True)
        self.folder = day_folder / self.session_id
        suffix = 1
        while self.folder.exists():
            self.folder = SESSIONS_ROOT / f"{self.session_id}_{suffix}"
            suffix += 1

        self.folder.mkdir(parents=True, exist_ok=False)
        self.transcript_path = self.folder / "transcript.md"
        self.audio_path = self.folder / "audio.wav"
        self.meta_path = self.folder / "session.json"

        self.chunk_count = 0
        self.errors: list[str] = []
        self.started_at = iso_now()
        self.ended_at: str | None = None
        self.status = "recording"

        self._transcript = self.transcript_path.open(
            "a", encoding="utf-8", buffering=1
        )
        self._transcript.write(
            "---\n"
            f"session_id: {self.folder.name}\n"
            f"started_at: {self.started_at}\n"
            "type: nova-class-capture\n"
            "status: recording\n"
            "---\n\n"
            f"# Class Session — {self.folder.name}\n\n"
            "## Live Transcript\n\n"
        )
        self._transcript.flush()
        self.audio = LocalAudioRecorder(self.audio_path)
        self.audio.start()
        if self.audio.error:
            self.errors.append(f"audio_backup: {self.audio.error}")

        self.write_metadata()

    def append_final(self, text: str, speaker_id: str | None = None) -> None:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return

        stamp = now_local().strftime("%H:%M:%S")
        speaker = f"[speaker={speaker_id}] " if speaker_id else ""
        self._transcript.write(f"[{stamp}] {speaker}{cleaned}\n")
        self._transcript.flush()
        try:
            os.fsync(self._transcript.fileno())
        except OSError:
            pass

        self.chunk_count += 1
        self.write_metadata()

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.write_metadata()

    def write_metadata(self) -> None:
        payload = {
            "session_id": self.folder.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "transcript_file": str(self.transcript_path),
            "audio_file": str(self.audio_path) if self.audio.available else None,
            "audio_backup_active": self.audio.available,
            "transcript_chunk_count": self.chunk_count,
            "status": self.status,
            "errors": self.errors,
        }
        temp = self.meta_path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(self.meta_path)

    def close(self, status: str = "completed") -> None:
        if self.status not in {"completed", "stopped", "error"}:
            self.status = status
        self.ended_at = iso_now()
        self.audio.stop()
        try:
            self._transcript.flush()
            try:
                os.fsync(self._transcript.fileno())
            except OSError:
                pass
        finally:
            self._transcript.close()
        self.write_metadata()


@server.rtc_session(agent_name="nova-class-capture")
async def class_capture(ctx: JobContext):
    store = ClassSessionStore()

    print()
    print("=" * 66)
    print("NOVA CLASS CAPTURE")
    print("SILENT MODE:       YES")
    print("TRANSCRIPT:        " + str(store.transcript_path))
    if store.audio.available:
        print("LOCAL AUDIO BACKUP:" + str(store.audio_path))
    else:
        print("LOCAL AUDIO BACKUP: UNAVAILABLE (transcript still active)")
        if store.audio.error:
            print("AUDIO ERROR:       " + store.audio.error)
    print("Press Ctrl+C to end the class.")
    print("=" * 66)
    print()

    # Official LiveKit STT-only pattern: no LLM and no TTS.
    session = AgentSession(
        stt=inference.STT(model="deepgram/nova-3-general"),
    )

    @session.on("user_input_transcribed")
    def on_transcript(event):
        if not event.is_final:
            return

        speaker_id = getattr(event, "speaker_id", None)
        store.append_final(event.transcript, speaker_id=speaker_id)
        print(f"[saved #{store.chunk_count}] {event.transcript}")

    @session.on("error")
    def on_error(event):
        message = f"{getattr(event, 'source', 'session')}: {getattr(event, 'error', event)}"
        store.add_error(message)
        logger.error("class capture session error: %s", message)

    async def shutdown() -> None:
        store.close("completed")
        print()
        print("Class capture saved.")
        print("Session folder:", store.folder)
        print("Transcript chunks:", store.chunk_count)
        print()

    ctx.add_shutdown_callback(shutdown)

    await session.start(
        agent=Agent(
            instructions=(
                "Transcribe speech only. Do not answer, speak, call tools, "
                "summarize, or interact with the speaker."
            )
        ),
        room=ctx.room,
    )

    # Console mode room connectivity/session lifecycle is managed by LiveKit.
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
