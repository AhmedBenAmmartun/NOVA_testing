"""Notes written *during* the lecture, not after it.

Class Intelligence used to produce its first note only after the class ended,
which meant a session that stopped early -- exactly what happened on
2026-08-27 -- produced no notes at all for the part that was captured. It also
meant the user had nothing to look at during a three-hour sitting.

This module runs a note worker alongside capture. It is built around three
rules that follow directly from the reliability goal:

1. **Never in the audio path.** The worker only ever reads finalized transcript
   segments. If Groq, OpenAI, Ollama, or the network fails, notes degrade;
   recording and transcription do not notice.
2. **Batch the evidence, not the sentences.** One model call per transcript
   line would be both ruinous and useless. Batches close on elapsed time, on
   accumulated words, or on an explicit flush, and the first batch closes
   early so notes exist within a minute or two of the class starting.
3. **Nothing pending is ever lost.** Every batch is appended to a durable queue
   before any provider is contacted, and a checkpoint records what has actually
   been folded into the notes. A provider outage leaves work queued; recovery
   drains it.

The generator is injected, so the batching, queueing, checkpointing, merging,
and failure behaviour are all testable without a model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TranscriptSegment
from .storage import ClassCaptureStorage


logger = logging.getLogger("nova.class_capture.live_notes")

NOTES_NAME = "live_notes.md"
QUEUE_NAME = "live_notes_queue.jsonl"
STATE_NAME = "live_notes_state.json"

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

#: Ordered (json key, markdown heading) pairs. The order is the order the
#: lecture notes are rendered in.
NOTE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("key_concepts", "Key Concepts"),
    ("definitions", "Definitions"),
    ("professor_explanations", "Professor Explanations"),
    ("examples", "Examples"),
    ("questions_asked", "Questions Asked"),
    ("answers", "Answers / Clarifications"),
    ("emphasis", "Important Emphasis"),
    ("assignments", "Assignments / Deadlines"),
    ("review_items", "Items to Review"),
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class NoteBatch:
    """One unit of lecture evidence the note worker will reason about."""

    index: int
    start_seconds: float
    end_seconds: float
    words: int
    lines: list[str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "words": self.words,
            "lines": list(self.lines),
            "reason": self.reason,
            "queued_at": _utc_now_iso(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NoteBatch":
        return cls(
            index=int(payload.get("index", 0)),
            start_seconds=float(payload.get("start_seconds", 0.0)),
            end_seconds=float(payload.get("end_seconds", 0.0)),
            words=int(payload.get("words", 0)),
            lines=[str(item) for item in payload.get("lines", [])],
            reason=str(payload.get("reason", "unknown")),
        )

    def transcript_text(self) -> str:
        return "\n".join(self.lines)


class LiveNotesBatcher:
    """Decide when enough lecture has happened to be worth a model call."""

    def __init__(
        self,
        *,
        interval_seconds: float = 75.0,
        first_interval_seconds: float = 60.0,
        word_trigger: int = 800,
        minimum_words: int = 120,
        first_minimum_words: int = 60,
    ) -> None:
        self.interval_seconds = max(15.0, float(interval_seconds))
        self.first_interval_seconds = max(15.0, float(first_interval_seconds))
        self.word_trigger = max(120, int(word_trigger))
        self.minimum_words = max(20, int(minimum_words))
        self.first_minimum_words = max(10, int(first_minimum_words))

        self._lines: list[str] = []
        self._words = 0
        self._batch_start: float | None = None
        self._last_end = 0.0
        self._batches_emitted = 0

    @property
    def pending_words(self) -> int:
        return self._words

    @property
    def batches_emitted(self) -> int:
        return self._batches_emitted

    def _window(self) -> tuple[float, int]:
        if self._batches_emitted == 0:
            return self.first_interval_seconds, self.first_minimum_words
        return self.interval_seconds, self.minimum_words

    def feed(self, segment: TranscriptSegment, *, speaker_label: str = "") -> NoteBatch | None:
        text = " ".join((segment.text or "").split())
        if not text:
            return None

        if self._batch_start is None:
            self._batch_start = float(segment.start_seconds)

        label = speaker_label or (segment.speaker_id or segment.speaker.value)
        self._lines.append(f"[{float(segment.start_seconds):0.1f}s] [{label}] {text}")
        self._words += len(text.split())
        self._last_end = float(segment.end_seconds)

        interval, minimum = self._window()
        elapsed = self._last_end - (self._batch_start or 0.0)

        if self._words >= self.word_trigger:
            return self._emit("word_budget")
        if elapsed >= interval and self._words >= minimum:
            return self._emit("interval")
        return None

    def flush(self, *, reason: str = "flush") -> NoteBatch | None:
        if not self._lines:
            return None
        return self._emit(reason)

    def _emit(self, reason: str) -> NoteBatch:
        self._batches_emitted += 1
        batch = NoteBatch(
            index=self._batches_emitted,
            start_seconds=self._batch_start or 0.0,
            end_seconds=self._last_end,
            words=self._words,
            lines=list(self._lines),
            reason=reason,
        )
        self._lines = []
        self._words = 0
        self._batch_start = None
        return batch


class LiveNotesQueue:
    """Durable pending-evidence queue with a processed-batch checkpoint."""

    def __init__(self, session_path: Path) -> None:
        self.session_path = Path(session_path)
        self.queue_path = self.session_path / QUEUE_NAME
        self.state_path = self.session_path / STATE_NAME
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.queue_path.touch(exist_ok=True)
        self._processed: set[int] = set(self._load_state().get("processed", []))

    def _load_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def enqueue(self, batch: NoteBatch) -> None:
        ClassCaptureStorage.append_jsonl(self.queue_path, batch.as_dict())

    def mark_processed(self, batch: NoteBatch, **extra: Any) -> None:
        self._processed.add(batch.index)
        self._write_state(**extra)

    def _write_state(self, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "version": 1,
            "updated_at": _utc_now_iso(),
            "processed": sorted(self._processed),
            "processed_count": len(self._processed),
        }
        payload.update(extra)
        ClassCaptureStorage.write_json(self.state_path, payload)

    def checkpoint(self, **extra: Any) -> None:
        self._write_state(**extra)

    def pending(self) -> list[NoteBatch]:
        """Every queued batch that has not been folded into the notes yet."""
        batches: list[NoteBatch] = []
        try:
            lines = self.queue_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return batches
        for line in lines:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            batch = NoteBatch.from_dict(payload)
            if batch.index not in self._processed:
                batches.append(batch)
        return batches

    @property
    def processed_count(self) -> int:
        return len(self._processed)


@dataclass
class LiveNotesDocument:
    """The accumulated, deduplicated live notes for one sitting."""

    course: str = ""
    title: str = ""
    current_topic: str | None = None
    topics: list[str] = field(default_factory=list)
    sections: dict[str, list[str]] = field(
        default_factory=lambda: {key: [] for key, _ in NOTE_SECTIONS}
    )
    covered_until_seconds: float = 0.0
    batches_folded: int = 0

    def merge(self, payload: dict[str, Any]) -> bool:
        """Fold one model result in. Returns True when anything was added."""
        changed = False

        topic = " ".join(str(payload.get("current_topic") or "").split()).strip()
        if topic and topic.casefold() not in {"none", "unknown", "n/a"}:
            if topic != self.current_topic:
                self.current_topic = topic
                if topic not in self.topics:
                    self.topics.append(topic)
                changed = True

        for key, _heading in NOTE_SECTIONS:
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            target = self.sections.setdefault(key, [])
            existing = {item.casefold() for item in target}
            for item in values:
                cleaned = " ".join(str(item).split()).strip()
                if not cleaned or cleaned.casefold() in existing:
                    continue
                target.append(cleaned)
                existing.add(cleaned.casefold())
                changed = True
        return changed

    def as_markdown(self, *, status_line: str = "") -> str:
        parts = ["# Live Class Notes", ""]
        if self.course or self.title:
            parts.append(f"**{self.course}** — {self.title}".strip(" —"))
            parts.append("")
        parts.append(
            "> Written live during the lecture from the finalized transcript. "
            "Refined after class; the raw transcript and audio remain authoritative."
        )
        parts.append("")
        if status_line:
            parts.append(status_line)
            parts.append("")

        parts.append("## Current Topic")
        parts.append("")
        parts.append(self.current_topic or "_Not resolved yet._")
        parts.append("")

        for key, heading in NOTE_SECTIONS:
            values = self.sections.get(key) or []
            if not values:
                continue
            parts.append(f"## {heading}")
            parts.append("")
            parts.extend(f"- {item}" for item in values)
            parts.append("")

        if self.topics:
            parts.append("## Topic Progression")
            parts.append("")
            parts.extend(f"{index}. {topic}" for index, topic in enumerate(self.topics, 1))
            parts.append("")

        return "\n".join(parts).rstrip() + "\n"


def parse_note_payload(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = _JSON_OBJECT.search(cleaned)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_note_prompt(
    batch: NoteBatch,
    *,
    course: str,
    title: str,
    current_topic: str | None,
    known_concepts: list[str],
    materials: str = "",
) -> str:
    keys = ", ".join(key for key, _ in NOTE_SECTIONS)
    return f"""You are NOVA taking live notes during a college lecture.

COURSE: {course}
SESSION: {title}
TOPIC SO FAR: {current_topic or 'not yet resolved'}
ALREADY NOTED CONCEPTS: {', '.join(known_concepts[:25]) or '(none yet)'}

Return ONLY one JSON object with the string key "current_topic" and these array keys:
{keys}

Rules:
- Use only the transcript excerpt below and, where it clearly supports the lecture, the supplied material excerpts.
- Never invent a definition, deadline, grade policy, example, or professor statement.
- Do not repeat anything already listed under ALREADY NOTED CONCEPTS.
- Keep every item one concise, self-contained sentence.
- Use an empty array for any category this excerpt does not support.
- "current_topic" is a short noun phrase for what is being taught right now, or "" if unclear.

RELATED COURSE MATERIAL EXCERPTS:
{materials[:8000] if materials else '(none available)'}

LECTURE TRANSCRIPT ({batch.start_seconds:0.0f}s - {batch.end_seconds:0.0f}s):
{batch.transcript_text()}"""


class LiveNotesWorker:
    """Turn batched transcript evidence into ``live_notes.md`` during class.

    The worker is a plain asyncio consumer: ``feed`` is cheap and synchronous
    (safe to call from the transcript callback), ``run`` does the slow work.
    Provider failures re-queue the batch and downgrade the worker status; they
    never propagate to the caller.
    """

    def __init__(
        self,
        *,
        session_path: Path,
        course: str,
        title: str,
        generate: Callable[[str], Awaitable[str | None]],
        batcher: LiveNotesBatcher | None = None,
        material_context_provider: Callable[[str], tuple[str, list]] | None = None,
        on_topic: Callable[[str, float], None] | None = None,
        on_status: Callable[[str, str | None], None] | None = None,
        retry_seconds: float = 45.0,
        max_attempts_per_batch: int = 4,
    ) -> None:
        self.session_path = Path(session_path)
        self.course = course
        self.title = title
        self.generate = generate
        self.batcher = batcher or LiveNotesBatcher()
        self.material_context_provider = material_context_provider
        self.on_topic = on_topic
        self.on_status = on_status
        # No hard floor: the caller owns the backoff. class_capture uses the
        # 45s default so a provider outage is not hammered.
        self.retry_seconds = max(0.0, float(retry_seconds))
        self.max_attempts_per_batch = max(1, int(max_attempts_per_batch))

        self.queue = LiveNotesQueue(self.session_path)
        self.document = LiveNotesDocument(course=course, title=title)
        self.notes_path = self.session_path / NOTES_NAME

        self._work: asyncio.Queue[NoteBatch] = asyncio.Queue()
        self._status = "active"
        self._last_error: str | None = None
        self._consecutive_failures = 0
        self._generated = 0
        self._last_update_seconds = 0.0

        self.write_notes()

    # --- state -----------------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def generated_count(self) -> int:
        return self._generated

    @property
    def pending_count(self) -> int:
        return self._work.qsize()

    @property
    def last_update_seconds(self) -> float:
        return self._last_update_seconds

    def _set_status(self, status: str, detail: str | None = None) -> None:
        if status == self._status and detail == self._last_error:
            return
        self._status = status
        self._last_error = detail
        # The notes file carries the status line, so a degraded provider has to
        # be visible in the file the user is actually reading -- not only in
        # health.json.
        try:
            self.write_notes()
        except OSError:
            logger.exception("could not refresh live notes after a status change")
        if self.on_status is not None:
            try:
                self.on_status(status, detail)
            except Exception:
                logger.exception("live notes status callback failed")

    # --- ingestion -------------------------------------------------------

    def feed(self, segment: TranscriptSegment, *, speaker_label: str = "") -> NoteBatch | None:
        """Cheap, synchronous. Safe to call from the STT callback."""
        batch = self.batcher.feed(segment, speaker_label=speaker_label)
        if batch is not None:
            self._enqueue(batch)
        return batch

    def flush(self, *, reason: str = "finalize") -> NoteBatch | None:
        batch = self.batcher.flush(reason=reason)
        if batch is not None:
            self._enqueue(batch)
        return batch

    def _enqueue(self, batch: NoteBatch) -> None:
        # Durable first, in-memory second: a crash between the two loses
        # nothing, because pending() re-reads the queue from disk.
        self.queue.enqueue(batch)
        self._work.put_nowait(batch)

    def restore_pending(self) -> int:
        """Re-queue anything a previous run persisted but never folded in."""
        restored = 0
        for batch in self.queue.pending():
            self._work.put_nowait(batch)
            restored += 1
        return restored

    # --- processing ------------------------------------------------------

    async def process_one(self, batch: NoteBatch) -> bool:
        materials = ""
        if self.material_context_provider is not None:
            try:
                materials, _sources = self.material_context_provider(
                    self.document.current_topic or batch.transcript_text()[:400]
                )
            except Exception:
                logger.exception("live notes material context failed")
                materials = ""

        prompt = build_note_prompt(
            batch,
            course=self.course,
            title=self.title,
            current_topic=self.document.current_topic,
            known_concepts=list(self.document.sections.get("key_concepts", [])),
            materials=materials,
        )

        try:
            raw = await self.generate(prompt)
        except Exception as error:
            self._consecutive_failures += 1
            self._set_status("degraded", f"{type(error).__name__}: {error}")
            return False

        payload = parse_note_payload(raw)
        if payload is None:
            self._consecutive_failures += 1
            self._set_status(
                "degraded",
                "no usable model response for the queued lecture evidence",
            )
            return False

        self._consecutive_failures = 0
        previous_topic = self.document.current_topic
        self.document.merge(payload)
        self.document.covered_until_seconds = max(
            self.document.covered_until_seconds, batch.end_seconds
        )
        self.document.batches_folded += 1
        self._generated += 1
        self._last_update_seconds = batch.end_seconds
        self.queue.mark_processed(
            batch,
            covered_until_seconds=round(self.document.covered_until_seconds, 3),
            current_topic=self.document.current_topic,
        )
        self.write_notes()
        self._set_status("active", None)

        if (
            self.on_topic is not None
            and self.document.current_topic
            and self.document.current_topic != previous_topic
        ):
            try:
                self.on_topic(self.document.current_topic, batch.start_seconds)
            except Exception:
                logger.exception("live notes topic callback failed")

        return True

    async def run(self) -> None:
        """Drain queued evidence forever. Cancel it to stop."""
        while True:
            batch = await self._work.get()
            try:
                attempts = 0
                while attempts < self.max_attempts_per_batch:
                    attempts += 1
                    if await self.process_one(batch):
                        break
                    if attempts >= self.max_attempts_per_batch:
                        # Give up on *this attempt cycle* only. The batch stays
                        # unprocessed in the durable queue, so post-class
                        # refinement still sees the evidence.
                        self._set_status(
                            "degraded",
                            self._last_error
                            or "note provider unavailable; evidence stays queued",
                        )
                        self.queue.checkpoint(
                            pending_note_batches=len(self.queue.pending())
                        )
                        break
                    await asyncio.sleep(self.retry_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("live notes worker iteration failed")
            finally:
                self._work.task_done()

    async def drain(self, timeout_seconds: float = 25.0) -> bool:
        """Wait for queued evidence to be folded in. False on timeout."""
        try:
            await asyncio.wait_for(self._work.join(), timeout=max(0.0, timeout_seconds))
        except asyncio.TimeoutError:
            return False
        return True

    # --- output ----------------------------------------------------------

    def status_line(self) -> str:
        pending = len(self.queue.pending())
        bits = [
            f"_Live notes status: **{self._status}**_",
            f"_Folded batches: {self.document.batches_folded}_",
            f"_Queued evidence batches: {pending}_",
        ]
        if self._last_error:
            bits.append(f"_Last note issue: {self._last_error}_")
        return "  \n".join(bits)

    def write_notes(self) -> Path:
        markdown = self.document.as_markdown(status_line=self.status_line())
        temporary = self.notes_path.with_suffix(".md.tmp")
        temporary.write_text(markdown, encoding="utf-8")
        temporary.replace(self.notes_path)
        return self.notes_path
