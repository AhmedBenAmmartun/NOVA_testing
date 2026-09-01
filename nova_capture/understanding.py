"""One structured understanding of a lecture, built by map/reduce.

Post-class generation used to send the *same* ~32,000-character evidence
bundle to the model five separate times, once per output document. On
2026-08-28 that failed completely against a real CEN4934 class: every prompt
was ~8,000 tokens, the local model was serving a 2,048-token window, and all
five documents silently fell back to an evidence dump while
``postprocess.json`` still reported ``"completed"``.

The fix is not a bigger context window -- it is a smaller prompt:

    lecture sections (already derived, no model)
        -> windows of ~8k chars that never cross a section boundary
        -> MAP:    one small call per window   (~2k tokens each)
        -> REDUCE: per-section calls, hierarchical only when a section is large
        -> GLOBAL: one bounded study-list pass
        -> LectureUnderstanding
        -> RENDER: pure Python, zero model calls

Measured end to end on that same 107-minute class:

    before   8 evidence + 5 documents = 13 calls, ~64,000 tok, largest 8,000
    after   15 map + bounded section/global reduces, with no oversized request

The part that actually mattered was bounding every individual request. Map
windows fit a stock Ollama context; reduce requests are checked against the
provider envelope and recursively subdivided when one semantic topic runs long.

Two properties matter as much as the token count:

* every document is now a *view* of one object, so they cannot contradict
  each other the way five independent generations could; and
* a window that fails costs one window, not a whole document, and it is
  recorded in ``degraded_windows`` so the session can report the truth.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from .evidence import (
    EvidenceKind,
    LectureSection,
    SessionEvidence,
    derive_lecture_structure,
)


logger = logging.getLogger("nova.class_capture.understanding")

#: Characters of transcript per map call. Measured against the real CEN4934
#: lecture, counting the *whole* prompt including the instruction block: 7,000
#: characters yields a largest prompt of ~1,916 tokens, safely under the
#: 2,048-token default an unconfigured Ollama serves. 7,500 also fits at 2,042
#: but leaves no headroom for a denser window; 8,000 does not fit at all.
#: Smaller windows cost more calls for no accuracy gain.
WINDOW_CHARS = 7_000

#: Cap on how much of a window digest is carried into the reduce prompt.
DIGEST_ITEM_LIMIT = 12

#: How many times a window is retried before it is written off. Provider rate
#: limits are transient; a single attempt turns a throttle into lost lecture.
DEFAULT_WINDOW_ATTEMPTS = 3

#: Pause between attempts. Sized for a per-minute token limit, which is the
#: real constraint on a free provider tier.
DEFAULT_RETRY_DELAY_SECONDS = 20.0

#: Conservative request envelope for the weakest production provider currently
#: used by Class Intelligence. Groq's free ``openai/gpt-oss-120b`` path rejects
#: a request before generation when input + reserved output crosses 8,000 TPM.
#: Keeping the invariant here prevents a future long semantic section from
#: recreating that failure even when the lecture itself is much longer.
DEFAULT_REQUEST_TOKEN_LIMIT = 8_000
DEFAULT_RESERVED_OUTPUT_TOKENS = 4_000
DEFAULT_REQUEST_SAFETY_MARGIN_TOKENS = 500

#: No provider tokenizer is available at this layer. 3.5 chars/token is a
#: deliberately conservative estimate for English lecture digests; the extra
#: safety margin above absorbs denser punctuation/JSON/tokenization.
ESTIMATED_CHARS_PER_TOKEN = 3.5

#: Hierarchical summaries are deliberately compact so recursive reduction
#: converges instead of repeatedly feeding the same oversized material upward.
HIERARCHY_THESIS_CHARS = 800
HIERARCHY_POINT_CHARS = 500
HIERARCHY_MAX_DEPTH = 12

UNDERSTANDING_NAME = "understanding.json"
SCHEMA_VERSION = 1

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

#: The evidence categories a window digest carries. Kept as one tuple so the
#: prompt, the parser, and the dataclass can never drift apart.
DIGEST_FIELDS = (
    "points",
    "definitions",
    "examples",
    "assignments",
    "deadlines",
    "exam_signals",
    "emphasis",
)

RouteFn = Callable[[str], Awaitable[str | None]]


def _clean(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def _clean_list(values: Any, *, limit: int = 40) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = _clean(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _elapsed(seconds: float) -> str:
    total = max(0, int(float(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _parse_json_object(text: str | None) -> dict[str, Any] | None:
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


# --- the model -------------------------------------------------------------


@dataclass(slots=True)
class TranscriptWindow:
    """One stretch of lecture small enough for a single small model call."""

    index: int
    section_id: str
    section_label: str
    start_seconds: float
    end_seconds: float
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass(slots=True)
class WindowDigest:
    """What the model understood from one window. Timestamps are real."""

    index: int
    section_id: str
    section_label: str
    start_seconds: float
    end_seconds: float
    thesis: str = ""
    points: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    deadlines: list[str] = field(default_factory=list)
    exam_signals: list[str] = field(default_factory=list)
    emphasis: list[str] = field(default_factory=list)
    degraded: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "section_id": self.section_id,
            "section_label": self.section_label,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "thesis": self.thesis,
            "degraded": self.degraded,
        }
        for name in DIGEST_FIELDS:
            payload[name] = list(getattr(self, name))
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WindowDigest":
        digest = cls(
            index=int(payload.get("index", 0) or 0),
            section_id=str(payload.get("section_id", "")),
            section_label=str(payload.get("section_label", "")),
            start_seconds=float(payload.get("start_seconds", 0.0) or 0.0),
            end_seconds=float(payload.get("end_seconds", 0.0) or 0.0),
            thesis=_clean(payload.get("thesis", "")),
            degraded=bool(payload.get("degraded", False)),
        )
        for name in DIGEST_FIELDS:
            setattr(digest, name, _clean_list(payload.get(name)))
        return digest


@dataclass(slots=True)
class SectionUnderstanding:
    """A topic section of the lecture, with the professor's line of argument."""

    section_id: str
    label: str
    start_seconds: float
    end_seconds: float
    thesis: str = ""
    points: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "label": self.label,
            "start_seconds": round(self.start_seconds, 3),
            "end_seconds": round(self.end_seconds, 3),
            "thesis": self.thesis,
            "points": list(self.points),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SectionUnderstanding":
        return cls(
            section_id=str(payload.get("section_id", "")),
            label=_clean(payload.get("label", "")),
            start_seconds=float(payload.get("start_seconds", 0.0) or 0.0),
            end_seconds=float(payload.get("end_seconds", 0.0) or 0.0),
            thesis=_clean(payload.get("thesis", "")),
            points=_clean_list(payload.get("points")),
        )


@dataclass(slots=True)
class LectureUnderstanding:
    """The single object every generated document is rendered from."""

    course: str = ""
    title: str = ""
    session_id: str = ""
    sections: list[SectionUnderstanding] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    deadlines: list[str] = field(default_factory=list)
    exam_signals: list[str] = field(default_factory=list)
    emphasis: list[str] = field(default_factory=list)
    review_priorities: list[str] = field(default_factory=list)
    qa: list[dict[str, Any]] = field(default_factory=list)
    windows: list[WindowDigest] = field(default_factory=list)
    #: Windows the model could not digest. Non-empty means the outputs are
    #: incomplete and the session must NOT report a clean completion.
    degraded_windows: list[int] = field(default_factory=list)
    #: True when the reduce call failed and the sections were assembled
    #: deterministically from the window digests instead.
    reduce_degraded: bool = False
    generated_at: str = ""
    schema_version: int = SCHEMA_VERSION

    @property
    def degraded(self) -> bool:
        return bool(self.degraded_windows) or self.reduce_degraded

    @property
    def has_content(self) -> bool:
        return bool(self.sections or self.definitions or self.examples)

    def warnings(self) -> list[str]:
        notes: list[str] = []
        if self.degraded_windows:
            notes.append(
                f"{len(self.degraded_windows)} of {len(self.windows)} lecture "
                "window(s) could not be digested by a model"
            )
        if self.reduce_degraded:
            notes.append(
                "cross-section synthesis was unavailable; sections were "
                "assembled directly from the window digests"
            )
        return notes

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "layer": "working_intelligence",
            "generated_at": self.generated_at,
            "course": self.course,
            "title": self.title,
            "session_id": self.session_id,
            "sections": [item.as_dict() for item in self.sections],
            "definitions": list(self.definitions),
            "examples": list(self.examples),
            "assignments": list(self.assignments),
            "deadlines": list(self.deadlines),
            "exam_signals": list(self.exam_signals),
            "emphasis": list(self.emphasis),
            "review_priorities": list(self.review_priorities),
            "qa": list(self.qa),
            "windows": [item.as_dict() for item in self.windows],
            "degraded_windows": list(self.degraded_windows),
            "reduce_degraded": self.reduce_degraded,
            "warnings": self.warnings(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LectureUnderstanding":
        return cls(
            course=str(payload.get("course", "")),
            title=str(payload.get("title", "")),
            session_id=str(payload.get("session_id", "")),
            sections=[
                SectionUnderstanding.from_dict(item)
                for item in payload.get("sections", [])
                if isinstance(item, dict)
            ],
            definitions=_clean_list(payload.get("definitions")),
            examples=_clean_list(payload.get("examples")),
            assignments=_clean_list(payload.get("assignments")),
            deadlines=_clean_list(payload.get("deadlines")),
            exam_signals=_clean_list(payload.get("exam_signals")),
            emphasis=_clean_list(payload.get("emphasis")),
            review_priorities=_clean_list(payload.get("review_priorities")),
            qa=[item for item in payload.get("qa", []) if isinstance(item, dict)],
            windows=[
                WindowDigest.from_dict(item)
                for item in payload.get("windows", [])
                if isinstance(item, dict)
            ],
            degraded_windows=[
                int(value) for value in payload.get("degraded_windows", [])
            ],
            reduce_degraded=bool(payload.get("reduce_degraded", False)),
            generated_at=str(payload.get("generated_at", "")),
            schema_version=int(payload.get("schema_version", SCHEMA_VERSION)),
        )


# --- planning --------------------------------------------------------------


def plan_windows(
    evidence: SessionEvidence,
    *,
    window_chars: int = WINDOW_CHARS,
    sections: list[LectureSection] | None = None,
) -> list[TranscriptWindow]:
    """Split the lecture into model-sized windows along its own structure.

    Windows never cross a section boundary, so a digest is always about one
    topic. Splitting by section *alone* is not enough -- the real CEN4934
    lecture had 36- and 48-minute sections, far past any small model's
    context -- so each section is then windowed by size.
    """
    budget = max(1_000, int(window_chars))
    structure = sections if sections is not None else derive_lecture_structure(evidence)
    transcript = [
        item for item in evidence.items if item.kind is EvidenceKind.TRANSCRIPT
    ]

    windows: list[TranscriptWindow] = []
    for section in structure:
        inside = [
            item
            for item in transcript
            if section.start_seconds <= item.start_seconds <= section.end_seconds
        ]
        if not inside:
            continue

        current: list[str] = []
        length = 0
        start = inside[0].start_seconds
        previous_end = start

        def flush(end_seconds: float) -> None:
            if not current:
                return
            windows.append(
                TranscriptWindow(
                    index=len(windows),
                    section_id=section.section_id,
                    section_label=section.label,
                    start_seconds=start,
                    end_seconds=end_seconds,
                    text="\n".join(current),
                )
            )

        for item in inside:
            label = evidence.speaker_label(item.speaker_id) or "Speaker"
            line = f"[{_elapsed(item.start_seconds)}] {label}: {item.text.strip()}"
            if current and length + len(line) + 1 > budget:
                flush(previous_end)
                current, length = [], 0
                start = item.start_seconds
            current.append(line)
            length += len(line) + 1
            previous_end = item.end_seconds or item.start_seconds

        flush(previous_end)

    return windows


# --- map -------------------------------------------------------------------


def build_window_prompt(window: TranscriptWindow, course: str) -> str:
    return f"""Extract grounded study evidence from ONE stretch of a {course} lecture.

SECTION: {window.section_label}
TIME: {_elapsed(window.start_seconds)}-{_elapsed(window.end_seconds)}

Return ONLY one JSON object with these keys:
"thesis": one sentence saying what this stretch is actually about,
"points": the substantive things said, in the order they were said,
"definitions", "examples", "assignments", "deadlines", "exam_signals", "emphasis":
arrays of short strings.

Every item must be directly supported by the transcript below. Do not invent a
statement, deadline, policy, or definition that is not there. Use an empty array
for a category that does not appear. Preserve technical terminology exactly.

TRANSCRIPT:
{window.text}"""


def parse_window_digest(
    window: TranscriptWindow, text: str | None
) -> WindowDigest:
    """Turn a model reply into a digest, marking it degraded if unusable."""
    digest = WindowDigest(
        index=window.index,
        section_id=window.section_id,
        section_label=window.section_label,
        start_seconds=window.start_seconds,
        end_seconds=window.end_seconds,
    )
    payload = _parse_json_object(text)
    if payload is None:
        digest.degraded = True
        return digest

    digest.thesis = _clean(payload.get("thesis", ""))
    for name in DIGEST_FIELDS:
        setattr(digest, name, _clean_list(payload.get(name)))

    if not digest.thesis and not any(
        getattr(digest, name) for name in DIGEST_FIELDS
    ):
        # Valid JSON that says nothing is still a failed window.
        digest.degraded = True
    return digest


# --- reduce ----------------------------------------------------------------


#: Course-material excerpt carried into the reduce prompt. Small on purpose:
#: reduce is the only stage that sees the whole lecture, so it is the only
#: place materials can help, but it must stay inside the same token budget.
MATERIALS_BUDGET_CHARS = 4_000


def build_section_reduce_prompt(
    digests: list[WindowDigest], *, course: str, section_label: str
) -> str:
    """Build one section-reduce prompt.

    The caller enforces the provider request envelope. Typical sections fit in
    one call; an unusually long single topic is subdivided hierarchically before
    any oversized request is sent.
    """
    parts: list[str] = []
    for digest in digests:
        if digest.degraded:
            continue
        block = [
            f"### window {digest.index} "
            f"[{_elapsed(digest.start_seconds)}-{_elapsed(digest.end_seconds)}]"
        ]
        if digest.thesis:
            block.append(f"thesis: {digest.thesis}")
        for name in DIGEST_FIELDS:
            values = getattr(digest, name)[:DIGEST_ITEM_LIMIT]
            if values:
                block.append(f"{name}: " + " | ".join(values))
        parts.append("\n".join(block))

    return f"""Compose the notes for ONE section of a {course} lecture from its
ordered window digests. Section as recorded: "{section_label}"

Return ONLY one JSON object:
{{"sections": [{{"label": "...", "thesis": "...", "points": ["..."],
                "windows": [0, 1]}}]}}

Rules:
- Usually ONE section. Split into several only if this stretch genuinely
  covered separate topics, and give each a real label.
- "windows" MUST list the window numbers each section draws from; it is how the
  section is placed in time.
- "points" are the substantive things said, in the order they were said. Merge
  duplicates across windows and keep the clearest wording.
- Never invent anything absent from the digests.

WINDOW DIGESTS:
{chr(10).join(parts) if parts else "(none available)"}"""



def estimate_prompt_tokens(prompt: str) -> int:
    """Conservatively estimate prompt tokens without a provider tokenizer.

    ASCII lecture text uses the measured chars/token heuristic. Non-ASCII text
    is budgeted at one token per code point so Arabic or other multilingual
    content cannot be dangerously underestimated by an English-only ratio.
    """
    if not prompt:
        return 0
    ascii_chars = sum(1 for character in prompt if ord(character) < 128)
    non_ascii_chars = len(prompt) - ascii_chars
    estimated = ascii_chars / ESTIMATED_CHARS_PER_TOKEN + non_ascii_chars
    return max(1, math.ceil(estimated))


def request_fits_budget(
    prompt: str,
    *,
    request_token_limit: int = DEFAULT_REQUEST_TOKEN_LIMIT,
    reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS,
    safety_margin_tokens: int = DEFAULT_REQUEST_SAFETY_MARGIN_TOKENS,
) -> bool:
    """Return True only when the complete request fits the configured envelope."""
    limit = max(1, int(request_token_limit))
    reserved = max(0, int(reserved_output_tokens))
    margin = max(0, int(safety_margin_tokens))
    return estimate_prompt_tokens(prompt) + reserved + margin <= limit


def _fallback_sections_for_group(
    digests: list[WindowDigest], *, section_label: str
) -> list[SectionUnderstanding]:
    """Deterministically preserve one reduce group when model synthesis fails."""
    usable = [digest for digest in digests if not digest.degraded]
    if not usable:
        return []

    thesis = next((digest.thesis for digest in usable if digest.thesis), "")
    points: list[str] = []
    for digest in usable:
        points.extend(digest.points)
    cleaned_points = _clean_list(points, limit=60)
    if not (thesis or cleaned_points):
        return []

    return [
        SectionUnderstanding(
            section_id=usable[0].section_id,
            label=section_label or usable[0].section_label,
            start_seconds=min(digest.start_seconds for digest in usable),
            end_seconds=max(digest.end_seconds for digest in usable),
            thesis=thesis,
            points=cleaned_points,
        )
    ]


def _split_section_group_for_budget(
    digests: list[WindowDigest],
    *,
    course: str,
    section_label: str,
    request_token_limit: int,
    reserved_output_tokens: int,
    safety_margin_tokens: int,
) -> list[list[WindowDigest]]:
    """Greedily split a section into contiguous request-sized groups."""
    groups: list[list[WindowDigest]] = []
    current: list[WindowDigest] = []

    for digest in digests:
        candidate = [*current, digest]
        prompt = build_section_reduce_prompt(
            candidate, course=course, section_label=section_label
        )
        if current and not request_fits_budget(
            prompt,
            request_token_limit=request_token_limit,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
        ):
            groups.append(current)
            current = [digest]
        else:
            current = candidate

    if current:
        groups.append(current)
    return groups


def _clip_for_hierarchy(value: str, limit: int) -> str:
    cleaned = _clean(value)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(1, limit - 1)].rstrip() + "…"


def _sections_as_hierarchy_digests(
    sections: list[SectionUnderstanding], *, section_id: str, section_label: str
) -> list[WindowDigest]:
    """Compress child reductions into bounded digests for the parent level."""
    out: list[WindowDigest] = []
    for index, section in enumerate(sections):
        out.append(
            WindowDigest(
                index=index,
                section_id=section_id,
                section_label=section_label,
                start_seconds=section.start_seconds,
                end_seconds=section.end_seconds,
                thesis=_clip_for_hierarchy(section.thesis, HIERARCHY_THESIS_CHARS),
                points=[
                    _clip_for_hierarchy(point, HIERARCHY_POINT_CHARS)
                    for point in section.points[:DIGEST_ITEM_LIMIT]
                ],
            )
        )
    return out


async def _reduce_section_group(
    route: RouteFn,
    digests: list[WindowDigest],
    *,
    course: str,
    section_label: str,
    max_attempts: int,
    retry_delay_seconds: float,
    request_token_limit: int,
    reserved_output_tokens: int,
    safety_margin_tokens: int,
    depth: int = 0,
) -> tuple[list[SectionUnderstanding], bool]:
    """Reduce one semantic section without ever sending an oversized request.

    Normal sections take the exact same one-call path as before. If the request
    envelope would be exceeded, contiguous child groups are reduced first and
    their compact summaries are reduced again. The boolean reports whether the
    full hierarchy was model-reduced; False means some deterministic fallback
    was required.
    """
    usable = [digest for digest in digests if not digest.degraded]
    if not usable:
        return [], False
    if depth >= HIERARCHY_MAX_DEPTH:
        logger.error(
            "section %r exceeded hierarchical reduce depth; using deterministic fallback",
            section_label,
        )
        return _fallback_sections_for_group(usable, section_label=section_label), False

    prompt = build_section_reduce_prompt(
        usable, course=course, section_label=section_label
    )
    if request_fits_budget(
        prompt,
        request_token_limit=request_token_limit,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    ):
        reply = await _route_with_retry(
            route,
            prompt,
            what=f"section {section_label!r}",
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
        payload = _parse_json_object(reply)
        produced = _sections_from_payload(payload, usable) if payload else []
        if produced:
            return produced, True
        return _fallback_sections_for_group(usable, section_label=section_label), False

    if len(usable) == 1:
        logger.warning(
            "section %r has one oversized digest (~%s input tokens); "
            "not sending it to the provider",
            section_label,
            estimate_prompt_tokens(prompt),
        )
        return _fallback_sections_for_group(usable, section_label=section_label), False

    chunks = _split_section_group_for_budget(
        usable,
        course=course,
        section_label=section_label,
        request_token_limit=request_token_limit,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )
    # Defensive progress guarantee: if an estimation change ever leaves the
    # whole oversized group intact, split it in half rather than recurse forever.
    if len(chunks) == 1 and len(chunks[0]) == len(usable):
        midpoint = max(1, len(usable) // 2)
        chunks = [usable[:midpoint], usable[midpoint:]]

    logger.info(
        "section %r exceeds request budget; reducing %s windows as %s child groups",
        section_label,
        len(usable),
        len(chunks),
    )

    child_sections: list[SectionUnderstanding] = []
    fully_reduced = True
    for chunk in chunks:
        produced, reduced = await _reduce_section_group(
            route,
            chunk,
            course=course,
            section_label=section_label,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            request_token_limit=request_token_limit,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
            depth=depth + 1,
        )
        child_sections.extend(produced)
        fully_reduced = fully_reduced and reduced

    if not child_sections:
        return _fallback_sections_for_group(usable, section_label=section_label), False

    summaries = _sections_as_hierarchy_digests(
        child_sections,
        section_id=usable[0].section_id,
        section_label=section_label,
    )
    if len(summaries) == 1:
        return child_sections, fully_reduced

    merged, parent_reduced = await _reduce_section_group(
        route,
        summaries,
        course=course,
        section_label=section_label,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        request_token_limit=request_token_limit,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
        depth=depth + 1,
    )
    if not merged:
        return child_sections, False
    return merged, fully_reduced and parent_reduced


def build_global_reduce_prompt(
    sections: list[SectionUnderstanding],
    *,
    course: str,
    title: str,
    materials: str = "",
) -> str:
    """Collect the cross-cutting study lists from the finished sections."""
    parts = []
    for section in sections:
        block = [
            f"### [{_elapsed(section.start_seconds)}-"
            f"{_elapsed(section.end_seconds)}] {section.label}"
        ]
        if section.thesis:
            block.append(section.thesis)
        block.extend(f"- {point}" for point in section.points[:DIGEST_ITEM_LIMIT])
        parts.append("\n".join(block))

    return f"""Collect the study material of a {course} lecture. Session: {title}

Return ONLY one JSON object:
{{"definitions": ["..."], "examples": ["..."], "assignments": ["..."],
  "deadlines": ["..."], "exam_signals": ["..."], "emphasis": ["..."],
  "review_priorities": ["..."]}}

Rules:
- Every item must be supported by the sections below. Never invent a deadline,
  policy, definition or exam hint.
- "review_priorities" is the only place NOVA's own study advice belongs.
- Course materials are supporting context only; the lecture is primary and a
  material never overrides what was actually said.
- Use an empty array for a category the lecture did not contain.

LECTURE SECTIONS:
{chr(10).join(parts) if parts else "(none available)"}

COURSE MATERIAL EXCERPTS:
{materials[:MATERIALS_BUDGET_CHARS] if materials else "(none available)"}"""


def understanding_from_digests(
    digests: list[WindowDigest],
    *,
    course: str,
    title: str,
    session_id: str,
) -> LectureUnderstanding:
    """Assemble an understanding with no model at all.

    This is the graceful-degradation path: if the reduce call fails, the
    window digests are still real work and must not be thrown away.
    """
    understanding = LectureUnderstanding(
        course=course,
        title=title,
        session_id=session_id,
        windows=list(digests),
        degraded_windows=[item.index for item in digests if item.degraded],
        reduce_degraded=True,
    )

    by_section: dict[str, SectionUnderstanding] = {}
    for digest in digests:
        if digest.degraded:
            continue
        section = by_section.get(digest.section_id)
        if section is None:
            section = SectionUnderstanding(
                section_id=digest.section_id,
                label=digest.section_label,
                start_seconds=digest.start_seconds,
                end_seconds=digest.end_seconds,
                thesis=digest.thesis,
            )
            by_section[digest.section_id] = section
        section.end_seconds = max(section.end_seconds, digest.end_seconds)
        if not section.thesis:
            section.thesis = digest.thesis
        section.points.extend(digest.points)

    understanding.sections = sorted(
        by_section.values(), key=lambda item: item.start_seconds
    )
    for name in ("definitions", "examples", "assignments", "deadlines",
                 "exam_signals", "emphasis"):
        merged: list[str] = []
        for digest in digests:
            if not digest.degraded:
                merged.extend(getattr(digest, name))
        setattr(understanding, name, _clean_list(merged, limit=60))
    return understanding


async def _route_with_retry(
    route: RouteFn,
    prompt: str,
    *,
    what: str,
    max_attempts: int,
    retry_delay_seconds: float,
) -> str | None:
    """Ask the model, retrying a transient refusal.

    The dominant real failure is a provider rate limit -- Groq's free tier
    allows 8,000 tokens per MINUTE and bills the reserved output against it, so
    calls fired back to back are throttled by design rather than broken.
    Waiting is the correct response, and it self-paces the run.
    """
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            reply = await route(prompt)
        except Exception:
            logger.exception("%s failed", what)
            reply = None
        if reply:
            return reply
        if attempt < attempts:
            logger.warning(
                "%s produced nothing on attempt %s; waiting %.0fs",
                what,
                attempt,
                retry_delay_seconds,
            )
            await asyncio.sleep(max(0.0, float(retry_delay_seconds)))
    return None


def _sections_from_payload(
    payload: dict[str, Any], digests: list[WindowDigest]
) -> list[SectionUnderstanding]:
    """Place model-proposed sections in time using the windows they cite."""
    raw = payload.get("sections")
    if not isinstance(raw, list):
        return []

    by_index = {digest.index: digest for digest in digests}
    ordered = list(digests)
    sections: list[SectionUnderstanding] = []
    #: One section for the whole group means it covers the whole group, whatever
    #: it cited. Models routinely cite only the first window, which collapsed a
    #: 36-minute section of the real CEN4934 lecture to "0:00-5:32". Citations
    #: only need to disambiguate when the group was actually split.
    single = len([item for item in raw if isinstance(item, dict)]) == 1

    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        # Prefer the windows the model actually cited. The model is allowed to
        # subdivide a derived section -- the real lecture had a 36-minute block
        # covering three distinct student projects -- and without citations
        # every one of those claimed the same span.
        cited = [
            by_index[int(value)]
            for value in (item.get("windows") or [])
            if isinstance(value, (int, float)) and int(value) in by_index
        ]
        if single or not cited:
            cited = ordered if single else (
                [ordered[position]] if position < len(ordered) else ordered
            )
        if not cited:
            continue

        points = _clean_list(item.get("points"), limit=60)
        label = _clean(item.get("label", "")) or cited[0].section_label
        thesis = _clean(item.get("thesis", ""))
        if not (points or thesis):
            continue

        sections.append(
            SectionUnderstanding(
                section_id=cited[0].section_id,
                label=label,
                start_seconds=min(d.start_seconds for d in cited),
                end_seconds=max(d.end_seconds for d in cited),
                thesis=thesis,
                points=points,
            )
        )
    return sections


async def build_understanding(
    evidence: SessionEvidence,
    *,
    route: RouteFn,
    window_chars: int = WINDOW_CHARS,
    questions: list[dict[str, Any]] | None = None,
    materials: str = "",
    max_attempts: int = DEFAULT_WINDOW_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    request_token_limit: int = DEFAULT_REQUEST_TOKEN_LIMIT,
    reserved_output_tokens: int = DEFAULT_RESERVED_OUTPUT_TOKENS,
    safety_margin_tokens: int = DEFAULT_REQUEST_SAFETY_MARGIN_TOKENS,
) -> LectureUnderstanding:
    """Map every window, then reduce them into one understanding.

    ``route`` is injected so this is testable without a model, and so the
    caller keeps ownership of provider selection and budget.
    """
    windows = plan_windows(evidence, window_chars=window_chars)
    digests: list[WindowDigest] = []

    for window in windows:
        digest = parse_window_digest(window, None)
        prompt = build_window_prompt(window, evidence.course)
        if not request_fits_budget(
            prompt,
            request_token_limit=request_token_limit,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
        ):
            logger.error(
                "lecture window %s exceeds request budget (~%s input tokens); "
                "not sending it to the provider",
                window.index,
                estimate_prompt_tokens(prompt),
            )
            digests.append(digest)
            continue

        attempts = max(1, int(max_attempts))
        for attempt in range(1, attempts + 1):
            try:
                reply = await route(prompt)
            except Exception:
                logger.exception("lecture window %s failed", window.index)
                reply = None

            digest = parse_window_digest(window, reply)
            if not digest.degraded:
                break
            if attempt < attempts:
                logger.warning(
                    "lecture window %s degraded on attempt %s; waiting %.0fs",
                    window.index,
                    attempt,
                    retry_delay_seconds,
                )
                await asyncio.sleep(max(0.0, float(retry_delay_seconds)))

        digests.append(digest)

    understanding = understanding_from_digests(
        digests,
        course=evidence.course,
        title=evidence.title,
        session_id=evidence.session_id,
    )
    understanding.qa = list(questions or [])
    understanding.generated_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    if not windows:
        # A session with no transcript has nothing to digest. Nothing failed,
        # so this is a clean empty result -- not a degraded one. Reporting
        # warnings here would cry wolf on every empty session.
        understanding.reduce_degraded = False
        return understanding

    usable = [item for item in digests if not item.degraded]
    if not usable:
        # Nothing to synthesise. The caller still gets a truthful, empty
        # understanding rather than an exception.
        return understanding

    # Reduce one SECTION at a time. A single reduce over the whole lecture
    # cannot scale -- 15 windows already exceeded the provider's per-minute
    # token limit, and a three-hour class has more.
    by_section: dict[str, list[WindowDigest]] = {}
    for digest in usable:
        by_section.setdefault(digest.section_id, []).append(digest)

    sections: list[SectionUnderstanding] = []
    all_sections_reduced = True
    for group in by_section.values():
        produced, reduced = await _reduce_section_group(
            route,
            group,
            course=evidence.course,
            section_label=group[0].section_label,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            request_token_limit=request_token_limit,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin_tokens=safety_margin_tokens,
        )
        all_sections_reduced = all_sections_reduced and reduced
        if produced:
            sections.extend(produced)
        else:
            sections.extend(
                item for item in understanding.sections
                if item.section_id == group[0].section_id
            )
            all_sections_reduced = False

    if sections:
        sections.sort(key=lambda item: item.start_seconds)
        understanding.sections = sections
    understanding.reduce_degraded = not all_sections_reduced

    # One small final pass for the cross-cutting study lists. Never send it if
    # an unusually section-heavy lecture would exceed the same request envelope;
    # the deterministic lists already assembled from window digests remain valid.
    global_prompt = build_global_reduce_prompt(
        understanding.sections,
        course=evidence.course,
        title=evidence.title,
        materials=materials,
    )
    if request_fits_budget(
        global_prompt,
        request_token_limit=request_token_limit,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    ):
        reply = await _route_with_retry(
            route,
            global_prompt,
            what="lecture study lists",
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
        )
        payload = _parse_json_object(reply)
        if payload is not None:
            for name in ("definitions", "examples", "assignments", "deadlines",
                         "exam_signals", "emphasis", "review_priorities"):
                values = _clean_list(payload.get(name), limit=60)
                if values:
                    setattr(understanding, name, values)
        else:
            understanding.reduce_degraded = True
    else:
        logger.warning(
            "global study-list reduce exceeds request budget (~%s input tokens); "
            "keeping deterministic study lists",
            estimate_prompt_tokens(global_prompt),
        )
        understanding.reduce_degraded = True

    return understanding


# --- persistence -----------------------------------------------------------


def write_understanding(
    session_path: str | Path, understanding: LectureUnderstanding
) -> Path:
    path = Path(session_path) / UNDERSTANDING_NAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(understanding.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def load_understanding(session_path: str | Path) -> LectureUnderstanding | None:
    path = Path(session_path) / UNDERSTANDING_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return LectureUnderstanding.from_dict(payload)
