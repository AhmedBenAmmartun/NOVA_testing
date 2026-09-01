from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nova_knowledge.discovery import discover_materials
from nova_knowledge.models import CourseDescriptor


def _courses(values: list[str]) -> list[CourseDescriptor]:
    output = []
    for raw in values:
        code, _, name = raw.partition(":")
        output.append(CourseDescriptor(code=code.strip(), name=name.strip()))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only batch discovery of possible NOVA course materials. Never copies/moves files.")
    parser.add_argument("source_root")
    parser.add_argument("--classes-root", required=True)
    parser.add_argument("--course", action="append", default=[], help="CODE[:Course Name]")
    parser.add_argument("--active-course", default="")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    results = discover_materials(
        args.source_root,
        vault_classes_root=args.classes_root,
        courses=_courses(args.course),
        active_course_hint=args.active_course or None,
        recursive=args.recursive,
    )
    payload = {
        "source_root_name": Path(args.source_root).expanduser().resolve().name,
        "count": len(results),
        "auto_import": sum(1 for x in results if x.disposition == "auto_import"),
        "pending_review": sum(1 for x in results if x.disposition == "pending_review"),
        "duplicates_in_scan": sum(1 for x in results if x.duplicate_in_scan),
        "results": [x.to_dict() for x in results],
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
