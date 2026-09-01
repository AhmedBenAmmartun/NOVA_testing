from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from .catalog import MaterialCatalog
from .classifier import classify_course
from .extractors import extract_document, material_kind_for
from .fingerprint import sha256_file, short_material_id
from .models import CourseDescriptor, MaterialRecord


@dataclass(slots=True)
class ImportPlan:
    source: Path
    sha256: str
    material_id: str
    duplicate: bool
    duplicate_record: dict | None
    course_code: str | None
    confidence: float
    disposition: str
    destination: Path | None
    extracted_title: str
    extractor: str
    warnings: list[str]
    reasons: list[str]


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or "material"


def _kind_folder(path: Path) -> str:
    kind = material_kind_for(path)
    return {
        "slides": "Slides",
        "pdf": "Readings",
        "document": "Documents",
        "text": "Documents",
        "unknown": "Other",
    }[kind]


def plan_import(
    source: str | Path,
    *,
    vault_classes_root: str | Path,
    courses: list[CourseDescriptor] | tuple[CourseDescriptor, ...],
    catalog: MaterialCatalog,
    active_course_hint: str | None = None,
) -> ImportPlan:
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or not source_path.is_file():
        raise FileNotFoundError(source_path)

    digest = sha256_file(source_path)
    duplicate = catalog.find_by_hash(digest)
    extracted = extract_document(source_path)
    classification = classify_course(
        source_path.name,
        extracted.searchable_text,
        courses,
        active_course_hint=active_course_hint,
    )

    destination: Path | None = None
    if duplicate is None:
        classes_root = Path(vault_classes_root).expanduser().resolve()
        if classification.disposition == "auto_import" and classification.course_code:
            destination = (
                classes_root
                / classification.course_code
                / "Resources"
                / _kind_folder(source_path)
                / sanitize_filename(source_path.name)
            )
        else:
            destination = (
                classes_root
                / "_Pending Review"
                / sanitize_filename(source_path.name)
            )

    return ImportPlan(
        source=source_path,
        sha256=digest,
        material_id=short_material_id(digest),
        duplicate=duplicate is not None,
        duplicate_record=duplicate,
        course_code=classification.course_code,
        confidence=classification.confidence,
        disposition=classification.disposition,
        destination=destination,
        extracted_title=extracted.title,
        extractor=extracted.extractor,
        warnings=list(extracted.warnings),
        reasons=list(classification.reasons),
    )


def _collision_safe_destination(destination: Path, sha256: str) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    candidate = destination.with_name(f"{stem}__{sha256[:8]}{suffix}")
    if candidate.exists():
        existing_hash = sha256_file(candidate)
        if existing_hash == sha256:
            return candidate
        candidate = destination.with_name(f"{stem}__{sha256[:16]}{suffix}")
    return candidate


def execute_import(plan: ImportPlan, *, catalog: MaterialCatalog) -> MaterialRecord:
    if plan.duplicate and plan.duplicate_record:
        record = plan.duplicate_record
        return MaterialRecord(
            material_id=str(record.get("material_id", plan.material_id)),
            sha256=plan.sha256,
            source_name=str(record.get("source_name", plan.source.name)),
            imported_name=str(record.get("imported_name", "")),
            course_code=record.get("course_code"),
            confidence=float(record.get("confidence", 0.0)),
            disposition=str(record.get("disposition", "pending_review")),
            material_kind=str(record.get("material_kind", material_kind_for(plan.source))),
            document_title=str(record.get("document_title", plan.extracted_title)),
            imported_at=float(record.get("imported_at", 0.0)),
            extractor=str(record.get("extractor", plan.extractor)),
            warnings=list(record.get("warnings", [])),
        )

    if plan.destination is None:
        raise ValueError("Import plan has no safe destination")

    destination = _collision_safe_destination(plan.destination, plan.sha256)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan.source, destination)

    record = MaterialRecord(
        material_id=plan.material_id,
        sha256=plan.sha256,
        source_name=plan.source.name,
        imported_name=destination.name,
        course_code=plan.course_code,
        confidence=plan.confidence,
        disposition=plan.disposition,
        material_kind=material_kind_for(plan.source),
        document_title=plan.extracted_title,
        extractor=plan.extractor,
        warnings=list(plan.warnings),
    )
    catalog.append(record)
    return record
