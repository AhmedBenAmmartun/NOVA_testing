from __future__ import annotations

from pathlib import Path
import re

from .models import CourseClassification, CourseDescriptor


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def classify_course(
    source_name: str,
    extracted_text: str,
    courses: list[CourseDescriptor] | tuple[CourseDescriptor, ...],
    *,
    active_course_hint: str | None = None,
    auto_threshold: float = 0.82,
    review_threshold: float = 0.45,
) -> CourseClassification:
    if not courses:
        return CourseClassification(None, 0.0, "reject", ["No active course catalog was provided."])

    filename = Path(source_name).stem
    filename_norm = _norm(filename)
    filename_compact = _compact(filename)
    text_norm = _norm(extracted_text[:120_000])
    hint = _compact(active_course_hint or "")

    scored: list[tuple[str, float, list[str]]] = []
    for course in courses:
        score = 0.0
        reasons: list[str] = []
        code_compact = _compact(course.code)
        code_norm = _norm(course.code)

        if code_compact and code_compact in filename_compact:
            score += 0.72
            reasons.append("course code appears in filename")
        elif code_norm and code_norm in filename_norm:
            score += 0.65
            reasons.append("course code appears in filename")

        for token in course.tokens()[1:]:
            token_norm = _norm(token)
            token_compact = _compact(token)
            if len(token_compact) < 4:
                continue
            if token_compact in filename_compact or token_norm in filename_norm:
                score += 0.32
                reasons.append(f"course alias/title appears in filename: {token}")
                break

        if code_compact and code_compact in _compact(text_norm):
            score += 0.28
            reasons.append("course code appears in extracted material text")

        text_hits = 0
        for token in course.tokens()[1:]:
            token_norm = _norm(token)
            if len(token_norm) >= 5 and token_norm in text_norm:
                text_hits += 1
        if text_hits:
            score += min(0.24, 0.10 + 0.05 * text_hits)
            reasons.append("course name/aliases appear in extracted material text")

        if hint and hint == code_compact:
            score += 0.12
            reasons.append("matches active-course hint")

        scored.append((course.code, min(score, 1.0), reasons))

    scored.sort(key=lambda item: (-item[1], item[0]))
    best_code, best_score, reasons = scored[0]
    alternatives = [(code, score) for code, score, _ in scored[1:4] if score > 0]
    second = alternatives[0][1] if alternatives else 0.0
    margin = best_score - second

    if best_score >= auto_threshold and margin >= 0.18:
        disposition = "auto_import"
    elif best_score >= review_threshold:
        disposition = "pending_review"
        if margin < 0.18 and alternatives:
            reasons.append("classification is too close to another course")
    else:
        disposition = "pending_review"
        reasons.append("insufficient evidence for automatic course selection")

    return CourseClassification(best_code if best_score > 0 else None, best_score, disposition, reasons, alternatives)
