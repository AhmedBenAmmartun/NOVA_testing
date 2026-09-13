from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .class_budget import get_class_cloud_usage_budget
from .models import QuestionRecord, TranscriptSegment
from .notifications import show_answer_popup
from .question_detection import should_answer_question
from .storage import ClassCaptureStorage
from .terminology import TerminologyInterpreter


logger = logging.getLogger("nova.class_capture.intelligence")
_class_router = None

# Class Intelligence is cloud-first. A live lecture is a real-time, low-latency
# workload running on the same PC Ahmed is taking the class on, so "the cloud is
# gone" must mean *less intelligence*, never *more local work*.
#
# This order is a preference between cloud providers only. Membership of the
# tier is decided by ProviderConfiguration.is_local at resolution time, so a
# local model can never enter the automatic class path -- not through this
# default, not through NOVA_CLASS_CLOUD_PROVIDER_ORDER, and not through
# nova_core's own fallback_order (every class call passes allow_fallback=False).
_DEFAULT_CLASS_CLOUD_ORDER = ("openai", "groq")
_CLASS_CLOUD_ORDER_ENV = "NOVA_CLASS_CLOUD_PROVIDER_ORDER"

# The emergency hatch for the later local-fallback phase. Off by default: on
# 2026-08-28 an automatic local fallback ran 86 heavy inferences during one
# lecture, and on 2026-09-01 another 42, which is the behaviour this module
# exists to prevent.
_CLASS_LOCAL_FALLBACK_ENV = "NOVA_CLASS_ALLOW_LOCAL_FALLBACK"

_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}


@dataclass(frozen=True, slots=True)
class ClassRouteOutcome:
    """What actually happened to the last class intelligence request.

    Carried separately from the returned text because ``_route`` must keep
    returning ``str | None`` -- ``live_notes`` and ``understanding`` both treat
    ``None`` as "degrade and keep the evidence", and that contract predates
    this module knowing *why* it had to defer.
    """

    state: str
    reason: str
    detail: str
    provider: str | None = None
    at: str = ""

    @property
    def deferred(self) -> bool:
        return self.state == "deferred"


_last_outcome: ClassRouteOutcome | None = None


def last_class_route_outcome() -> ClassRouteOutcome | None:
    """Return the most recent class routing outcome, or None before any call."""

    return _last_outcome


def _record_outcome(
    state: str,
    reason: str,
    detail: str,
    provider: str | None = None,
) -> ClassRouteOutcome:
    global _last_outcome
    _last_outcome = ClassRouteOutcome(
        state=state,
        reason=reason,
        detail=detail,
        provider=provider,
        at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    return _last_outcome


def _local_fallback_allowed() -> bool:
    raw = os.getenv(_CLASS_LOCAL_FALLBACK_ENV, "").strip().lower()
    return raw in _TRUE_VALUES


def _class_cloud_providers(router) -> tuple[str, ...]:
    """Resolve the ordered cloud tier this class may use.

    Anything local is dropped rather than reordered: the filter is the
    invariant, not the order.
    """

    from nova_core import parse_provider_name

    configured = os.getenv(_CLASS_CLOUD_ORDER_ENV, "")
    requested = [item.strip() for item in configured.split(",") if item.strip()]
    if not requested:
        requested = list(_DEFAULT_CLASS_CLOUD_ORDER)

    ordered: list[str] = []
    for name in requested:
        try:
            provider = parse_provider_name(name)
            provider_configuration = router.configuration.provider(provider)
        except Exception:
            logger.warning("ignoring unknown class cloud provider: %s", name)
            continue

        if provider_configuration.is_local:
            logger.warning(
                "refusing local provider '%s' in the class cloud tier; "
                "class intelligence defers instead of running local inference",
                provider.value,
            )
            continue

        if provider.value not in ordered:
            ordered.append(provider.value)

    return tuple(ordered)


def _deferral_reason(router) -> tuple[str, str]:
    """Say why the cloud tier could not serve this request."""

    try:
        budget = router.cloud_budget.status()
        # A disabled budget never blocks anything, so it must never be blamed
        # for an outage -- the counter keeps rising even while it is off.
        remaining = (
            budget.get("remaining_today") if budget.get("enabled", True) else None
        )
    except Exception:
        remaining = None

    if remaining == 0:
        return (
            "class_cloud_budget_exhausted",
            "class cloud budget exhausted for today; "
            "lecture evidence is queued for later",
        )
    return (
        "cloud_providers_unavailable",
        "cloud providers unavailable; lecture evidence is queued for later",
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
    """Route one class request across the cloud tier, or defer.

    Returns None when no cloud provider can serve the request. That is a
    deliberate, load-bearing outcome rather than an error: every class consumer
    already treats None as "mark this degraded and keep the evidence", so a
    cloud outage costs intelligence instead of costing the PC.
    """
    try:
        from nova_core import NoProviderAvailableError, RouterError

        router = _get_class_router()
    except Exception:
        logger.exception("Class Intelligence router initialization failed")
        _record_outcome(
            "deferred",
            "router_unavailable",
            "class intelligence router could not start; evidence is queued",
        )
        return None

    cloud_providers = _class_cloud_providers(router)
    if not cloud_providers:
        logger.warning("Class Intelligence has no cloud provider configured")
        _record_outcome(
            "deferred",
            "no_cloud_providers_configured",
            "no class cloud provider is configured; evidence is queued",
        )
        return None

    for provider_name in cloud_providers:
        try:
            # allow_fallback=False keeps nova_core's own fallback_order -- which
            # ends at the local provider -- out of the class path entirely.
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
            _record_outcome(
                "answered",
                "cloud_provider_answered",
                f"answered by {response.provider}",
                provider=response.provider,
            )
            return answer

    reason, detail = _deferral_reason(router)

    if _local_fallback_allowed():
        # Explicitly requested, never automatic. Still routed through nova_core
        # so the local provider stays a routing decision, not a hardcoded name.
        try:
            response = await router.route(
                task,
                role="private",
                local_only=True,
                allow_fallback=True,
            )
        except Exception:
            logger.exception("Class Intelligence local fallback failed")
        else:
            answer = (response.text or "").strip()
            if answer:
                logger.warning(
                    "Class Intelligence used the explicitly enabled local "
                    "fallback: provider=%s model=%s",
                    response.provider,
                    response.model,
                )
                _record_outcome(
                    "answered",
                    "local_fallback_requested",
                    f"answered locally by {response.provider} "
                    f"(enabled via {_CLASS_LOCAL_FALLBACK_ENV})",
                    provider=response.provider,
                )
                return answer

    logger.info("Class Intelligence deferred this request: %s", reason)
    _record_outcome("deferred", reason, detail)
    return None


async def route_class_prompt(task: str, *, role: str = "reasoning") -> str | None:
    """Public Class-Intelligence routing entry point (cloud tier, then defer).

    Live notes and post-class generation both go through here so they share one
    provider order, one class-scoped cloud budget, and one deferral policy.
    """
    return await _route(task, role=role)


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
