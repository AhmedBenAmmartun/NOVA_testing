from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
from zipfile import ZipFile

from nova_knowledge.discovery import discover_materials, iter_candidate_files
from nova_knowledge.index import CourseKnowledgeIndex, chunks_from_file, merge_unique
from nova_knowledge.lexicon import build_course_lexicon
from nova_knowledge.models import CourseDescriptor
from nova_knowledge.retrieval import hits_to_evidence, search_records


def _pptx(path: Path, slides: list[list[str]]) -> None:
    ns = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    with ZipFile(path, 'w') as z:
        for i, texts in enumerate(slides, start=1):
            nodes = ''.join(f'<a:p><a:r><a:t>{t}</a:t></a:r></a:p>' for t in texts)
            z.writestr(f'ppt/slides/slide{i}.xml', f'<root xmlns:a="{ns}">{nodes}</root>')


def _courses():
    return [
        CourseDescriptor('CEN4065', 'Software Architecture and Design', ('architecture', 'software design')),
        CourseDescriptor('COT3400', 'Design and Analysis of Algorithms', ('algorithms', 'algorithm analysis')),
    ]


def test_discovery_scans_supported_only(tmp_path: Path):
    (tmp_path/'CEN4065_notes.txt').write_text('Software Architecture', encoding='utf-8')
    (tmp_path/'ignore.exe').write_bytes(b'x')
    found = list(iter_candidate_files(tmp_path))
    assert [p.name for p in found] == ['CEN4065_notes.txt']


def test_discovery_routes_course_and_pending(tmp_path: Path):
    (tmp_path/'CEN4065_architecture.md').write_text('# MVC\narchitecture', encoding='utf-8')
    (tmp_path/'lecture4.md').write_text('# Lecture\nhello', encoding='utf-8')
    results = discover_materials(tmp_path, vault_classes_root=tmp_path/'classes', courses=_courses())
    by = {r.source_name:r for r in results}
    assert by['CEN4065_architecture.md'].disposition == 'auto_import'
    assert by['lecture4.md'].disposition == 'pending_review'


def test_discovery_marks_duplicate_content(tmp_path: Path):
    (tmp_path/'CEN4065_a.txt').write_text('CEN4065 architecture architecture', encoding='utf-8')
    (tmp_path/'CEN4065_b.txt').write_text('CEN4065 architecture architecture', encoding='utf-8')
    results = discover_materials(tmp_path, vault_classes_root=tmp_path/'classes', courses=_courses())
    assert sum(r.duplicate_in_scan for r in results) == 1


def test_index_pptx_retains_slide_provenance(tmp_path: Path):
    p = tmp_path/'CEN4065_MVC.pptx'
    _pptx(p, [['MVC', 'Model View Controller'], ['Layered Architecture', 'presentation business data']])
    chunks = chunks_from_file(p, course_code='CEN4065')
    assert [c.slide for c in chunks] == [1,2]
    assert chunks[0].source_name == p.name


def test_index_does_not_store_full_source_path(tmp_path: Path):
    p = tmp_path/'secret-parent'/'CEN4065_notes.txt'; p.parent.mkdir()
    p.write_text('CEN4065 model view controller', encoding='utf-8')
    chunks = chunks_from_file(p, course_code='CEN4065')
    payload = str(chunks[0].to_dict())
    assert str(p.parent) not in payload


def test_index_rebuild_round_trip(tmp_path: Path):
    p = tmp_path/'CEN4065_notes.txt'; p.write_text('CEN4065 model view controller', encoding='utf-8')
    chunks = chunks_from_file(p, course_code='CEN4065')
    index = CourseKnowledgeIndex(tmp_path/'index.jsonl')
    index.rebuild(chunks)
    records = index.records()
    assert len(records) == len(chunks)
    assert records[0]['course_code'] == 'CEN4065'


def test_merge_is_idempotent(tmp_path: Path):
    p = tmp_path/'CEN4065_notes.txt'; p.write_text('CEN4065 model view controller', encoding='utf-8')
    chunks = chunks_from_file(p, course_code='CEN4065')
    assert len(merge_unique(chunks, chunks)) == len(chunks)


def test_retrieval_returns_correct_slide(tmp_path: Path):
    p = tmp_path/'CEN4065_MVC.pptx'
    _pptx(p, [['MVC', 'Model View Controller responsibilities'], ['Layered Architecture', 'layers and dependencies']])
    records = [c.to_dict() for c in chunks_from_file(p, course_code='CEN4065')]
    hits = search_records(records, 'model view controller', course_code='CEN4065')
    assert hits and hits[0].chunk['slide'] == 1
    evidence = hits_to_evidence(hits[:1])
    assert evidence[0].slide == 1
    assert evidence[0].name == p.name


def test_retrieval_respects_course_filter(tmp_path: Path):
    a = tmp_path/'CEN4065.txt'; a.write_text('MVC architecture controller', encoding='utf-8')
    b = tmp_path/'COT3400.txt'; b.write_text('MVC is just a token here algorithm', encoding='utf-8')
    records = [c.to_dict() for c in chunks_from_file(a, course_code='CEN4065')] + [c.to_dict() for c in chunks_from_file(b, course_code='COT3400')]
    hits = search_records(records, 'MVC', course_code='CEN4065')
    assert hits and all(h.chunk['course_code'] == 'CEN4065' for h in hits)


def test_course_lexicon_extracts_acronyms_and_terms(tmp_path: Path):
    p = tmp_path/'CEN4065.txt'
    p.write_text('UML UML MVC MVC architecture architecture architecture model model', encoding='utf-8')
    records = [c.to_dict() for c in chunks_from_file(p, course_code='CEN4065')]
    terms = build_course_lexicon(records, course_code='CEN4065')
    names = {x['term'] for x in terms}
    assert 'UML' in names
    assert 'MVC' in names
    assert 'architecture' in names



def test_standalone_cli_entrypoints_bootstrap_repo_root():
    repo_root = Path(__file__).resolve().parents[1]
    scripts = [
        "nova_knowledge_batch_scan.py",
        "nova_knowledge_build_index.py",
        "nova_knowledge_query.py",
    ]
    for name in scripts:
        proc = subprocess.run(
            [sys.executable, str(repo_root / "scripts" / name), "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, f"{name}: {proc.stderr}"
        assert "usage:" in proc.stdout.lower()


def test_recursive_build_index_handles_same_filename_collision(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    downloads = tmp_path / "downloads"
    classes = tmp_path / "classes"
    (downloads / "a").mkdir(parents=True)
    (downloads / "b").mkdir(parents=True)
    classes.mkdir()
    (downloads / "a" / "CEN4065_notes.txt").write_text(
        "CEN4065 software architecture MVC controller model view",
        encoding="utf-8",
    )
    (downloads / "b" / "CEN4065_notes.txt").write_text(
        "CEN4065 software architecture layered architecture dependencies",
        encoding="utf-8",
    )
    index_path = tmp_path / "index.jsonl"
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "nova_knowledge_build_index.py"),
            str(downloads),
            "--classes-root", str(classes),
            "--course", "CEN4065:Software Architecture and Design",
            "--recursive",
            "--index", str(index_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["indexed_materials"] == 2
    records = CourseKnowledgeIndex(index_path).records()
    texts = "\n".join(r["text"] for r in records)
    assert "controller model view" in texts
    assert "layered architecture dependencies" in texts
