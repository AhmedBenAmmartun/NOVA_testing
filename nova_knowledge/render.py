from __future__ import annotations

from pathlib import Path
import json

from .models import ExtractedDocument, MaterialRecord


def render_extracted_markdown(document: ExtractedDocument, record: MaterialRecord) -> str:
    """Render searchable derived material with stable page/slide anchors and provenance."""
    meta = {
        "nova_material_id": record.material_id,
        "course": record.course_code or "pending-review",
        "source_file": record.imported_name or record.source_name,
        "source_sha256": record.sha256,
        "material_kind": record.material_kind,
        "extractor": record.extractor,
        "review_state": "generated",
    }
    lines = ["---"]
    for key, value in meta.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", "", f"# {document.title or record.document_title or record.imported_name}", ""])
    if document.warnings:
        lines.extend(["> [!warning] Extraction notes", *[f"> - {w}" for w in document.warnings], ""])
    lines.extend(["## Source Provenance", "", f"- Material ID: `{record.material_id}`", f"- Source file: `{record.imported_name or record.source_name}`", f"- SHA-256: `{record.sha256}`", f"- Extractor: `{record.extractor}`", ""])

    for section in document.sections:
        if section.slide is not None:
            heading = f"Slide {section.slide} — {section.title or 'Untitled'}"
            anchor = f"slide-{section.slide}"
        elif section.page is not None:
            heading = f"Page {section.page} — {section.title or 'Untitled'}"
            anchor = f"page-{section.page}"
        else:
            heading = section.title or section.section_id
            anchor = section.section_id
        lines.extend([f'<a id="{anchor}"></a>', f"## {heading}", "", section.text.strip() or "_[No extractable text]_", ""])

    return "\n".join(lines).rstrip() + "\n"


def write_extracted_markdown(path: str | Path, document: ExtractedDocument, record: MaterialRecord) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(target)
    target.write_text(render_extracted_markdown(document, record), encoding="utf-8")
    return target
