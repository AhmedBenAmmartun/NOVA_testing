"""NOVA Course Knowledge foundation.

This package is intentionally not wired into the live class recorder yet.
It provides deterministic material ingestion/evidence primitives that can be
integrated after the active class session is safely finalized.
"""

from .catalog import MaterialCatalog
from .classifier import classify_course
from .evidence import load_manifest, save_manifest
from .extractors import extract_document, material_kind_for
from .fingerprint import sha256_file, short_material_id
from .ingest import ImportPlan, execute_import, plan_import, sanitize_filename
from .render import render_extracted_markdown, write_extracted_markdown
from .models import (
    CourseClassification,
    CourseDescriptor,
    EvidenceManifest,
    EvidenceSource,
    ExtractedDocument,
    ExtractedSection,
    MaterialRecord,
)

__all__ = [
    "CourseClassification",
    "CourseDescriptor",
    "EvidenceManifest",
    "EvidenceSource",
    "ExtractedDocument",
    "ExtractedSection",
    "ImportPlan",
    "MaterialCatalog",
    "MaterialRecord",
    "classify_course",
    "execute_import",
    "extract_document",
    "load_manifest",
    "material_kind_for",
    "plan_import",
    "sanitize_filename",
    "save_manifest",
    "render_extracted_markdown",
    "write_extracted_markdown",
    "sha256_file",
    "short_material_id",
]
