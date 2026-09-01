from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import tempfile

from nova_school.paths import ArchivedSourceError, is_archived_path

from .catalog import MaterialCatalog
from .fingerprint import sha256_file
from .ingest import ImportPlan, plan_import
from .models import CourseDescriptor

SUPPORTED_EXTENSIONS = {".pptx", ".pdf", ".docx", ".md", ".txt"}


@dataclass(slots=True)
class DiscoveryResult:
    source_name: str
    material_id: str
    sha256: str
    course_code: str | None
    confidence: float
    disposition: str
    extractor: str
    duplicate_in_scan: bool
    warnings: list[str]
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def iter_candidate_files(
    root: str | Path,
    *,
    recursive: bool = False,
    allow_archived: bool = False,
):
    """Yield material candidates under ``root``.

    Preserved archive/backup locations are refused outright when they are the
    scan root, and skipped when a recursive scan walks into one, so historical
    vaults, old captures, and backups can never become live Course Knowledge
    input. Nothing in those locations is read, moved, or modified.
    """
    base = Path(root).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise NotADirectoryError(base)
    if not allow_archived and is_archived_path(base):
        raise ArchivedSourceError(
            f"{base} is a preserved archive/backup location and cannot be "
            "scanned as live Course Knowledge input."
        )
    iterator = base.rglob("*") if recursive else base.iterdir()
    for path in iterator:
        if not path.is_file():
            continue
        if path.name.startswith((".", "~$")):
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if not allow_archived and is_archived_path(path):
            continue
        yield path


def discover_materials(
    root: str | Path,
    *,
    vault_classes_root: str | Path,
    courses: list[CourseDescriptor] | tuple[CourseDescriptor, ...],
    active_course_hint: str | None = None,
    recursive: bool = False,
) -> list[DiscoveryResult]:
    if is_archived_path(vault_classes_root):
        raise ArchivedSourceError(
            f"{vault_classes_root} is a preserved archive/backup location and "
            "cannot be used as a Course Knowledge destination root."
        )

    output: list[DiscoveryResult] = []
    seen_hashes: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="nova-knowledge-discovery-") as temp:
        catalog = MaterialCatalog(Path(temp) / "catalog.jsonl")
        for path in iter_candidate_files(root, recursive=recursive):
            plan = plan_import(
                path,
                vault_classes_root=vault_classes_root,
                courses=courses,
                catalog=catalog,
                active_course_hint=active_course_hint,
            )
            duplicate_in_scan = plan.sha256 in seen_hashes
            seen_hashes.add(plan.sha256)
            warnings = list(plan.warnings)
            if duplicate_in_scan:
                warnings.append("Duplicate content also appears elsewhere in this scan.")
            output.append(
                DiscoveryResult(
                    source_name=path.name,
                    material_id=plan.material_id,
                    sha256=plan.sha256,
                    course_code=plan.course_code,
                    confidence=round(float(plan.confidence), 4),
                    disposition=plan.disposition,
                    extractor=plan.extractor,
                    duplicate_in_scan=duplicate_in_scan,
                    warnings=warnings,
                    reasons=list(plan.reasons),
                )
            )
    return output
