from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Iterable

from .paths import school_runtime_root


_DAY_ALIASES = {
    "monday": 0, "mon": 0, "mo": 0,
    "tuesday": 1, "tue": 1, "tu": 1,
    "wednesday": 2, "wed": 2, "we": 2,
    "thursday": 3, "thu": 3, "th": 3,
    "friday": 4, "fri": 4, "fr": 4,
    "saturday": 5, "sat": 5, "sa": 5,
    "sunday": 6, "sun": 6, "su": 6,
}


@dataclass(slots=True)
class Meeting:
    weekday: int
    start: str
    end: str
    location: str = ""

    def contains(self, when: datetime, *, buffer_minutes: int = 15) -> bool:
        if when.weekday() != self.weekday:
            return False
        start_value = time.fromisoformat(self.start)
        end_value = time.fromisoformat(self.end)
        current = when.hour * 60 + when.minute
        start_minutes = start_value.hour * 60 + start_value.minute - buffer_minutes
        end_minutes = end_value.hour * 60 + end_value.minute + buffer_minutes
        return start_minutes <= current <= end_minutes


@dataclass(slots=True)
class CourseProfile:
    code: str
    name: str
    instructor: str = ""
    aliases: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    meetings: list[Meeting] = field(default_factory=list)
    term: str = ""
    active: bool = True

    @classmethod
    def from_dict(cls, payload: dict) -> "CourseProfile":
        meetings = [
            item if isinstance(item, Meeting) else Meeting(**item)
            for item in payload.get("meetings", [])
        ]
        return cls(
            code=str(payload.get("code", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            instructor=str(payload.get("instructor", "")).strip(),
            aliases=[str(v).strip() for v in payload.get("aliases", []) if str(v).strip()],
            keywords=[str(v).strip() for v in payload.get("keywords", []) if str(v).strip()],
            meetings=meetings,
            term=str(payload.get("term", "")).strip(),
            active=bool(payload.get("active", True)),
        )

    def as_dict(self) -> dict:
        return asdict(self)


def default_registry_path() -> Path:
    return (school_runtime_root() / "courses.json").resolve()


DEFAULT_COURSES = [
    CourseProfile(
        code="CEN4065",
        name="Software Architecture and Design",
        aliases=[
            "CEN 4065",
            "Software Architecture & Design",
            "SWDesign",
            "Bookstore System Design",
        ],
        keywords=[
            "UML", "software architecture", "software design",
            "design patterns", "architectural patterns", "SOLID",
            "cohesion", "coupling", "user stories", "observer pattern",
            "bookstore",
        ],
        term="Fall 2026",
    ),
    CourseProfile(
        code="COP3350",
        name="Systems Admin and Programming",
        aliases=["COP 3350", "Systems Admin", "Systems Administration"],
        keywords=["Linux", "system administration", "shell", "PowerShell"],
        term="Fall 2026",
    ),
    CourseProfile(
        code="COP3710",
        name="Introduction to Data Engineering",
        aliases=["COP 3710", "Intro to Data Engineering", "Data Engineering"],
        keywords=["data engineering", "database", "ETL", "pipeline", "SQL"],
        term="Fall 2026",
    ),
    CourseProfile(
        code="COT3400",
        name="Design and Analysis of Algorithms",
        aliases=["COT 3400", "Algorithms", "Design and Analysis of Algorithms"],
        keywords=["algorithm", "complexity", "Big O", "recurrence", "runtime"],
        term="Fall 2026",
    ),
]


class CourseRegistry:
    """Local course registry. Meeting times are never guessed."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or default_registry_path()).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(DEFAULT_COURSES)

    def load(self) -> list[CourseProfile]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [CourseProfile.from_dict(item) for item in payload.get("courses", [])]

    def save(self, courses: Iterable[CourseProfile]) -> None:
        payload = {"version": 1, "courses": [course.as_dict() for course in courses]}
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    @staticmethod
    def _code(value: str) -> str:
        return "".join(ch for ch in value.upper() if ch.isalnum())

    def get(self, code: str) -> CourseProfile | None:
        needle = self._code(code)
        return next((c for c in self.load() if self._code(c.code) == needle), None)

    def add_meeting(
        self,
        code: str,
        day: str,
        start: str,
        end: str,
        *,
        location: str = "",
    ) -> CourseProfile:
        courses = self.load()
        course = next((c for c in courses if self._code(c.code) == self._code(code)), None)
        if course is None:
            raise KeyError(f"Unknown course: {code}")

        weekday = _DAY_ALIASES.get(day.strip().lower())
        if weekday is None:
            raise ValueError(f"Unknown weekday: {day}")

        start_time = time.fromisoformat(start)
        end_time = time.fromisoformat(end)
        if (end_time.hour, end_time.minute) <= (start_time.hour, start_time.minute):
            raise ValueError("Meeting end time must be after start time.")

        meeting = Meeting(weekday, start, end, location.strip())
        if meeting not in course.meetings:
            course.meetings.append(meeting)
            self.save(courses)
        return course
