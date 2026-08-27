from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from nova_school.context import CourseContextLibrary, course_sessions_root
from nova_school.registry import CourseRegistry

from .evidence import (
    evidence_digest_markdown,
    lecture_timeline_markdown,
    load_session_evidence,
    write_session_evidence,
)
from .intelligence import _route
from .presentation import build_presentation
from .storage import safe_slug


logger = logging.getLogger("nova.class_capture.postprocess")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

#: How much of the lecture timeline each generation prompt may carry.
#: This replaces the old ``transcript_excerpt[:16000]`` head-truncation, which
#: silently dropped everything after roughly the first fifteen minutes. The
#: timeline is budgeted by salience with guaranteed coverage of every stretch of
#: the lecture, so raising or lowering this trades detail for cost, never the
#: end of the lecture.
TIMELINE_BUDGET_CHARS = 32_000


@dataclass(slots=True)
class EvidenceBundle:
    topics: list[str] = field(default_factory=list)
    definitions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    assignments: list[str] = field(default_factory=list)
    deadlines: list[str] = field(default_factory=list)
    exam_hints: list[str] = field(default_factory=list)
    emphasized: list[str] = field(default_factory=list)
    explanations: list[str] = field(default_factory=list)

    def merge(self, payload: dict[str, Any]) -> None:
        for name in self.__dataclass_fields__:
            values = payload.get(name, [])
            if not isinstance(values, list):
                continue
            target = getattr(self, name)
            for item in values:
                cleaned = " ".join(str(item).split()).strip()
                if cleaned and cleaned.casefold() not in {value.casefold() for value in target}:
                    target.append(cleaned)

    def as_dict(self) -> dict[str, list[str]]:
        return {name: list(getattr(self, name)) for name in self.__dataclass_fields__}


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return items
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def _elapsed(seconds: Any) -> str:
    # Raw journal values are model/STT-derived and a truncated or malformed
    # write must not take down the whole post-class job. An unreadable
    # timestamp degrades to 00:00 the same way the evidence loader coerces it.
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def _role_label(item: dict[str, Any], role_map: dict[str, Any]) -> str:
    speaker_id = item.get("speaker_id")
    if speaker_id is not None:
        resolved = role_map.get(str(speaker_id), {})
        label = resolved.get("label")
        if label:
            return str(label)
    role = str(item.get("speaker") or "unknown")
    return role.title() if role != "unknown" else f"Speaker {speaker_id or '?'}"


def build_source_transcript(
    transcript: list[dict[str, Any]],
    *,
    role_map: dict[str, Any],
    course: str,
    title: str,
) -> str:
    lines = [
        f"# Source Transcript — {title}",
        "",
        f"**Course:** {course}",
        "",
        "> Derived from the authoritative raw `transcript.jsonl`. Speaker labels are generic in-session inferences, not identity recognition.",
        "",
    ]
    for item in transcript:
        label = _role_label(item, role_map)
        stamp = _elapsed(item.get("start_seconds", 0.0))
        lines.append(f"**[{stamp}] {label}:** {str(item.get('text', '')).strip()}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _chunk_transcript(transcript: list[dict[str, Any]], max_chars: int = 12_000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for item in transcript:
        line = f"[{_elapsed(item.get('start_seconds', 0.0))}] speaker={item.get('speaker_id')} {item.get('text', '')}".strip()
        if current and length + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _parse_evidence_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = _JSON_OBJECT.search(cleaned)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def extract_evidence(chunks: list[str], course: str) -> EvidenceBundle:
    bundle = EvidenceBundle()
    for index, chunk in enumerate(chunks, start=1):
        prompt = f"""Extract grounded study evidence from lecture transcript chunk {index}/{len(chunks)} for {course}.
Return ONLY one JSON object with these array keys:
topics, definitions, examples, assignments, deadlines, exam_hints, emphasized, explanations.
Each item must be a concise statement directly supported by the supplied transcript. Do not invent missing information. If a category is absent, use an empty array.

TRANSCRIPT CHUNK:
{chunk}"""
        payload = _parse_evidence_json(await _route(prompt))
        if payload:
            bundle.merge(payload)
    return bundle


def _fallback_summary(transcript: list[dict[str, Any]], evidence: EvidenceBundle) -> str:
    topics = evidence.topics[:10]
    if topics:
        return "\n".join(f"- {item}" for item in topics)
    sample = [str(item.get("text", "")).strip() for item in transcript if str(item.get("text", "")).strip()]
    return "\n".join(f"- {item}" for item in sample[:12]) or "- No transcript content was captured."


def _evidence_markdown(evidence: EvidenceBundle) -> str:
    sections = []
    for name, values in evidence.as_dict().items():
        sections.append(f"## {name.replace('_', ' ').title()}")
        sections.extend(f"- {item}" for item in values[:30])
        if not values:
            sections.append("- None identified from the captured evidence.")
        sections.append("")
    return "\n".join(sections)


async def _generate_doc(
    *,
    kind: str,
    course: str,
    title: str,
    evidence_markdown: str,
    session_digest: str,
    questions: list[dict[str, Any]],
    materials_context: str,
    lecture_timeline: str,
) -> str | None:
    qa = "\n".join(
        f"- Q: {item.get('question', '')}\n  A: {item.get('answer') or '(no live answer logged)'}"
        for item in questions[:40]
    )
    prompt = f"""Create {kind} for a college class session.
COURSE: {course}
SESSION: {title}

GROUNDING RULES:
- Use only the lecture timeline, logged Q&A, session evidence, and supplied course materials.
- Never invent a professor statement, deadline, grade policy, exam hint, definition, or example.
- The professor's explanation is primary. Course materials supplement the lecture; they never replace it.
- Lines labelled "NOVA LIVE ANSWER" are NOVA's own in-class answers, not professor statements. Never attribute them to the professor.
- Moments labelled "MARKED BY AHMED" are explicit study signals. Give them weight.
- Clearly separate confirmed lecture evidence from NOVA study recommendations.
- Omit empty sections rather than padding them with made-up content.
- Preserve important technical terminology.

STRUCTURE RULES:
- Follow the professor's actual intellectual progression as it appears in the timeline.
- Let the lecture decide the headings. Do not impose a generic
  "Introduction / Key Takeaways / Conclusion" shape on a lecture that did not have one.
- No filler, no repeated summaries, no bullet dumps, no decorative bold, no fake certainty.

SESSION EVIDENCE (markers, topic progression, questions asked):
{session_digest}

EXTRACTED EVIDENCE:
{evidence_markdown}

LOGGED QUESTIONS/ANSWERS:
{qa or '(none)'}

RELATED MATERIAL EXCERPTS:
{materials_context[:22000] or '(none)'}

LECTURE TIMELINE:
{lecture_timeline}

Return polished Markdown only."""
    return await _route(prompt)


def _write_status(path: Path, **payload: Any) -> None:
    current = _load_json(path, {})
    current.update(payload)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


async def process_session(session_path: Path) -> Path:
    session_path = session_path.expanduser().resolve()
    metadata = _load_json(session_path / "session.json", {})
    course = str(metadata.get("course") or session_path.parent.name)
    title = str(metadata.get("title") or "Class Session")
    transcript = _load_jsonl(session_path / "transcript.jsonl")
    questions = _load_jsonl(session_path / "questions.jsonl")
    speaker_payload = _load_json(session_path / "speaker_roles.json", {})
    role_map = speaker_payload.get("speakers") if isinstance(speaker_payload, dict) else None
    # A corrupt speaker map must degrade to generic labels, not abort the job.
    if not isinstance(role_map, dict):
        role_map = {}

    status_path = session_path / "postprocess.json"
    _write_status(
        status_path,
        status="running",
        started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        error=None,
    )

    try:
        # Layer 2 (working intelligence): one authoritative read of every raw
        # journal this session produced. Markers, topic progression, live Q&A and
        # attachments reach generation through here; before this they were
        # captured and then silently dropped.
        session_evidence = load_session_evidence(session_path)
        write_session_evidence(
            session_path,
            session_evidence,
            generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        if session_evidence.warnings:
            logger.warning(
                "class evidence loaded with warnings: %s",
                "; ".join(session_evidence.warnings),
            )
        lecture_timeline = lecture_timeline_markdown(
            session_evidence,
            max_chars=TIMELINE_BUDGET_CHARS,
        )
        session_digest = evidence_digest_markdown(session_evidence)

        library = CourseContextLibrary(course, session_path=session_path, max_chars=40_000)
        materials_context, sources = library.build_context("")
        chunks = _chunk_transcript(transcript)
        evidence = await extract_evidence(chunks, course) if chunks else EvidenceBundle()
        evidence_markdown = _evidence_markdown(evidence)

        started_at = str(metadata.get("started_at") or "")
        try:
            stamp = datetime.fromisoformat(started_at).astimezone()
        except Exception:
            stamp = datetime.now().astimezone()
        folder = course_sessions_root(course) / stamp.strftime("%Y-%m-%d") / safe_slug(
            f"{stamp.strftime('%H-%M')} - {title} - {str(metadata.get('session_id', 'session'))[-8:]}",
            fallback="session",
        )
        folder.mkdir(parents=True, exist_ok=True)

        source_transcript = build_source_transcript(
            transcript,
            role_map=role_map,
            course=course,
            title=title,
        )
        (folder / "Source Transcript.md").write_text(source_transcript, encoding="utf-8")
        (folder / "Evidence.md").write_text(
            f"# Evidence — {title}\n\n"
            f"{session_digest}\n"
            f"## Extracted from the transcript\n\n{evidence_markdown}",
            encoding="utf-8",
        )
        (folder / "Lecture Timeline.md").write_text(
            f"# Lecture Timeline — {title}\n\n"
            "> Chronological, budget-selected view of the whole lecture. Derived from "
            "the authoritative raw journals; it never replaces them.\n\n"
            f"{lecture_timeline}",
            encoding="utf-8",
        )

        documents = {
            "Lecture.md": "detailed, organized lecture notes with topics, explanations, definitions, examples, and clearly labeled assignments/deadlines/exam emphasis",
            "Summary.md": "a concise but complete session summary and key takeaways",
            "Study.md": "a study guide with key concepts, what to understand, likely review priorities, and NOVA recommendations clearly labeled as recommendations",
            "Questions.md": "a complete Q&A review using every logged question and answer plus transcript-supported answers where possible",
            "Presentation Outline.md": "a slide-by-slide presentation outline with short slide titles and concise bullets",
        }

        generated: dict[str, str] = {}
        for filename, kind in documents.items():
            value = await _generate_doc(
                kind=kind,
                course=course,
                title=title,
                evidence_markdown=evidence_markdown,
                session_digest=session_digest,
                questions=questions,
                materials_context=materials_context,
                lecture_timeline=lecture_timeline,
            )
            if not value:
                # No model was reachable. Fall back to grounded evidence rather
                # than an empty file — the digest needs no AI to be useful.
                if filename == "Summary.md":
                    value = f"# Session Summary — {title}\n\n{_fallback_summary(transcript, evidence)}\n"
                elif filename == "Questions.md":
                    lines = [f"# Questions — {title}", ""]
                    for item in questions:
                        lines += [f"## {item.get('question', '')}", "", item.get("answer") or "No answer was logged.", ""]
                    value = "\n".join(lines)
                elif filename == "Presentation Outline.md":
                    value = f"# Session Overview\n\n{_fallback_summary(transcript, evidence)}\n"
                else:
                    value = (
                        f"# {filename.removesuffix('.md')} — {title}\n\n"
                        "> NOVA could not reach a model for this session, so this file "
                        "contains the grounded session evidence without AI synthesis.\n\n"
                        f"{session_digest}\n{evidence_markdown}"
                    )
            generated[filename] = value.rstrip() + "\n"
            (folder / filename).write_text(generated[filename], encoding="utf-8")

        presentation_path = None
        try:
            presentation_path = build_presentation(
                generated["Presentation Outline.md"],
                folder / "Presentation.pptx",
                course=course,
                title=title,
            )
        except Exception as error:
            logger.exception("class presentation generation failed")
            (folder / "Presentation ERROR.txt").write_text(
                f"{type(error).__name__}: {error}\n",
                encoding="utf-8",
            )

        _write_status(
            status_path,
            status="completed",
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output_folder=str(folder),
            material_sources=[source.path for source in sources],
            presentation=str(presentation_path) if presentation_path else None,
            evidence_coverage=session_evidence.coverage(),
            evidence_warnings=list(session_evidence.warnings),
        )
        return folder
    except Exception as error:
        logger.exception("post-class intelligence failed")
        _write_status(
            status_path,
            status="failed",
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            error=f"{type(error).__name__}: {error}",
        )
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova-class-postprocess")
    parser.add_argument("--session", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    folder = asyncio.run(process_session(Path(args.session)))
    print("Class Intelligence outputs:", folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# NOTE: launch_postprocess is intentionally defined after main helpers but is
# imported by class_capture, not executed through the CLI branch above.
def launch_postprocess(session_path: Path) -> int | None:
    import os
    import subprocess
    import sys

    session_path = session_path.expanduser().resolve()
    status_path = session_path / "postprocess.json"
    _write_status(
        status_path,
        status="queued",
        queued_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        error=None,
    )

    command = [
        sys.executable,
        "-m",
        "nova_capture.postprocess",
        "--session",
        str(session_path),
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(Path(__file__).resolve().parents[1]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen(command, **kwargs)
    except Exception as error:
        _write_status(
            status_path,
            status="failed_to_launch",
            error=f"{type(error).__name__}: {error}",
        )
        logger.exception("could not launch post-class intelligence")
        return None

    _write_status(status_path, status="launched", pid=process.pid)
    return process.pid
