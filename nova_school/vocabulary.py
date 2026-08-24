from __future__ import annotations

import re

from .registry import CourseProfile


# High-value terminology that remains useful even before the first course file
# is organized. Material-derived terms are added later by CourseContextLibrary.
_COURSE_DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "CEN4065": (
        "cohesion",
        "coupling",
        "aggregation",
        "composition",
        "association",
        "dependency",
        "inheritance",
        "generalization",
        "realization",
        "abstraction",
        "encapsulation",
        "polymorphism",
        "object-oriented design",
        "class diagram",
        "sequence diagram",
        "use case diagram",
        "component diagram",
        "deployment diagram",
        "package diagram",
        "state machine diagram",
        "activity diagram",
        "single responsibility principle",
        "open-closed principle",
        "Liskov substitution principle",
        "interface segregation principle",
        "dependency inversion principle",
        "observer pattern",
        "factory pattern",
        "factory method",
        "abstract factory",
        "adapter pattern",
        "strategy pattern",
        "decorator pattern",
        "facade pattern",
        "singleton pattern",
        "model-view-controller",
        "MVC",
        "layered architecture",
        "client-server architecture",
        "microservices",
        "monolithic architecture",
        "architectural style",
        "architectural pattern",
        "design pattern",
        "quality attribute",
        "modularity",
        "maintainability",
        "responsibility",
        "interface",
        "component",
        "connector",
        "Bookstore System Design",
    ),
    "COP3350": (
        "Linux", "PowerShell", "Bash", "shell scripting", "systemd",
        "process", "service", "daemon", "permissions", "filesystem",
        "environment variable", "package manager", "SSH", "cron",
    ),
    "COP3710": (
        "ETL", "ELT", "data pipeline", "schema", "normalization",
        "denormalization", "primary key", "foreign key", "SQL",
        "data warehouse", "data lake", "batch processing", "stream processing",
    ),
    "COT3400": (
        "asymptotic analysis", "Big O", "Big Omega", "Big Theta",
        "recurrence relation", "divide and conquer", "dynamic programming",
        "greedy algorithm", "graph algorithm", "time complexity",
        "space complexity", "worst case", "average case",
    ),
}


def course_stt_keyterms(course: CourseProfile, *, limit: int = 100) -> list[str]:
    values = [
        course.code,
        course.name,
        *course.aliases,
        *course.keywords,
        *_COURSE_DOMAIN_TERMS.get(course.code.upper(), ()),
    ]
    unique: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
        if len(unique) >= max(1, min(100, int(limit))):
            break

    return unique
