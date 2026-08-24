from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from .class_budget import get_class_cloud_usage_budget
from .models import QuestionRecord, TranscriptSegment
from .notifications import show_answer_popup
from .question_detection import should_answer_question
from .storage import ClassCaptureStorage
from .terminology import TerminologyInterpreter


logger = logging.getLogger("nova.class_capture.intelligence")
_class_router = None
_ROUTER_FAILURE_PREFIXES = (
    "No specialist model is currently available",
    "NOVA could not route that specialist request",
    "The specialist system encountered an unexpected error",
)


def _trim(value: str, limit: int) -> str:
    text = (value or "").strip()
    return text if len(text) <= limit else text[-limit:]


def _recent_transcript_text(
    segments: list[TranscriptSegment],
    *,
    limit: int = 12_000,
) -> str:
    lines = []
    for segment in segments[-40:]:
        label = segment.speaker_id or segment.speaker.value
        lines.append(f"[{label}] {segment.text.strip()}")
    return _trim("\n".join(lines), limit)


def _get_class_router():
    """Create a Class-Intelligence router with its own cloud budget."""
    global _class_router
    if _class_router is None:
        from nova_core import create_model_router

        _class_router = create_model_router(
            cloud_budget=get_class_cloud_usage_budget(),
        )
    return _class_router


async def _route(task: str, *, role: str = "reasoning") -> str | None:
    """Route Class Intelligence Groq -> OpenAI -> Ollama."""
    try:
        from nova_core import NoProviderAvailableError, RouterError

        router = _get_class_router()
    except Exception:
        logger.exception("Class Intelligence router initialization failed")
        return None

    for provider_name in ("groq", "openai", "ollama"):
        try:
            response = await router.route(
                task,
                role=role,
                preferred_provider=provider_name,
                allow_fallback=False,
                local_only=False,
            )
        except (NoProviderAvailableError, RouterError):
            continue
        except Exception:
            logger.exception(
                "Class Intelligence provider attempt failed: %s",
                provider_name,
            )
            continue

        answer = (response.text or "").strip()
        if answer:
            logger.info(
                "Class Intelligence provider selected: %s model=%s",
                response.provider,
                response.model,
            )
            return answer

    return None


class LiveQAManager:
    """Ground live answers in transcript/material context and persist events."""

    def __init__(
        self,
        *,
        session_path: Path,
        material_context_provider,
        terminology_interpreter: TerminologyInterpreter | None = None,
        max_concurrent: int = 2,
    ) -> None:
        self.session_path = session_path
        self.material_context_provider = material_context_provider
        self.terminology_interpreter = terminology_interpreter
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrent)))
        self._recent_keys: set[str] = set()
        self.log_path = session_path / "Live Q&A.md"
        self.events_path = session_path / "live_qa_events.jsonl"
        self._events: list[dict[str, object]] = []
        self.events_path.touch(exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text("# Live Q&A\n\n", encoding="utf-8")

    @staticmethod
    def _key(question: str) -> str:
        return re.sub(r"\W+", " ", question.casefold()).strip()[:240]

    def should_answer(self, question: str) -> bool:
        key = self._key(question)
        if not key or key in self._recent_keys:
            return False
        return should_answer_question(question)

    async def answer(
        self,
        question: QuestionRecord,
        *,
        recent_segments: list[TranscriptSegment],
        course_code: str,
        course_name: str,
        current_topic: str | None,
    ) -> str | None:
        if not self.should_answer(question.question):
            return None

        interpretation = (
            self.terminology_interpreter.interpret(question.question)
            if self.terminology_interpreter is not None
            else None
        )
        interpreted_question = (
            interpretation.interpreted
            if interpretation is not None and interpretation.interpreted
            else question.question
        )

        key = self._key(interpreted_question)
        self._recent_keys.add(key)
        if len(self._recent_keys) > 200:
            self._recent_keys = set(list(self._recent_keys)[-120:])

        async with self._semaphore:
            try:
                materials, sources = self.material_context_provider(
                    interpreted_question
                )
            except Exception:
                logger.exception("could not build live class material context")
                materials, sources = "", []

            prompt = f"""You are NOVA silently assisting during a live college class.

COURSE: {course_code} — {course_name}
CURRENT TOPIC: {current_topic or 'not yet resolved'}
RAW STT QUESTION: {question.question}
INTERPRETED QUESTION: {interpreted_question}

RECENT LECTURE TRANSCRIPT:
{_recent_transcript_text(recent_segments)}

RELATED COURSE/SESSION MATERIAL EXCERPTS:
{_trim(materials, 18000) if materials else '(none available)'}

The RAW STT QUESTION may contain speech-recognition errors. The INTERPRETED QUESTION is allowed to correct terminology only when NOVA's deterministic terminology layer supplied that correction. Never invent a different word just because it seems plausible. If a key word is unclear, garbled, or unsupported by the supplied transcript/materials, say briefly that NOVA may have heard that word incorrectly and ask for repetition instead of guessing.

Answer only the question that was actually captured. Respond in 2-5 concise sentences. Prioritize lecture/material evidence when it supports the answer. Do not claim a page number, professor statement, deadline, or course policy unless it appears in the supplied evidence."""

            answer = await _route(prompt)
            if answer is None:
                self._record_event(question, None, sources, interpretation)
                return None

            self._record_event(question, answer, sources, interpretation)
            try:
                await show_answer_popup(question.question, answer)
            except Exception:
                logger.exception("answer popup failed")
            return answer

    def _event_payload(
        self,
        question: QuestionRecord,
        answer: str | None,
        sources,
        interpretation=None,
    ) -> dict[str, object]:
        interpreted = (
            interpretation.interpreted
            if interpretation is not None and interpretation.changed
            else None
        )
        corrections = (
            [
                {"from": source, "to": target}
                for source, target in interpretation.corrections
            ]
            if interpretation is not None and interpretation.changed
            else []
        )
        return {
            "timestamp_seconds": question.timestamp_seconds,
            "speaker_id": question.speaker_id,
            "speaker_at_answer": question.speaker.value,
            "raw_question": question.question.strip(),
            "interpreted_question": interpreted,
            "answer": (
                answer.strip()
                if answer
                else "Answer unavailable during live capture."
            ),
            "context_sources": [
                Path(item.path).name
                for item in sources[:5]
            ],
            "corrections": corrections,
        }

    def _record_event(
        self,
        question: QuestionRecord,
        answer: str | None,
        sources,
        interpretation=None,
    ) -> None:
        event = self._event_payload(
            question,
            answer,
            sources,
            interpretation,
        )
        self._events.append(event)
        ClassCaptureStorage.append_jsonl(self.events_path, event)
        self._render_log()

        if interpretation is not None and interpretation.changed:
            ClassCaptureStorage.append_jsonl(
                self.session_path / "question_interpretations.jsonl",
                {
                    "timestamp_seconds": question.timestamp_seconds,
                    "raw": interpretation.raw,
                    "interpreted": interpretation.interpreted,
                    "corrections": event["corrections"],
                },
            )

    def _render_log(self, resolver=None) -> None:
        parts = ["# Live Q&A\n\n"]
        for event in self._events:
            speaker = str(event.get("speaker_at_answer") or "unknown")
            speaker_id = event.get("speaker_id")
            if resolver is not None and speaker_id is not None:
                try:
                    speaker = resolver(speaker_id).role.value
                except Exception:
                    logger.exception("could not resolve final Q&A speaker role")

            interpreted = event.get("interpreted_question")
            interpretation_line = (
                f"**Interpreted terminology:** {interpreted}\n\n"
                if interpreted
                else ""
            )
            source_names = ", ".join(event.get("context_sources") or []) or "none"
            parts.append(
                f"## {float(event['timestamp_seconds']):0.1f}s — {speaker}\n\n"
                f"**Raw question:** {event['raw_question']}\n\n"
                f"{interpretation_line}"
                f"**Answer:** {event['answer']}\n\n"
                f"**Context sources:** {source_names}\n\n"
            )

        temporary = self.log_path.with_suffix(".md.tmp")
        temporary.write_text("".join(parts), encoding="utf-8")
        temporary.replace(self.log_path)

    def rebuild_log(self, resolver) -> None:
        """Re-render Live Q&A with the final session speaker map."""
        self._render_log(resolver)
