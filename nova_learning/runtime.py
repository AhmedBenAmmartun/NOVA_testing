from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import time
from typing import Any

from .redaction import redact
from .evaluator import correction_signal, evaluate_tool_result
from .schema import Experience, ToolCall
from .store import NDJSONExperienceStore


logger = logging.getLogger("nova.learning")


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _item_text(item: object) -> str:
    text = getattr(item, "text_content", None)
    if isinstance(text, str):
        return text.strip()

    content = getattr(item, "content", None)
    if isinstance(content, list):
        parts = [part for part in content if isinstance(part, str)]
        return "\n".join(parts).strip()

    return ""


def _safe_arguments(raw: object) -> dict[str, Any]:
    """Return structured, redacted tool arguments without persisting raw blobs."""
    if isinstance(raw, dict):
        safe = redact(raw)
        return safe if isinstance(safe, dict) else {"arguments": safe}

    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            # Do not keep arbitrary unparsed argument strings; they may contain
            # transcript text, file contents, tokens, URLs with secrets, etc.
            return {"arguments": "<unparsed arguments redacted>"}
        safe = redact(decoded)
        return safe if isinstance(safe, dict) else {"arguments": safe}

    if raw is None:
        return {}

    return {"arguments": f"<{type(raw).__name__}>"}


def _output_is_error(output: object | None) -> bool:
    if output is None:
        return False
    return bool(getattr(output, "is_error", False))


@dataclass(slots=True)
class _ActiveTurn:
    experience: Experience
    started_at: float


class LearningSessionRecorder:
    """Observe LiveKit session events and persist privacy-reduced experiences.

    This is intentionally event-based. NOVA's current runtime already exposes
    final conversation items and completed tool batches through AgentSession,
    which lets learning observe the whole capability surface without wrapping
    or changing every individual tool.

    Privacy/safety defaults:
    - NOVA_LEARNING_ENABLED=false
    - NOVA_LEARNING_STORE_UTTERANCES=false
    - records are written outside the Git repository by NDJSONExperienceStore
    - tool outputs are never persisted here
    - failed persistence never breaks the agent
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        store_utterances: bool | None = None,
        store: NDJSONExperienceStore | None = None,
        route: str = "",
        model: str = "",
        strategy_versions: dict[str, str] | None = None,
    ) -> None:
        self.enabled = (
            _env_flag("NOVA_LEARNING_ENABLED", default=False)
            if enabled is None
            else bool(enabled)
        )
        self.store_utterances = (
            _env_flag("NOVA_LEARNING_STORE_UTTERANCES", default=False)
            if store_utterances is None
            else bool(store_utterances)
        )
        self.store = store
        self.route = route.strip()
        self.model = model.strip()
        self.strategy_versions = dict(strategy_versions or {})

        self._active: _ActiveTurn | None = None
        self._last_voice_final_at = 0.0
        self._last_voice_fingerprint: bytes | None = None
        self._writer: ThreadPoolExecutor | None = None
        self._attached = False
        self._last_finalized_experience_id: str | None = None

    def attach(self, session) -> bool:
        """Attach fail-open event listeners. Returns whether learning is enabled."""
        if not self.enabled:
            logger.info("learning experience recording disabled")
            return False
        if self._attached:
            return True

        self._attached = True
        if self.store is None:
            self.store = NDJSONExperienceStore()
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nova-learning")

        @session.on("user_input_transcribed")
        def _voice_transcribed(event) -> None:
            self._guard(self._on_voice_transcribed, event)

        @session.on("conversation_item_added")
        def _conversation_item(event) -> None:
            self._guard(self._on_conversation_item, event)

        @session.on("function_tools_executed")
        def _tools_executed(event) -> None:
            self._guard(self._on_tools_executed, event)

        @session.on("error")
        def _session_error(event) -> None:
            self._guard(self._on_session_error, event)

        @session.on("close")
        def _session_close(event) -> None:
            self._guard(self._on_session_close, event)

        logger.info(
            "learning experience recording enabled store_utterances=%s root=%s",
            self.store_utterances,
            getattr(self.store, "root", "custom"),
        )
        return True

    def _guard(self, fn, event) -> None:
        try:
            fn(event)
        except Exception:
            # Learning is observation-only. It must never take down a working
            # voice session or capability path.
            logger.exception("learning event handler failed event=%s", getattr(event, "type", "unknown"))

    @staticmethod
    def _fingerprint(text: str) -> bytes:
        normalized = " ".join(text.split()).strip().encode("utf-8", "replace")
        return hashlib.sha256(normalized).digest()

    def _on_voice_transcribed(self, event) -> None:
        if bool(getattr(event, "is_final", False)):
            transcript = str(getattr(event, "transcript", "") or "")
            self._last_voice_final_at = time.monotonic()
            self._last_voice_fingerprint = self._fingerprint(transcript)

    def _new_experience(self, *, text: str, modality: str) -> Experience:
        if self.store_utterances:
            safe_utterance = redact(text, max_string_chars=500)
            if not isinstance(safe_utterance, str):
                safe_utterance = "<redacted>"
        else:
            safe_utterance = f"<not stored; chars={len(text)}>"

        versions = dict(self.strategy_versions)
        versions.setdefault("outcome_evaluator", "v1")
        return Experience(
            utterance_redacted=safe_utterance,
            modality=modality if modality in {"voice", "text", "screen"} else "voice",
            route=self.route,
            model=self.model,
            strategy_versions=versions,
        )

    def _on_conversation_item(self, event) -> None:
        item = getattr(event, "item", None)
        if item is None:
            return

        role = getattr(item, "role", "")
        if role not in {"user", "assistant"}:
            return

        text = _item_text(item)
        if role == "user":
            # A new user turn may be explicit feedback about the immediately
            # preceding experience. Detect the signal in memory, then persist
            # only a categorical patch -- never the raw correction text.
            signal = correction_signal(text)
            if signal and self._last_finalized_experience_id:
                self._submit_patch(
                    self._last_finalized_experience_id,
                    {
                        "outcome": "failure",
                        "outcome_source": "user_correction",
                        "outcome_score": 1.0,
                        "user_correction": signal,
                        "correction_ts": time.time(),
                    },
                )

            # If a previous turn never received an assistant message (e.g. an
            # interruption), preserve it as an incomplete observation instead
            # of silently dropping it.
            if self._active is not None:
                self._finalize_active(outcome="partial", source="superseded_by_user_turn")

            recent_voice = (time.monotonic() - self._last_voice_final_at) <= 5.0
            same_input = self._last_voice_fingerprint == self._fingerprint(text)
            modality = "voice" if recent_voice and same_input else "text"
            experience = self._new_experience(text=text, modality=modality)
            self._active = _ActiveTurn(experience=experience, started_at=time.perf_counter())
            return

        # Assistant item closes the currently active user turn. A response by
        # itself is not proof the task succeeded, so outcome stays unknown
        # unless verified tool failure evidence was already recorded.
        if self._active is not None:
            current = self._active.experience
            if current.outcome in {"success", "failure", "partial"}:
                self._finalize_active(
                    outcome=current.outcome,
                    source=current.outcome_source or "verified_evidence",
                )
            else:
                self._finalize_active(outcome="unknown", source="assistant_response")

    def _on_tools_executed(self, event) -> None:
        if self._active is None:
            return

        calls = list(getattr(event, "function_calls", ()) or ())
        outputs = list(getattr(event, "function_call_outputs", ()) or ())

        for index, call in enumerate(calls):
            output = outputs[index] if index < len(outputs) else None
            is_error = _output_is_error(output)
            name = str(getattr(call, "name", "unknown_tool") or "unknown_tool")
            arguments = _safe_arguments(getattr(call, "arguments", None))

            self._active.experience.tools.append(
                ToolCall(
                    name=name,
                    args=arguments,
                    ok=not is_error,
                    # FunctionToolsExecutedEvent in the verified runtime does
                    # not expose per-tool duration. Keep 0 rather than inventing
                    # precision; end-to-end turn latency is recorded separately.
                    latency_ms=0,
                    error="tool_error" if is_error else None,
                )
            )

            # When transcript quality is poor, the selected tool can still be a
            # useful privacy-safe intent signal. Keep only tool names.
            names = [tool.name for tool in self._active.experience.tools if tool.name]
            if names:
                self._active.experience.intent = "tool:" + ">".join(names[:6])

            raw_output = getattr(output, "output", None) if output is not None else None
            evaluation = evaluate_tool_result(
                tool_name=name,
                output=raw_output,
                is_error=is_error,
            )
            if evaluation is not None:
                current_score = float(self._active.experience.outcome_score or 0.0)
                # Failure evidence wins ties. Otherwise keep the strongest
                # deterministic evaluation from the tool batch.
                replace = evaluation.score > current_score
                if evaluation.score == current_score and evaluation.outcome == "failure":
                    replace = True
                if replace:
                    self._active.experience.outcome = evaluation.outcome  # type: ignore[assignment]
                    self._active.experience.outcome_source = evaluation.source
                    self._active.experience.outcome_score = evaluation.score

    def _on_session_error(self, event) -> None:
        if self._active is None:
            return
        error = getattr(event, "error", None)
        recoverable = bool(getattr(error, "recoverable", False))
        if not recoverable:
            self._active.experience.outcome = "failure"
            self._active.experience.outcome_source = "unrecoverable_session_error"
            self._active.experience.outcome_score = 1.0

    def _on_session_close(self, _event) -> None:
        if self._active is not None:
            outcome = self._active.experience.outcome
            source = self._active.experience.outcome_source or "session_closed"
            self._finalize_active(outcome=outcome, source=source)
        self._close_writer()

    def _finalize_active(self, *, outcome: str, source: str) -> None:
        active = self._active
        if active is None:
            return

        experience = active.experience
        experience.latency_ms = max(
            experience.latency_ms,
            int((time.perf_counter() - active.started_at) * 1000),
        )

        if outcome in {"success", "failure", "partial", "unknown"}:
            experience.outcome = outcome  # type: ignore[assignment]
        experience.outcome_source = source

        self._active = None
        self._last_finalized_experience_id = experience.id
        self._submit_write(experience)

    def _submit_write(self, experience: Experience) -> None:
        writer = self._writer
        if writer is None:
            return

        try:
            store = self.store
            if store is None:
                return
            future = writer.submit(store.append_experience, experience)
            future.add_done_callback(self._write_finished)
        except Exception:
            logger.exception("learning experience queue failed")


    def _submit_patch(self, experience_id: str, changes: dict[str, Any]) -> None:
        writer = self._writer
        if writer is None:
            return

        try:
            store = self.store
            if store is None:
                return
            future = writer.submit(store.append_patch, experience_id, changes)
            future.add_done_callback(self._write_finished)
        except Exception:
            logger.exception("learning patch queue failed")

    @staticmethod
    def _write_finished(future) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("learning experience persistence failed")

    def _close_writer(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is None:
            return
        try:
            writer.shutdown(wait=False, cancel_futures=False)
        except Exception:
            logger.exception("learning writer shutdown failed")
