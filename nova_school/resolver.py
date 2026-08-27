from __future__ import annotations

from datetime import datetime

from .registry import CourseProfile, CourseRegistry


def resolve_current_course(
    when: datetime | None = None,
    *,
    registry: CourseRegistry | None = None,
    buffer_minutes: int = 15,
) -> CourseProfile | None:
    """Return exactly one scheduled active course, otherwise None."""

    when = when or datetime.now().astimezone()
    registry = registry or CourseRegistry()
    matches = [
        course
        for course in registry.load()
        if course.active
        and any(
            meeting.contains(when, buffer_minutes=buffer_minutes)
            for meeting in course.meetings
        )
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_course_override(
    override: str | None,
    *,
    registry: CourseRegistry | None = None,
) -> CourseProfile | None:
    if not override or not override.strip():
        return None
    return (registry or CourseRegistry()).get(override)


def _compact_course_token(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _split_course_token(value: str) -> tuple[str, str]:
    token = _compact_course_token(value)
    letters = "".join(ch for ch in token if ch.isalpha())
    digits = "".join(ch for ch in token if ch.isdigit())
    return letters, digits


def resolve_requested_course(
    value: str | None,
    *,
    registry: CourseRegistry | None = None,
) -> CourseProfile | None:
    """Resolve an explicit user course request independent of meeting time.

    Resolution is deliberately conservative:
    1. exact canonical course code (spacing/hyphens ignored)
    2. exact registered alias/name
    3. unique numeric suffix (e.g. ``3400`` when only one active course matches)
    4. unique one-letter STT correction when the numeric suffix is exact

    The schedule is never consulted here. An explicit user instruction is
    authority to start that known course at any time of day.
    """

    if not value or not value.strip():
        return None

    registry = registry or CourseRegistry()
    courses = [course for course in registry.load() if course.active]

    # Existing canonical lookup already ignores separators/case.
    exact = registry.get(value)
    if exact is not None and exact.active:
        return exact

    needle = _compact_course_token(value)
    if not needle:
        return None

    # Registered course names and aliases are authoritative vocabulary too.
    for course in courses:
        names = [course.name, *course.aliases]
        if any(_compact_course_token(name) == needle for name in names if name):
            return course

    requested_letters, requested_digits = _split_course_token(value)
    if not requested_digits:
        return None

    # "3400" is safe only if exactly one active course has that suffix.
    if not requested_letters:
        numeric_matches = []
        for course in courses:
            _, digits = _split_course_token(course.code)
            if digits == requested_digits:
                numeric_matches.append(course)
        return numeric_matches[0] if len(numeric_matches) == 1 else None

    # Handle common speech-to-text slips such as COG3400 -> COT3400, but only
    # when the number is exact and there is exactly one one-letter candidate.
    fuzzy_matches = []
    for course in courses:
        letters, digits = _split_course_token(course.code)
        if digits != requested_digits or len(letters) != len(requested_letters):
            continue
        substitutions = sum(a != b for a, b in zip(letters, requested_letters))
        if substitutions <= 1:
            fuzzy_matches.append(course)

    return fuzzy_matches[0] if len(fuzzy_matches) == 1 else None
