from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nova_knowledge.discovery import discover_materials, iter_candidate_files
from nova_knowledge.fingerprint import sha256_file
from nova_knowledge.index import CourseKnowledgeIndex, chunks_from_file, merge_unique
from nova_knowledge.models import CourseDescriptor


def _courses(values: list[str]) -> list[CourseDescriptor]:
    output = []
    for raw in values:
        code, _, name = raw.partition(":")
        output.append(CourseDescriptor(code=code.strip(), name=name.strip()))
    return output


def _default_index() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local") / "NOVA" / "course_knowledge"
    return root / "index.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local-only NOVA course-material retrieval index. Does not modify the vault.")
    parser.add_argument("source_root")
    parser.add_argument("--classes-root", required=True)
    parser.add_argument("--course", action="append", default=[], help="CODE[:Course Name]")
    parser.add_argument("--active-course", default="")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--index", default=str(_default_index()))
    args = parser.parse_args()

    courses = _courses(args.course)
    discovered = discover_materials(
        args.source_root,
        vault_classes_root=args.classes_root,
        courses=courses,
        active_course_hint=args.active_course or None,
        recursive=args.recursive,
    )
    by_identity = defaultdict(deque)
    for result in discovered:
        by_identity[(result.source_name, result.sha256)].append(result)
    chunks = []
    indexed_materials = 0
    for path in iter_candidate_files(args.source_root, recursive=args.recursive):
        identity = (path.name, sha256_file(path))
        bucket = by_identity.get(identity)
        result = bucket.popleft() if bucket else None
        if result is None or result.disposition != "auto_import" or not result.course_code or result.duplicate_in_scan:
            continue
        additions = chunks_from_file(path, course_code=result.course_code)
        if additions:
            chunks = merge_unique(chunks, additions)
            indexed_materials += 1

    index = CourseKnowledgeIndex(args.index)
    index.rebuild(chunks)
    print(json.dumps({
        "index": str(index.path),
        "indexed_materials": indexed_materials,
        "chunks": len(chunks),
        "pending_review": sum(1 for r in discovered if r.disposition == "pending_review"),
        "note": "Index stores extracted course-material text locally and does not modify the vault.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
