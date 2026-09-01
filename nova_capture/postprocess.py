from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from nova_school.context import CourseContextLibrary, course_sessions_root
from nova_knowledge.knowledge_db import KnowledgeStore, default_knowledge_path
from nova_school.corrections import active_corrections_for, load_course_corrections

from .control import process_identity_matches
from .evidence import (
    SessionEvidence,
    evidence_digest_markdown,
    lecture_timeline_markdown,
    load_session_evidence,
    write_session_evidence,
)
from .terminology import TerminologyInterpreter
from .intelligence import _route
from .note_review import ReviewFinding, review_definitions
from .note_versions import archive_existing_notes
from .presentation import build_presentation
from .renderers import render_all
from .storage import safe_slug
from .understanding import (
    DEFAULT_REQUEST_TOKEN_LIMIT,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
    LectureUnderstanding,
    build_understanding,
    write_understanding,
)


logger = logging.getLogger("nova.class_capture.postprocess")

#: How much of the lecture timeline each generation prompt may carry.
#: This replaces the old ``transcript_excerpt[:16000]`` head-truncation, which
#: silently dropped everything after roughly the first fifteen minutes. The
#: timeline is budgeted by salience with guaranteed coverage of every stretch of
#: the lecture, so raising or lowering this trades detail for cost, never the
#: end of the lecture.
TIMELINE_BUDGET_CHARS = 32_000


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


def understanding_evidence_markdown(understanding: LectureUnderstanding) -> str:
    """The extracted-evidence view of Evidence.md, from the understanding."""
    blocks: list[str] = []
    for label, values in (
        ("Definitions", understanding.definitions),
        ("Examples", understanding.examples),
        ("Assignments", understanding.assignments),
        ("Deadlines", understanding.deadlines),
        ("Exam signals", understanding.exam_signals),
        ("Emphasised", understanding.emphasis),
    ):
        blocks.append(f"## {label}")
        blocks.extend(f"- {value}" for value in values[:30])
        if not values:
            blocks.append("- None identified from the captured evidence.")
        blocks.append("")
    return "\n".join(blocks)



def _render_review(
    findings: list["ReviewFinding"], *, title: str, course: str
) -> str:
    """A short, actionable note about what could not be corroborated.

    Written as its own document rather than mixed into the lecture notes, so
    the notes stay readable and the doubt stays visible.
    """
    lines = [
        f"# Review — {title}",
        "",
        f"**Course:** {course}",
        "",
        "> These terms appear in NOVA's generated notes but in **none** of this",
        "> course's materials. This lecture is taught from those materials, so a",
        "> definition resting on an uncorroborated term may be built on a",
        "> transcription error rather than on something the professor said.",
        ">",
        "> Nothing has been removed. Check these against the audio before",
        "> relying on them, and add a rule to `STT-Corrections.md` if one is",
        "> genuinely a mishearing.",
        "",
    ]
    for finding in findings:
        lines.append(f"## `{finding.term}` — not found in any course material")
        lines.append("")
        lines.append(f"> {finding.claim}")
        lines.append("")
    return "\n".join(lines)


def _write_status(path: Path, **payload: Any) -> None:
    current = _load_json(path, {})
    current.update(payload)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


#: Statuses that describe a job which has stopped for a known reason. Only a
#: recorded "running" is ever reinterpreted against process liveness; a job
#: that reported its own ending told us something the OS cannot contradict.
TERMINAL_POSTPROCESS_STATUSES = frozenset(
    {"completed", "completed_with_warnings", "failed", "failed_to_launch", "interrupted"}
)


def apply_course_corrections(
    evidence: "SessionEvidence",
    corrections: tuple[tuple[str, str], ...],
) -> int:
    """Rewrite misheard phrases in the DERIVED evidence view, in place.

    ``transcript.jsonl`` and the audio are never touched: they are the
    authoritative record of what the recognizer actually produced, and every
    document already says so. What gets corrected is the working copy that
    reaches generation -- which is where an uncorrected mis-hearing turns into
    a stated definition in the user's notes.

    Returns the number of items changed, for the run log.
    """
    if not corrections:
        return 0

    interpreter = TerminologyInterpreter([], corrections=corrections)
    changed = 0
    for item in evidence.items:
        result = interpreter.interpret(item.text)
        if not result.changed:
            continue
        item.text = result.interpreted
        # Keep the original within reach: a correction is Ahmed's judgement,
        # and anyone auditing a note must be able to see what was actually
        # heard without going back to the raw journal.
        item.attributes.setdefault("raw_text", result.raw)
        item.attributes["corrections"] = [list(pair) for pair in result.corrections]
        changed += 1
    return changed


def write_running_status(path: Path) -> None:
    """Claim the post-class job for THIS process.

    Whoever is about to do the work stamps their own identity, so a manual
    rerun cannot inherit the PID of the launcher that died hours ago.
    """
    process = psutil.Process(os.getpid())
    _write_status(
        path,
        status="running",
        started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        error=None,
        pid=process.pid,
        pid_created_at=process.create_time(),
        completed_at=None,
    )


def postprocess_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Resolve a raw status record against whether its process is still alive.

    A process that is killed, power-cycled, or reaped never gets to write its
    own failure. Trusting the file alone therefore reports a dead job as
    healthy forever -- which is exactly how a real COT3400 lecture silently
    produced no notes on 2026-08-31. Liveness is the reader's job.
    """
    resolved = dict(payload)
    recorded = str(resolved.get("status") or "not_started")
    resolved["recorded_status"] = recorded

    # "launched" is as ambiguous as "running": the launcher writes it before the
    # child process writes its own "running", so a child that dies in between --
    # an import error, a missing dependency, an immediate crash -- leaves it
    # standing forever. Both mean "believed to be in progress"; neither is a
    # reported outcome.
    if recorded not in {"running", "launched"}:
        return resolved

    if process_identity_matches(resolved.get("pid"), resolved.get("pid_created_at")):
        return resolved

    resolved["status"] = "interrupted"
    resolved["error"] = resolved.get("error") or (
        "Post-class processing stopped without reporting a result: the process "
        "that claimed this job is no longer running. Re-run it with "
        "`python -m nova_capture.postprocess --session <path>`."
    )
    return resolved


def read_postprocess_status(session_path: str | Path) -> dict[str, Any]:
    """The trustworthy view of a session's post-class job."""
    path = Path(session_path).expanduser() / "postprocess.json"
    payload = _load_json(path, {})
    if not payload:
        return {"status": "not_started", "recorded_status": "not_started", "error": None}
    return postprocess_status_payload(payload)


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
    write_running_status(status_path)

    try:
        # Layer 2 (working intelligence): one authoritative read of every raw
        # journal this session produced. Markers, topic progression, live Q&A and
        # attachments reach generation through here; before this they were
        # captured and then silently dropped.
        session_evidence = load_session_evidence(session_path)
        # Corrections come from the structured store, not straight off the
        # file: the store is what knows which rules are CONFIRMED. A correction
        # NOVA merely inferred is retained there as a candidate and is
        # deliberately not applied -- one guess must not reach the notes.
        # A store failure degrades to the hand-written file rather than to no
        # corrections at all, because those rules are Ahmed's own ground truth.
        try:
            store = KnowledgeStore(default_knowledge_path())
            rules = active_corrections_for(course, store)
        except Exception:
            logger.exception("knowledge store unavailable; using file rules only")
            rules = load_course_corrections(course)
        corrected = apply_course_corrections(session_evidence, rules)
        if corrected:
            logger.info(
                "applied %s course correction(s) to derived class evidence", corrected
            )
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

        # One understanding of the lecture, built from small windows, then
        # rendered into every document. Replaces the old path, which sent the
        # same ~32k-character bundle to the model once per document and blew
        # past a stock Ollama's context on every one of them.
        request_token_limit, reserved_output_tokens = _generation_request_budget(
            os.environ
        )
        understanding = await build_understanding(
            session_evidence,
            route=_route,
            questions=questions,
            materials=materials_context,
            request_token_limit=request_token_limit,
            reserved_output_tokens=reserved_output_tokens,
        )
        write_understanding(session_path, understanding)
        if understanding.degraded:
            logger.warning(
                "lecture understanding is incomplete: %s",
                "; ".join(understanding.warnings()),
            )
        evidence_markdown = understanding_evidence_markdown(understanding)

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

        # A regeneration must not destroy the notes it replaces. Record what
        # prompted it, so "why did this change?" is answerable from the folder
        # itself rather than from someone's memory.
        archived = archive_existing_notes(
            folder,
            reason=(
                f"Regenerated {datetime.now().astimezone():%Y-%m-%d %H:%M}. "
                f"{corrected} correction(s) applied to derived evidence; "
                f"provider route: {'degraded' if understanding.degraded else 'normal'}."
            ),
        )
        if archived is not None:
            logger.info("previous notes preserved at %s", archived)

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

        # Every document is a view of the one understanding, so they cannot
        # disagree with each other, and rendering costs no model calls at all.
        generated = render_all(understanding)
        for filename, value in generated.items():
            (folder / filename).write_text(value, encoding="utf-8")

        # Independent evidence check, before Ahmed relies on any of this. The
        # corrections layer only repairs mishearings someone already knows
        # about; this catches novel ones by asking whether a definition's
        # central term appears anywhere in the slides the professor is teaching
        # from. Deliberately NOT another model call, and it MARKS rather than
        # deletes -- a real term the slides happen not to contain must survive.
        review_findings: list = []
        try:
            verification, _kinds = library.verification_material()
            review_findings = list(
                review_definitions(understanding.definitions, materials=verification)
            )
            if review_findings:
                (folder / "Review.md").write_text(
                    _render_review(review_findings, title=title, course=course),
                    encoding="utf-8",
                )
                logger.warning(
                    "note review flagged %s uncorroborated term(s)",
                    len(review_findings),
                )
        except Exception:
            logger.exception("note review failed; notes published unreviewed")

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

        # A run where the model failed on part of the lecture is NOT a clean
        # completion. On 2026-08-28 this reported "completed" while all five
        # documents had silently fallen back to an evidence dump.
        warnings = list(session_evidence.warnings) + understanding.warnings()
        _write_status(
            status_path,
            status="completed_with_warnings" if understanding.degraded else "completed",
            completed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            output_folder=str(folder),
            material_sources=[source.path for source in sources],
            presentation=str(presentation_path) if presentation_path else None,
            evidence_coverage=session_evidence.coverage(),
            evidence_warnings=warnings,
            understanding={
                "windows": len(understanding.windows),
                "degraded_windows": list(understanding.degraded_windows),
                "reduce_degraded": understanding.reduce_degraded,
                "sections": len(understanding.sections),
            },
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


#: Output-token budget for post-class generation.
#:
#: NOVA's shared provider defaults are 600 (Groq) and 400 (Ollama) output
#: tokens, which is right for a spoken specialist answer and far too small to
#: emit a structured lecture digest. On 2026-08-28 that returned an EMPTY
#: completion for every window -- "Groq returned an empty response" -- and the
#: whole class silently fell back to a dump. gpt-oss-120b is a reasoning model,
#: so it spends that budget thinking and never reaches the content.
#:
#: Post-processing runs in its own detached process, so raising the budget here
#: cannot affect live Q&A or the voice agent. An explicitly configured value
#: always wins.
#:
#: Capped at 4,000 rather than higher because Groq bills the RESERVED output
#: against its tokens-per-minute limit, not the tokens actually produced. On the
#: free tier that limit is 8,000 TPM, so a ~2,000-token window prompt plus a
#: 6,000-token reservation was rejected outright:
#:     413 - Request too large ... TPM: Limit 8000, Requested 8428
#: 4,000 leaves room for the prompt and is still far more than any window digest
#: needs -- a real one measured 4,163 characters, roughly 1,000 tokens.
CLASS_GENERATION_MAX_TOKENS = 4_000

_GENERATION_TOKEN_VARIABLES = (
    "GROQ_MAX_TOKENS",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OLLAMA_MAX_TOKENS",
)


def _raise_generation_output_budget(environment: Any) -> None:
    budget = environment.get(
        "NOVA_CLASS_GENERATION_MAX_TOKENS", str(CLASS_GENERATION_MAX_TOKENS)
    )
    for name in _GENERATION_TOKEN_VARIABLES:
        environment.setdefault(name, budget)


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _generation_request_budget(environment: Any) -> tuple[int, int]:
    """Return the real request limit and largest configured output reservation.

    ``_route`` may fall through several providers. Their explicit output-token
    settings are allowed to differ, so Class Intelligence protects against the
    largest reservation that could actually be sent rather than assuming the
    default 4,000-token postprocess budget.
    """
    request_limit = _positive_int(
        environment.get("NOVA_CLASS_REQUEST_TOKEN_LIMIT"),
        DEFAULT_REQUEST_TOKEN_LIMIT,
    )
    reservations: list[int] = []
    for name in _GENERATION_TOKEN_VARIABLES:
        value = environment.get(name)
        if value in (None, ""):
            continue
        parsed = _positive_int(value, 0)
        if parsed > 0:
            reservations.append(parsed)
    reserved = max(reservations, default=DEFAULT_RESERVED_OUTPUT_TOKENS)
    return request_limit, reserved


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova-class-postprocess")
    parser.add_argument("--session", required=True)
    return parser


def main() -> int:
    # Post-processing is normally spawned by class_capture.py, which has
    # already loaded the environment, so the child inherits the provider
    # credentials. A MANUAL rerun does not -- and on 2026-08-28 that silently
    # reduced 'regenerate my notes' to a local-only run reporting every
    # provider as 'not_configured'. load_dotenv never overrides an existing
    # variable, so this is a no-op in the spawned case.
    from dotenv import load_dotenv

    load_dotenv(".env.local")
    load_dotenv(".env")
    _raise_generation_output_budget(os.environ)

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

    # Record the child's process IDENTITY, not just its number. A bare PID
    # proves nothing once the OS recycles it, and this status has to survive
    # until the child overwrites it with its own "running".
    try:
        pid_created_at = psutil.Process(process.pid).create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # The child is already gone, or unreadable. Leaving the identity out
        # makes the reader resolve this to "interrupted", which is the honest
        # answer: we cannot show that anything is running.
        pid_created_at = None

    _write_status(
        status_path,
        status="launched",
        pid=process.pid,
        pid_created_at=pid_created_at,
    )
    return process.pid
