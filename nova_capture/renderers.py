"""Render every class document from one LectureUnderstanding.

These are pure functions. No model is called here, which is the point: the
five study documents stop being five independent generations that can quietly
disagree with each other, and become five *views* of a single object.

That also makes a document template a real thing rather than a prompt string
buried in a dict -- a renderer is a function over a stable structure, so a
user-editable template becomes possible without touching generation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .understanding import LectureUnderstanding


DEGRADED_NOTE = (
    "> **Incomplete.** Some of this lecture could not be processed by a model. "
    "The raw transcript and audio remain authoritative.\n"
)


def _elapsed(seconds: float) -> str:
    total = max(0, int(float(seconds)))
    if total >= 3600:
        return f"{total // 3600:d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def _header(understanding: LectureUnderstanding, kind: str) -> list[str]:
    lines = [f"# {kind} — {understanding.title or 'Class Session'}", ""]
    if understanding.course:
        lines += [f"**Course:** {understanding.course}", ""]
    if understanding.degraded:
        lines.append(DEGRADED_NOTE)
        for warning in understanding.warnings():
            lines.append(f"> - {warning}")
        lines.append("")
    return lines


def _bullets(values: list[str], *, empty: str | None = None) -> list[str]:
    if not values:
        return [empty] if empty else []
    return [f"- {value}" for value in values]


def _section_block(section: Any, *, heading: str = "##") -> list[str]:
    span = f"[{_elapsed(section.start_seconds)}–{_elapsed(section.end_seconds)}]"
    lines = [f"{heading} {span} {section.label or 'Untitled section'}", ""]
    if section.thesis:
        lines += [section.thesis, ""]
    lines += _bullets(section.points)
    lines.append("")
    return lines


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


# --- the documents ----------------------------------------------------------


def render_lecture(understanding: LectureUnderstanding) -> str:
    lines = _header(understanding, "Lecture")
    if not understanding.sections:
        lines.append("_No lecture structure could be derived for this session._")
        return _finish(lines)

    lines += ["> Follows the lecture's own progression, in the order it happened.", ""]
    for section in understanding.sections:
        lines += _section_block(section)

    for title, values in (
        ("Definitions", understanding.definitions),
        ("Examples", understanding.examples),
        ("Assignments", understanding.assignments),
        ("Deadlines", understanding.deadlines),
    ):
        if values:
            lines += [f"## {title}", ""] + _bullets(values) + [""]
    return _finish(lines)


def render_summary(understanding: LectureUnderstanding) -> str:
    lines = _header(understanding, "Summary")
    if not understanding.sections:
        lines.append("_Nothing could be summarised for this session._")
        return _finish(lines)

    for section in understanding.sections:
        span = _elapsed(section.start_seconds)
        thesis = section.thesis or (section.points[0] if section.points else "")
        lines.append(f"- **[{span}] {section.label}** — {thesis}".rstrip(" —"))
    lines.append("")

    if understanding.assignments or understanding.deadlines:
        lines += ["## What you owe", ""]
        lines += _bullets(understanding.assignments + understanding.deadlines)
        lines.append("")
    return _finish(lines)


def render_study(understanding: LectureUnderstanding) -> str:
    lines = _header(understanding, "Study Guide")
    blocks = (
        ("Key concepts", understanding.definitions),
        ("Emphasised in class", understanding.emphasis),
        ("Likely exam material", understanding.exam_signals),
        ("Worked examples", understanding.examples),
        ("Assignments and deadlines",
         understanding.assignments + understanding.deadlines),
    )
    wrote = False
    for title, values in blocks:
        if values:
            wrote = True
            lines += [f"## {title}", ""] + _bullets(values) + [""]

    if understanding.review_priorities:
        wrote = True
        lines += [
            "## NOVA's review recommendations",
            "",
            "> NOVA's own suggestions, not the professor's words.",
            "",
        ] + _bullets(understanding.review_priorities) + [""]

    if not wrote:
        lines.append("_No study evidence could be extracted for this session._")
    return _finish(lines)


def render_questions(understanding: LectureUnderstanding) -> str:
    lines = _header(understanding, "Questions")
    if not understanding.qa:
        lines.append("_No questions were captured during this session._")
        return _finish(lines)

    lines += [
        "> Answers labelled NOVA are NOVA's in-class answers, not the "
        "professor's statements.",
        "",
    ]
    for item in understanding.qa:
        question = str(item.get("question") or "").strip()
        if not question:
            continue
        stamp = item.get("timestamp_seconds")
        prefix = f"[{_elapsed(stamp)}] " if isinstance(stamp, (int, float)) else ""
        lines += [f"## {prefix}{question}", ""]
        answer = str(item.get("answer") or "").strip()
        lines += [
            f"**NOVA:** {answer}" if answer else "_No answer was logged._",
            "",
        ]
    return _finish(lines)


def render_presentation_outline(understanding: LectureUnderstanding) -> str:
    lines = _header(understanding, "Presentation Outline")
    if not understanding.sections:
        lines.append("_No sections available to outline._")
        return _finish(lines)

    for index, section in enumerate(understanding.sections, start=1):
        lines += [f"## Slide {index}: {section.label or 'Untitled'}", ""]
        if section.thesis:
            lines += [section.thesis, ""]
        lines += _bullets(section.points[:5])
        lines.append("")

    if understanding.review_priorities:
        lines += [
            f"## Slide {len(understanding.sections) + 1}: What to review",
            "",
        ] + _bullets(understanding.review_priorities[:5]) + [""]
    return _finish(lines)


#: Filename -> renderer. Adding a document is adding an entry here; nothing
#: about generation changes, because generation already happened.
RENDERERS: dict[str, Callable[[LectureUnderstanding], str]] = {
    "Lecture.md": render_lecture,
    "Summary.md": render_summary,
    "Study.md": render_study,
    "Questions.md": render_questions,
    "Presentation Outline.md": render_presentation_outline,
}


def render_all(understanding: LectureUnderstanding) -> dict[str, str]:
    return {name: render(understanding) for name, render in RENDERERS.items()}
