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
