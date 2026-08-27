from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .materials import SUPPORTED_MATERIAL_EXTENSIONS, extract_text
from .paths import course_materials_root, is_archived_path, school_runtime_root
from .registry import CourseProfile, CourseRegistry
from .resolver import resolve_current_course


logger = logging.getLogger("nova.school.organizer")


@dataclass(slots=True)
class Classification:
    course: CourseProfile | None
    confidence: float
    reasons: list[str]


@dataclass(slots=True)
class OrganizeResult:
    source: str
    destination: str | None
    course_code: str | None
    confidence: float
    status: str
    reasons: list[str]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _compact(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def classify_file(
    path: Path,
    *,
    registry: CourseRegistry | None = None,
    inspect_content: bool = True,
) -> Classification:
    registry = registry or CourseRegistry()
    filename = _normalize(path.stem)
    filename_compact = _compact(path.stem)
    content = _normalize(extract_text(path, max_chars=40_000)) if inspect_content else ""
    content_compact = _compact(content)
    current = resolve_current_course(registry=registry)

    scores: list[tuple[float, CourseProfile, list[str]]] = []

    for course in registry.load():
        if not course.active:
            continue

        score = 0.0
        reasons: list[str] = []
        code = _compact(course.code)

        if code and code in filename_compact:
            score += 0.95
            reasons.append("course code in filename")
        elif code and code in content_compact:
            score += 0.85
            reasons.append("course code in document text")

        aliases = [_normalize(alias) for alias in course.aliases]
        if any(alias and alias in filename for alias in aliases):
            score += 0.65
            reasons.append("course alias in filename")
        elif any(alias and alias in content for alias in aliases):
            score += 0.45
            reasons.append("course alias in document text")

        keyword_hits = sum(
            1
            for keyword in course.keywords
            if _normalize(keyword) and _normalize(keyword) in content
        )
        if keyword_hits:
            score += min(0.35, keyword_hits * 0.05)
            reasons.append(f"{keyword_hits} course keyword matches")

        if current is not None and current.code == course.code:
            score += 0.15
            reasons.append("matches current scheduled class")

        scores.append((min(1.0, score), course, reasons))

    if not scores:
        return Classification(None, 0.0, [])

    scores.sort(key=lambda item: item[0], reverse=True)
    best_score, best_course, best_reasons = scores[0]

    if best_score <= 0.0:
        return Classification(None, 0.0, [])

    if len(scores) > 1:
        second_score, second_course, _ = scores[1]
        if second_score > 0.0 and abs(best_score - second_score) < 0.05:
            return Classification(
                None,
                best_score,
                [
                    f"ambiguous between {best_course.code} and {second_course.code}",
                    *best_reasons,
                ],
            )

    return Classification(best_course, best_score, best_reasons)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _category(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".ppt", ".pptx"}:
        return "Slides"
    if ext in {".pdf", ".doc", ".docx", ".txt", ".md"}:
        return "Readings"
    if ext in {".xlsx", ".xls", ".csv"}:
        return "Data"
    return "Other"


class SchoolMaterialOrganizer:
    """Copy-only organizer with confidence, collision safety, and local audit."""

    def __init__(self, *, registry: CourseRegistry | None = None) -> None:
        self.registry = registry or CourseRegistry()
        self.audit_path = school_runtime_root() / "material_audit.jsonl"

    def organize(
        self,
        source: Path,
        *,
        minimum_confidence: float = 0.80,
    ) -> OrganizeResult:
        source = source.expanduser().resolve()

        try:
            result = self._organize(
                source,
                minimum_confidence=minimum_confidence,
            )
        except Exception as error:
            logger.exception("school material organization failed: %s", source)
            result = OrganizeResult(
                str(source),
                None,
                None,
                0.0,
                "error",
                [f"{type(error).__name__}: {error}"],
            )

        self._audit(result)
        return result

    def _organize(
        self,
        source: Path,
        *,
        minimum_confidence: float,
    ) -> OrganizeResult:
        if is_archived_path(source):
            return OrganizeResult(
                str(source),
                None,
                None,
                0.0,
                "archived_source",
                [
                    "Source is inside a preserved archive/backup location and "
                    "is never copied into the live vault."
                ],
            )

        if not source.is_file() or source.suffix.lower() not in SUPPORTED_MATERIAL_EXTENSIONS:
            return OrganizeResult(
                str(source),
                None,
                None,
                0.0,
                "unsupported",
                [],
            )

        classification = classify_file(source, registry=self.registry)
        if classification.course is None or classification.confidence < minimum_confidence:
            return OrganizeResult(
                str(source),
                None,
                classification.course.code if classification.course else None,
                classification.confidence,
                "needs_review",
                classification.reasons,
            )

        folder = course_materials_root(classification.course.code) / _category(source)
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / source.name

        source_hash = _sha256(source)
        if destination.exists():
            if destination.is_file() and _sha256(destination) == source_hash:
                status = "already_organized"
            else:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                destination = folder / f"{source.stem} ({stamp}){source.suffix}"
                shutil.copy2(source, destination)
                status = "organized"
        else:
            shutil.copy2(source, destination)
            status = "organized"

        return OrganizeResult(
            str(source),
            str(destination),
            classification.course.code,
            classification.confidence,
            status,
            classification.reasons,
        )

    def _audit(self, result: OrganizeResult) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                **asdict(result),
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            }
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            # Audit failure must never make a safe copy operation fail.
            logger.exception("could not write school material audit")
