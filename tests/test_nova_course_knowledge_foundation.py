from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import json

from nova_knowledge import (
    CourseDescriptor,
    EvidenceManifest,
    EvidenceSource,
    MaterialCatalog,
    execute_import,
    extract_document,
    plan_import,
    save_manifest,
    load_manifest,
)


def courses():
    return [
        CourseDescriptor("CEN4065", "Software Architecture and Design", ("software architecture", "architecture design")),
        CourseDescriptor("COP3350", "Systems Admin and Programming", ("systems administration",)),
        CourseDescriptor("COP3710", "Intro to Data Engineering", ("data engineering",)),
        CourseDescriptor("COT3400", "Design and Analysis of Algorithms", ("algorithms", "algorithm analysis")),
    ]


def make_pptx(path: Path, slides: list[list[str]]) -> None:
    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    with ZipFile(path, "w") as z:
        for i, texts in enumerate(slides, start=1):
            runs = "".join(f'<a:r><a:t>{t}</a:t></a:r>' for t in texts)
            xml = f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="{ns}"><p:cSld><p:spTree><p:sp><p:txBody><a:p>{runs}</a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'
            z.writestr(f"ppt/slides/slide{i}.xml", xml)


def make_docx(path: Path, paras: list[str]) -> None:
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paras)
    xml = f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>'
    with ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def test_course_code_filename_auto_routes(tmp_path: Path):
    source = tmp_path / "CEN4065_Architecture_Patterns_Lecture4.pptx"
    make_pptx(source, [["Architecture Patterns", "MVC"]])
    catalog = MaterialCatalog(tmp_path / "catalog.jsonl")
    plan = plan_import(source, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog)
    assert plan.course_code == "CEN4065"
    assert plan.disposition == "auto_import"
    assert "CEN4065" in str(plan.destination)
    assert "Slides" in str(plan.destination)


def test_ambiguous_material_goes_pending_review(tmp_path: Path):
    source = tmp_path / "lecture4.md"
    source.write_text("Today we discuss design concepts and examples.", encoding="utf-8")
    catalog = MaterialCatalog(tmp_path / "catalog.jsonl")
    plan = plan_import(source, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog)
    assert plan.disposition == "pending_review"
    assert "_Pending Review" in str(plan.destination)


def test_same_file_twice_is_deduplicated(tmp_path: Path):
    source = tmp_path / "COT3400_algorithms.md"
    source.write_text("# Algorithms\nInsertion sort", encoding="utf-8")
    catalog = MaterialCatalog(tmp_path / "catalog.jsonl")
    plan1 = plan_import(source, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog)
    record1 = execute_import(plan1, catalog=catalog)
    plan2 = plan_import(source, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog)
    record2 = execute_import(plan2, catalog=catalog)
    assert plan2.duplicate is True
    assert record1.material_id == record2.material_id
    assert len(catalog.records()) == 1


def test_different_files_same_name_do_not_overwrite(tmp_path: Path):
    d1 = tmp_path / "a"; d2 = tmp_path / "b"
    d1.mkdir(); d2.mkdir()
    s1 = d1 / "CEN4065_notes.md"; s2 = d2 / "CEN4065_notes.md"
    s1.write_text("version one", encoding="utf-8")
    s2.write_text("version two", encoding="utf-8")
    catalog = MaterialCatalog(tmp_path / "catalog.jsonl")
    r1 = execute_import(plan_import(s1, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog), catalog=catalog)
    r2 = execute_import(plan_import(s2, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog), catalog=catalog)
    assert r1.sha256 != r2.sha256
    imported = list((tmp_path / "vault" / "CEN4065" / "Resources" / "Documents").glob("CEN4065_notes*"))
    assert len(imported) == 2
    assert imported[0].read_text(encoding="utf-8") != imported[1].read_text(encoding="utf-8")


def test_pptx_extraction_preserves_slide_provenance(tmp_path: Path):
    source = tmp_path / "lecture.pptx"
    make_pptx(source, [["MVC", "Model View Controller"], ["Layered Architecture", "Presentation Business Data"]])
    doc = extract_document(source)
    assert doc.extractor == "builtin-pptx-xml"
    assert [s.slide for s in doc.sections] == [1, 2]
    assert doc.sections[0].title == "MVC"
    assert "Model View Controller" in doc.sections[0].text


def test_docx_extraction_preserves_document_text(tmp_path: Path):
    source = tmp_path / "CEN4065_handout.docx"
    make_docx(source, ["Software Architecture", "Quality attributes"])
    doc = extract_document(source)
    assert doc.extractor == "builtin-docx-xml"
    assert "Quality attributes" in doc.searchable_text


def test_material_catalog_does_not_store_source_full_path(tmp_path: Path):
    private_dir = tmp_path / "private" / "very-secret-folder"
    private_dir.mkdir(parents=True)
    source = private_dir / "CEN4065_material.md"
    source.write_text("architecture", encoding="utf-8")
    catalog_path = tmp_path / "catalog.jsonl"
    catalog = MaterialCatalog(catalog_path)
    execute_import(plan_import(source, vault_classes_root=tmp_path / "vault", courses=courses(), catalog=catalog), catalog=catalog)
    raw = catalog_path.read_text(encoding="utf-8")
    assert str(private_dir) not in raw
    assert source.name in raw


def test_evidence_manifest_round_trip_uses_names_not_required_absolute_paths(tmp_path: Path):
    manifest = EvidenceManifest(
        session_id="2026-08-26_120000",
        course_code="CEN4065",
        transcript_name="transcript.jsonl",
        audio_name="audio.wav",
        marker_name="markers.jsonl",
        materials=[EvidenceSource(source_id="mat_abc", kind="slides", name="lecture4.pptx", sha256="a" * 64, slide=12)],
    )
    path = save_manifest(tmp_path / "evidence.json", manifest)
    loaded = load_manifest(path)
    assert loaded["session_id"] == manifest.session_id
    assert loaded["materials"][0]["slide"] == 12
    assert loaded["materials"][0]["name"] == "lecture4.pptx"


def test_manifest_write_is_valid_json(tmp_path: Path):
    path = save_manifest(tmp_path / "evidence.json", EvidenceManifest(session_id="s", course_code="COT3400"))
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == 1


def test_rendered_material_markdown_has_stable_slide_provenance(tmp_path: Path):
    from nova_knowledge import MaterialRecord, render_extracted_markdown
    source = tmp_path / "CEN4065_week4.pptx"
    make_pptx(source, [["MVC", "Model View Controller"]])
    doc = extract_document(source)
    record = MaterialRecord(
        material_id="mat_1234567890abcdef",
        sha256="b" * 64,
        source_name=source.name,
        imported_name=source.name,
        course_code="CEN4065",
        confidence=0.99,
        disposition="auto_import",
        material_kind="slides",
        document_title=doc.title,
        extractor=doc.extractor,
    )
    rendered = render_extracted_markdown(doc, record)
    assert '<a id="slide-1"></a>' in rendered
    assert "## Slide 1 — MVC" in rendered
    assert "Model View Controller" in rendered
    assert str(tmp_path) not in rendered
