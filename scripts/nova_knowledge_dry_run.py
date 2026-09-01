from __future__ import annotations

import argparse
from pathlib import Path
import json
import tempfile

from nova_knowledge import CourseDescriptor, MaterialCatalog, plan_import


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run NOVA course material classification. Never copies or writes into the vault.")
    parser.add_argument("source")
    parser.add_argument("--classes-root", required=True)
    parser.add_argument("--course", action="append", default=[], help="CODE[:Course Name]")
    parser.add_argument("--active-course", default="")
    args = parser.parse_args()

    courses: list[CourseDescriptor] = []
    for raw in args.course:
        code, _, name = raw.partition(":")
        courses.append(CourseDescriptor(code=code.strip(), name=name.strip()))

    with tempfile.TemporaryDirectory(prefix="nova-knowledge-dry-run-") as temp:
        scratch_catalog = MaterialCatalog(Path(temp) / "catalog.jsonl")
        plan = plan_import(
            args.source,
            vault_classes_root=args.classes_root,
            courses=courses,
            catalog=scratch_catalog,
            active_course_hint=args.active_course or None,
        )

    print(json.dumps({
        "source_name": plan.source.name,
        "material_id": plan.material_id,
        "duplicate": plan.duplicate,
        "course_code": plan.course_code,
        "confidence": round(plan.confidence, 4),
        "disposition": plan.disposition,
        "destination": str(plan.destination) if plan.destination else None,
        "extractor": plan.extractor,
        "warnings": plan.warnings,
        "reasons": plan.reasons,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
