from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


SUPPORTED_MATERIAL_EXTENSIONS = {
    ".ppt", ".pptx", ".pdf", ".doc", ".docx",
    ".txt", ".md", ".xlsx", ".xls", ".csv",
}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def extract_text(path: Path, *, max_chars: int = 80_000) -> str:
    """Best-effort local extraction without background Office automation."""

    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md", ".csv"}:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]

        if suffix == ".pdf":
            from pypdf import PdfReader

            parts, total = [], 0
            for page in PdfReader(str(path)).pages:
                text = page.extract_text() or ""
                parts.append(text)
                total += len(text)
                if total >= max_chars:
                    break
            return "\n".join(parts)[:max_chars]

        if suffix == ".pptx":
            with zipfile.ZipFile(path) as archive:
                parts = []
                for name in sorted(
                    n for n in archive.namelist()
                    if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                ):
                    root = ET.fromstring(archive.read(name))
                    text = " ".join(
                        _clean(node.text or "")
                        for node in root.iter()
                        if node.tag.endswith("}t") and _clean(node.text or "")
                    )
                    if text:
                        parts.append(text)
                    if sum(map(len, parts)) >= max_chars:
                        break
                return "\n".join(parts)[:max_chars]

        if suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                root = ET.fromstring(archive.read("word/document.xml"))
            return "\n".join(
                _clean(node.text or "")
                for node in root.iter()
                if node.tag.endswith("}t") and _clean(node.text or "")
            )[:max_chars]
    except Exception:
        return ""

    # Legacy .ppt/.doc and spreadsheets are still classifiable by filename,
    # but V1.1 does not silently launch Microsoft Office to inspect them.
    return ""
