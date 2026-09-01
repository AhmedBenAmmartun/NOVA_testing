from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nova_knowledge.index import CourseKnowledgeIndex
from nova_knowledge.lexicon import build_course_lexicon
from nova_knowledge.retrieval import search_records


def _default_index() -> Path:
    root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local") / "NOVA" / "course_knowledge"
    return root / "index.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Query NOVA's local course-material index.")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--course", default="")
    parser.add_argument("--index", default=str(_default_index()))
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--lexicon", action="store_true")
    args = parser.parse_args()

    index = CourseKnowledgeIndex(args.index)
    records = index.records()
    if args.lexicon:
        print(json.dumps(build_course_lexicon(records, course_code=args.course or None), ensure_ascii=False, indent=2))
        return 0
    if not args.query:
        raise SystemExit("query is required unless --lexicon is used")
    hits = search_records(records, args.query, course_code=args.course or None, limit=args.limit)
    print(json.dumps([hit.to_dict() for hit in hits], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
