from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from nova_capture.control import read_active_session
from nova_runtime import NovaRuntime

from .automation import SchoolAutomationService
from .context import attach_material_to_session
from .organizer import SchoolMaterialOrganizer, classify_file
from .registry import CourseRegistry
from .resolver import resolve_current_course


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="nova-school")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("show")

    meeting = commands.add_parser("add-meeting")
    meeting.add_argument("course")
    meeting.add_argument("day")
    meeting.add_argument("start", help="24-hour HH:MM")
    meeting.add_argument("end", help="24-hour HH:MM")
    meeting.add_argument("--location", default="")

    classify = commands.add_parser("classify")
    classify.add_argument("path")

    organize = commands.add_parser("organize")
    organize.add_argument("path")

    attach = commands.add_parser("attach-session")
    attach.add_argument("path")
    attach.add_argument("--session", default="")

    commands.add_parser("watch")
    return root


async def run_watch() -> None:
    runtime = NovaRuntime()
    service = SchoolAutomationService()
    job_id = await service.start(runtime)

    print("NOVA School Automation is running under nova_runtime.")
    for folder in service.download_directories:
        print("Watching:", folder)
    print("Recognized course files are COPIED; originals are never deleted.")
    print("Press Ctrl+C to stop.")

    try:
        await runtime.jobs.wait(job_id)
    finally:
        await runtime.shutdown()


def main() -> None:
    args = parser().parse_args()
    registry = CourseRegistry()

    if args.command == "show":
        current = resolve_current_course(registry=registry)
        print("Registry:", registry.path)
        print("Current class:", f"{current.code} — {current.name}" if current else "not resolved")
        for course in registry.load():
            print(f"\n{course.code} — {course.name}")
            print("Instructor:", course.instructor or "(not set)")
            if not course.meetings:
                print("Meetings: NOT CONFIGURED")
            for meeting in course.meetings:
                print(
                    f"Meeting: weekday={meeting.weekday} "
                    f"{meeting.start}-{meeting.end} {meeting.location}".rstrip()
                )
        return

    if args.command == "add-meeting":
        registry.add_meeting(
            args.course,
            args.day,
            args.start,
            args.end,
            location=args.location,
        )
        print("Meeting added.")
        return

    if args.command == "classify":
        result = classify_file(Path(args.path), registry=registry)
        if result.course is None:
            print("No course match.")
        else:
            print(f"{result.course.code}: {result.confidence:.0%} confidence")
            for reason in result.reasons:
                print("-", reason)
        return

    if args.command == "organize":
        print(SchoolMaterialOrganizer(registry=registry).organize(Path(args.path)))
        return

    if args.command == "attach-session":
        if args.session.strip():
            session_path = Path(args.session).expanduser().resolve()
        else:
            active = read_active_session(clean_stale=True)
            if active is None:
                raise SystemExit("No active NOVA class session. Use --session <path> to attach to a completed session.")
            session_path = Path(active.session_path)
        record = attach_material_to_session(Path(args.path), session_path)
        print("Attached:", record.destination)
        return

    if args.command == "watch":
        try:
            asyncio.run(run_watch())
        except KeyboardInterrupt:
            print("\nNOVA School Automation stopped.")


if __name__ == "__main__":
    main()
