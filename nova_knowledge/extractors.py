from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
import re

from .models import ExtractedDocument, ExtractedSection, MaterialKind

_TEXT_EXTS = {".txt", ".md"}


def material_kind_for(path: str | Path) -> MaterialKind:
    suffix = Path(path).suffix.lower()
    if suffix in {".pptx"}:
        return "slides"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".docx"}:
        return "document"
    if suffix in _TEXT_EXTS:
        return "text"
    return "unknown"


def extract_document(path: str | Path) -> ExtractedDocument:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix in _TEXT_EXTS:
        return _extract_text(source)
    if suffix == ".pptx":
        return _extract_pptx(source)
    if suffix == ".docx":
        return _extract_docx(source)
    if suffix == ".pdf":
        return _extract_pdf(source)
    return ExtractedDocument(
        kind="unknown",
        title=source.stem,
        extractor="unsupported",
        warnings=[f"Unsupported material extension: {suffix or '(none)'}"],
    )


def _clean_xml_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_text(path: Path) -> ExtractedDocument:
    text = path.read_text(encoding="utf-8", errors="replace")
    sections: list[ExtractedSection] = []
    current_title = path.stem
    current: list[str] = []
    section_no = 1

    def flush() -> None:
        nonlocal section_no, current
        body = "\n".join(current).strip()
        if body or not sections:
            sections.append(
                ExtractedSection(
                    section_id=f"section-{section_no}",
                    title=current_title,
                    text=body,
                )
            )
            section_no += 1
        current = []

    for line in text.splitlines():
        if path.suffix.lower() == ".md" and line.lstrip().startswith("#"):
            if current:
                flush()
            current_title = line.lstrip("#").strip() or current_title
        else:
            current.append(line)
    flush()
    return ExtractedDocument(kind="text", title=path.stem, sections=sections, extractor="builtin-text")


def _extract_pptx(path: Path) -> ExtractedDocument:
    try:
        with ZipFile(path) as archive:
            slide_names = sorted(
                [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)],
                key=lambda n: int(re.search(r"slide(\d+)\.xml", n).group(1)),
            )
            sections: list[ExtractedSection] = []
            for slide_name in slide_names:
                slide_no = int(re.search(r"slide(\d+)\.xml", slide_name).group(1))
                root = ET.fromstring(archive.read(slide_name))
                texts = [_clean_xml_text(node.text or "") for node in root.iter() if node.tag.endswith("}t")]
                texts = [t for t in texts if t]
                title = texts[0] if texts else f"Slide {slide_no}"
                body = "\n".join(texts[1:] if len(texts) > 1 else texts)
                sections.append(
                    ExtractedSection(
                        section_id=f"slide-{slide_no}",
                        title=title,
                        text=body,
                        slide=slide_no,
                    )
                )
            return ExtractedDocument(
                kind="slides",
                title=path.stem,
                sections=sections,
                extractor="builtin-pptx-xml",
                warnings=[] if sections else ["No slide text was found."],
            )
    except (BadZipFile, ET.ParseError, OSError) as error:
        return ExtractedDocument(
            kind="slides",
            title=path.stem,
            extractor="builtin-pptx-xml",
            warnings=[f"PPTX extraction failed: {type(error).__name__}"],
        )


def _extract_docx(path: Path) -> ExtractedDocument:
    try:
        with ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
            root = ET.fromstring(xml)
            paragraphs: list[str] = []
            for p in root.iter():
                if not p.tag.endswith("}p"):
                    continue
                texts = [_clean_xml_text(n.text or "") for n in p.iter() if n.tag.endswith("}t")]
                value = _clean_xml_text(" ".join(t for t in texts if t))
                if value:
                    paragraphs.append(value)
            return ExtractedDocument(
                kind="document",
                title=path.stem,
                sections=[ExtractedSection(section_id="document", title=path.stem, text="\n".join(paragraphs))],
                extractor="builtin-docx-xml",
                warnings=[] if paragraphs else ["No document text was found."],
            )
    except (BadZipFile, KeyError, ET.ParseError, OSError) as error:
        return ExtractedDocument(
            kind="document",
            title=path.stem,
            extractor="builtin-docx-xml",
            warnings=[f"DOCX extraction failed: {type(error).__name__}"],
        )


def _extract_pdf(path: Path) -> ExtractedDocument:
    reader_cls = None
    extractor_name = ""
    try:
        from pypdf import PdfReader  # type: ignore
        reader_cls = PdfReader
        extractor_name = "pypdf"
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
            reader_cls = PdfReader
            extractor_name = "PyPDF2"
        except Exception:
            pass

    if reader_cls is None:
        return ExtractedDocument(
            kind="pdf",
            title=path.stem,
            extractor="optional-pdf",
            warnings=["PDF text extraction unavailable: install/use existing pypdf or PyPDF2 support."],
        )

    try:
        reader = reader_cls(str(path))
        sections: list[ExtractedSection] = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            sections.append(
                ExtractedSection(
                    section_id=f"page-{page_no}",
                    title=f"Page {page_no}",
                    text=text,
                    page=page_no,
                )
            )
        return ExtractedDocument(
            kind="pdf",
            title=path.stem,
            sections=sections,
            extractor=extractor_name,
            warnings=[] if any(s.text for s in sections) else ["PDF contained no extractable text."],
        )
    except Exception as error:
        return ExtractedDocument(
            kind="pdf",
            title=path.stem,
            extractor=extractor_name or "optional-pdf",
            warnings=[f"PDF extraction failed: {type(error).__name__}"],
        )
