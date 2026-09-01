"""Which real-time speech pipeline Class Capture uses, and why.

NOVA's verified transcription path is LiveKit Agents + LiveKit Inference
(Deepgram ``nova-3-general``). It works in real lectures and it stays the
default. This module exists so that fact is a *choice* rather than a hard-coded
assumption: ``NOVA_CLASS_PIPELINE`` selects an engine, every engine feeds the
same downstream data model (TranscriptJournal, SpeakerRoleTracker,
QuestionJournal, LiveQAManager, live notes), and switching back is a config
change rather than a rewrite.

The Pipecat engine here is a **pilot**. It is written against Pipecat 1.8.x's
documented API and has *not* been executed against a real microphone on this
runtime -- ``pipecat-ai`` is deliberately not installed, and
:func:`describe_pipecat_support` reports exactly what is missing rather than
guessing. Nothing selects it unless the user asks for it.

Note the deeper point: adopting Pipecat is no longer the way to make class
recording durable. ``nova_capture.recorder_process`` already owns the
microphone in its own process, so audio survives whatever the transcription
engine does. Pipecat would buy pipeline flexibility, not reliability.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass, field
from typing import Any


LIVEKIT = "livekit"
PIPECAT = "pipecat"

#: Deepgram settings NOVA's transcription must keep whichever engine runs.
#: These are the values verified in real CEN4065/COP3710 lectures.
CLASS_STT_MODEL = "deepgram/nova-3-general"
PIPECAT_STT_MODEL = "nova-3-general"


class TranscriptionEngineUnavailable(RuntimeError):
    """Raised when a requested engine cannot run on this machine."""


@dataclass(slots=True)
class TranscriptionEvent:
    """One finalized (or interim) utterance, engine-independent."""

    text: str
    is_final: bool = True
    speaker_id: str | None = None


@dataclass(slots=True)
class PipelineSelection:
    requested: str
    engine: str
    available: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def fell_back(self) -> bool:
        return self.requested != self.engine

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "engine": self.engine,
            "available": self.available,
            "fell_back": self.fell_back,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _module_present(name: str) -> bool:
    """True when ``name`` is importable. find_spec raises on a missing parent."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def describe_pipecat_support() -> dict[str, Any]:
    """Report -- from this machine, not from assumptions -- what Pipecat needs.

    Never reads or reports the value of any credential; only whether the name
    is set at all.
    """

    modules = {
        name: _module_present(name)
        for name in (
            "pipecat",
            "pipecat.pipeline.pipeline",
            "pipecat.services.deepgram.stt",
            "pipecat.transports.local.audio",
            "pyaudio",
        )
    }
    missing = [name for name, present in modules.items() if not present]
    has_key = bool(os.getenv("DEEPGRAM_API_KEY", "").strip())

    blockers: list[str] = []
    if missing:
        blockers.append("missing modules: " + ", ".join(missing))
    if not has_key:
        blockers.append(
            "DEEPGRAM_API_KEY is not configured (NOVA reaches Deepgram through "
            "LiveKit Inference today, so no direct Deepgram key exists)"
        )

    return {
        "modules": modules,
        "deepgram_api_key_configured": has_key,
        "blockers": blockers,
        "usable": not blockers,
    }


def resolve_class_pipeline(requested: str | None = None) -> PipelineSelection:
    """Pick the transcription engine, and be explicit when falling back."""
    raw = (requested if requested is not None else os.getenv("NOVA_CLASS_PIPELINE", "")).strip().casefold()
    choice = raw or LIVEKIT

    if choice not in {LIVEKIT, PIPECAT}:
        return PipelineSelection(
            requested=choice,
            engine=LIVEKIT,
            available=True,
            reason=(
                f"unknown NOVA_CLASS_PIPELINE value {choice!r}; "
                "using the verified LiveKit pipeline"
            ),
        )

    if choice == LIVEKIT:
        return PipelineSelection(
            requested=LIVEKIT,
            engine=LIVEKIT,
            available=True,
            reason="verified LiveKit Inference (Deepgram nova-3-general) pipeline",
        )

    support = describe_pipecat_support()
    if support["usable"]:
        return PipelineSelection(
            requested=PIPECAT,
            engine=PIPECAT,
            available=True,
            reason="Pipecat pilot pipeline requested and importable",
            details=support,
        )

    return PipelineSelection(
        requested=PIPECAT,
        engine=LIVEKIT,
        available=False,
        reason="Pipecat unavailable: " + "; ".join(support["blockers"]),
        details=support,
    )


class PipecatTranscriptionEngine:
    """Pilot adapter: Pipecat local audio -> Deepgram STT -> NOVA callbacks.

    UNVERIFIED. Written against the Pipecat 1.8.x documented API
    (``LocalAudioTransport``, ``DeepgramSTTService.Settings``,
    ``Pipeline``/``PipelineTask``/``PipelineRunner``). It has never been run
    against a microphone on this machine, because ``pipecat-ai`` and its
    ``local`` extra (PyAudio, which has no cp314 wheel) are not installed. Do
    not describe it as working until an acceptance run says so.
    """

    name = PIPECAT

    def __init__(
        self,
        *,
        keyterms: list[str] | None = None,
        sample_rate: int = 16_000,
        api_key: str | None = None,
    ) -> None:
        self.keyterms = list(keyterms or [])
        self.sample_rate = int(sample_rate)
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY", "").strip()
        self._task = None
        self._runner = None

    def describe(self) -> dict[str, Any]:
        return {
            "engine": self.name,
            "verified": False,
            "model": PIPECAT_STT_MODEL,
            "keyterms": len(self.keyterms),
            "support": describe_pipecat_support(),
        }

    def _require(self) -> None:
        support = describe_pipecat_support()
        if not support["usable"]:
            raise TranscriptionEngineUnavailable(
                "Pipecat class pipeline cannot start: "
                + "; ".join(support["blockers"])
            )

    async def start(self, *, on_transcript, on_error=None) -> None:
        """Build and run the Pipecat pipeline, forwarding finalized speech."""
        self._require()

        # Imported here, never at module scope: pipecat-ai is intentionally
        # not installed, and importing it must not be able to break Class
        # Capture startup on the verified LiveKit path.
        from pipecat.frames.frames import TranscriptionFrame  # type: ignore[import-not-found]
        from pipecat.pipeline.pipeline import Pipeline  # type: ignore[import-not-found]
        from pipecat.pipeline.runner import PipelineRunner  # type: ignore[import-not-found]
        from pipecat.pipeline.task import PipelineTask  # type: ignore[import-not-found]
        from pipecat.processors.frame_processor import FrameProcessor  # type: ignore[import-not-found]
        from pipecat.services.deepgram.stt import DeepgramSTTService  # type: ignore[import-not-found]
        from pipecat.transports.local.audio import (  # type: ignore[import-not-found]
            LocalAudioTransport,
            LocalAudioTransportParams,
        )

        class _NovaTranscriptSink(FrameProcessor):
            """Forward finalized Deepgram speech into NOVA's own journals."""

            async def process_frame(self, frame, direction) -> None:
                await super().process_frame(frame, direction)
                if isinstance(frame, TranscriptionFrame):
                    try:
                        on_transcript(
                            TranscriptionEvent(
                                text=str(getattr(frame, "text", "") or ""),
                                is_final=True,
                                speaker_id=_speaker_id_of(frame),
                            )
                        )
                    except Exception as error:  # pragma: no cover - pilot path
                        if on_error is not None:
                            on_error(error)
                await self.push_frame(frame, direction)

        transport = LocalAudioTransport(LocalAudioTransportParams())
        stt = DeepgramSTTService(
            api_key=self.api_key,
            settings=DeepgramSTTService.Settings(
                model=PIPECAT_STT_MODEL,
                punctuate=True,
                smart_format=True,
                diarize=True,
                keyterm=self.keyterms,
            ),
        )

        pipeline = Pipeline([transport.input(), stt, _NovaTranscriptSink()])
        self._task = PipelineTask(pipeline)
        self._runner = PipelineRunner()
        await self._runner.run(self._task)

    async def stop(self, *, drain: bool = True) -> None:
        task = self._task
        if task is None:
            return
        stop = getattr(task, "stop_when_done", None) if drain else None
        if stop is not None:
            await stop()
            return
        cancel = getattr(task, "cancel", None)
        if cancel is not None:
            await cancel()


def _speaker_id_of(frame: Any) -> str | None:
    for attribute in ("speaker_id", "speaker"):
        value = getattr(frame, attribute, None)
        if value is not None:
            return str(value)
    return None
