from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from nova_capture.storage import ClassCaptureStorage

from .materials import SUPPORTED_MATERIAL_EXTENSIONS, extract_text
from .paths import course_materials_root, course_sessions_root


_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_+.#/-]*")

_STT_STOPWORDS = {
    "about", "after", "again", "also", "another", "because", "been", "before",
    "being", "between", "both", "class", "could", "course", "does", "each",
    "from", "have", "into", "more", "most", "other", "over", "same", "session",
    "should", "some", "than", "that", "their", "there", "these", "they", "this",
    "through", "under", "using", "very", "what", "when", "where", "which", "while",
    "with", "would", "your", "will", "were", "then", "them", "such", "only",
}
_STT_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+.#/-]{3,}")



@dataclass(slots=True)
class ContextSource:
    path: str
    source_kind: str
    chars: int
    score: float


@dataclass(slots=True)
class AttachmentRecord:
    source: str
    destination: str
    sha256: str
    attached_at: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _query_terms(query: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD_RE.findall(query or "")
        if len(token) >= 3
    }


def _score_text(text: str, query: str, *, recency_rank: int = 0) -> float:
    terms = _query_terms(query)
    lowered = text.casefold()
    hit_score = sum(1 for term in terms if term in lowered)
    return float(hit_score) + max(0.0, 0.25 - recency_rank * 0.02)


def attach_material_to_session(source: Path, session_path: Path) -> AttachmentRecord:
    source = source.expanduser().resolve()
    session_path = session_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in SUPPORTED_MATERIAL_EXTENSIONS:
        raise ValueError(f"Unsupported class material: {source.suffix or '(no extension)'}")
    if not session_path.is_dir():
        raise FileNotFoundError(session_path)

    folder = session_path / "Materials"
    folder.mkdir(parents=True, exist_ok=True)
    source_hash = _sha256(source)
    destination = folder / source.name

    if destination.exists():
        if destination.is_file() and _sha256(destination) == source_hash:
            pass
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            destination = folder / f"{source.stem} ({stamp}){source.suffix}"
            shutil.copy2(source, destination)
    else:
        shutil.copy2(source, destination)

    record = AttachmentRecord(
        source=str(source),
        destination=str(destination),
        sha256=source_hash,
        attached_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    ClassCaptureStorage.append_jsonl(
        session_path / "attachments.jsonl",
        asdict(record),
    )
    return record


class CourseContextLibrary:
    """Read the best relevant course/session context without moving originals."""

    def __init__(
        self,
        course_code: str,
        *,
        session_path: Path | None = None,
        max_files: int = 18,
        max_chars: int = 36_000,
        per_file_chars: int = 7_000,
    ) -> None:
        self.course_code = course_code.strip()
        self.session_path = session_path.expanduser().resolve() if session_path else None
        self.max_files = max(1, int(max_files))
        self.max_chars = max(4_000, int(max_chars))
        self.per_file_chars = max(1_000, int(per_file_chars))

    def _candidate_files(self) -> list[tuple[Path, str]]:
        candidates: list[tuple[Path, str]] = []

        material_root = course_materials_root(self.course_code)
        if material_root.is_dir():
            for path in material_root.rglob("*"):
                if path.is_file() and path.suffix.lower() in SUPPORTED_MATERIAL_EXTENSIONS:
                    candidates.append((path, "course_material"))

        if self.session_path is not None:
            attachment_root = self.session_path / "Materials"
            if attachment_root.is_dir():
                for path in attachment_root.rglob("*"):
                    if path.is_file() and path.suffix.lower() in SUPPORTED_MATERIAL_EXTENSIONS:
                        candidates.append((path, "session_attachment"))

        sessions_root = course_sessions_root(self.course_code)
        if sessions_root.is_dir():
            prior_markdown = sorted(
                (path for path in sessions_root.rglob("*.md") if path.is_file()),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )[:12]
            candidates.extend((path, "prior_note") for path in prior_markdown)

        # Deduplicate exact paths while favoring session attachments first.
        priority = {"session_attachment": 0, "course_material": 1, "prior_note": 2}
        unique: dict[Path, str] = {}
        for path, kind in sorted(candidates, key=lambda item: priority[item[1]]):
            unique.setdefault(path.resolve(), kind)
        return list(unique.items())

    def build_context(self, query: str = "") -> tuple[str, list[ContextSource]]:
        ranked: list[tuple[float, int, Path, str, str]] = []
        for rank, (path, kind) in enumerate(self._candidate_files()):
            try:
                text = extract_text(path, max_chars=self.per_file_chars)
            except Exception:
                continue
            text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
            if not text:
                continue
            score = _score_text(text, query, recency_rank=rank)
            if kind == "session_attachment":
                score += 2.0
            elif kind == "course_material":
                score += 1.0
            ranked.append((score, rank, path, kind, text))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        parts: list[str] = []
        sources: list[ContextSource] = []
        used = 0
        for score, _, path, kind, text in ranked[: self.max_files]:
            remaining = self.max_chars - used
            if remaining <= 0:
                break
            excerpt = text[:remaining]
            header = f"SOURCE: {path.name} ({kind})"
            parts.append(f"{header}\n{excerpt}")
            sources.append(ContextSource(str(path), kind, len(excerpt), score))
            used += len(excerpt)

        return "\n\n---\n\n".join(parts), sources


    #: Source kinds that a human authored. NOVA's own prior notes are excluded
    #: deliberately -- see `verification_material`.
    HUMAN_SOURCE_KINDS = ("course_material", "session_attachment")

    def verification_material(self) -> tuple[str, tuple[str, ...]]:
        """Course evidence suitable for CHECKING NOVA's own generated content.

        `build_context` deliberately includes `prior_note` sources so a live
        answer has continuity with earlier lectures. That is exactly wrong for
        verification: those notes are NOVA's own output, so a fabrication
        corroborates itself.

        This was not hypothetical. On the real COT3400 course, "GNRO" -- a
        mishearing of `g(n)` that generation had promoted into a definition --
        appeared in `Lecture.md`, `Study.md` and `Questions.md`. Checking the
        definition against a pool containing those files found "support" for it
        and flagged nothing.

        So verification sees only what a human wrote: slides, handouts, and
        materials Ahmed attached. Same boundary `HUMAN_PROVENANCE` draws in
        `nova_capture/evidence.py`.

        Returns the text and the source kinds that contributed, so a caller can
        assert what it was actually checked against.
        """
        parts: list[str] = []
        kinds: list[str] = []
        for path, kind in self._candidate_files():
            if kind not in self.HUMAN_SOURCE_KINDS:
                continue
            try:
                text = extract_text(path, max_chars=self.per_file_chars)
            except Exception:
                continue
            if not text.strip():
                continue
            parts.append(text)
            kinds.append(kind)
        return "\n\n".join(parts), tuple(dict.fromkeys(kinds))

    def build_stt_keyterms(
        self,
        seed_terms: list[str] | tuple[str, ...],
        *,
        limit: int = 100,
        max_material_terms: int = 30,
    ) -> list[str]:
        """Build bounded Nova-3 keyterms from trusted source materials.

        Curated course/domain terms are always preferred. Generated prior
        notes/transcripts are intentionally excluded from STT prompting so an
        earlier ASR mistake cannot become a future Deepgram keyterm.
        """
        maximum = max(1, min(100, int(limit)))
        material_budget = max(0, min(int(max_material_terms), maximum))
        output: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> bool:
            cleaned = re.sub(r"\s+", " ", str(value or "")).strip(
                " \t\r\n-_:;,.()[]{}"
            )
            key = cleaned.casefold()
            if not cleaned or key in seen or len(output) >= maximum:
                return False
            if len(cleaned) > 80:
                return False
            seen.add(key)
            output.append(cleaned)
            return True

        for value in seed_terms:
            add(value)

        if len(output) >= maximum or material_budget <= 0:
            return output[:maximum]

        # Only original/attached course materials are trusted for STT mining.
        # prior_note includes NOVA-generated notes and raw transcripts, which
        # can contain ASR mistakes and must never feed those mistakes back into
        # the recognizer.
        trusted_candidates = [
            (path, kind)
            for path, kind in self._candidate_files()
            if kind in {"session_attachment", "course_material"}
        ][:18]

        token_counts: Counter[str] = Counter()
        heading_candidates: list[str] = []

        for path, _kind in trusted_candidates:
            stem = re.sub(r"[_-]+", " ", path.stem)
            add(stem)
            for token in _STT_WORD.findall(stem):
                token_counts[token] += 4

            try:
                material_text = extract_text(path, max_chars=10_000)
            except Exception:
                continue

            for raw_line in material_text.splitlines():
                line = re.sub(r"\s+", " ", raw_line).strip()
                words = _STT_WORD.findall(line)
                if 1 <= len(words) <= 7 and 4 <= len(line) <= 80:
                    heading_candidates.append(line)

                for token in words:
                    lowered = token.casefold().strip("./-")
                    if (
                        len(lowered) >= 5
                        and lowered not in _STT_STOPWORDS
                        and not lowered.isdigit()
                    ):
                        token_counts[token] += 1

        material_added = 0
        ranked_tokens = sorted(
            token_counts.items(),
            key=lambda item: (-item[1], -len(item[0]), item[0].casefold()),
        )
        for token, count in ranked_tokens:
            if count < 2:
                continue
            if add(token):
                material_added += 1
            if len(output) >= maximum or material_added >= material_budget:
                return output

        for heading in heading_candidates[:40]:
            if len(heading.split()) > 5:
                continue
            if heading.endswith((".", "?", "!")):
                continue
            if add(heading):
                material_added += 1
            if len(output) >= maximum or material_added >= material_budget:
                break

        return output

    def write_stt_keyterms_manifest(self, terms: list[str]) -> Path | None:
        if self.session_path is None:
            return None
        path = self.session_path / "stt_keyterms.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "course": self.course_code,
                    "count": len(terms),
                    "terms": list(terms),
                    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    def write_context_manifest(self) -> Path | None:
        if self.session_path is None:
            return None
        _, sources = self.build_context("")
        path = self.session_path / "context_sources.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "course": self.course_code,
                    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "sources": [asdict(item) for item in sources],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        return path


def organize_recent_downloads_for_course(
    course_code: str,
    *,
    lookback_days: int = 30,
    max_files: int = 60,
) -> list:
    """Safely copy recent high-confidence Downloads that match one course.

    This is a bounded one-time scan used at class start. It never deletes or
    moves originals and never accepts a file classified to a different course.
    """
    import time

    from .automation import default_download_directories
    from .organizer import SchoolMaterialOrganizer, classify_file
    from .registry import CourseRegistry

    registry = CourseRegistry()
    organizer = SchoolMaterialOrganizer(registry=registry)
    cutoff = time.time() - max(1, int(lookback_days)) * 86400
    candidates: list[Path] = []
    for folder in default_download_directories():
        try:
            files = list(folder.iterdir())
        except OSError:
            continue
        for path in files:
            try:
                if (
                    path.is_file()
                    and path.suffix.lower() in SUPPORTED_MATERIAL_EXTENSIONS
                    and path.stat().st_mtime >= cutoff
                ):
                    candidates.append(path)
            except OSError:
                continue

    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    results = []
    for path in candidates[: max(1, int(max_files))]:
        classification = classify_file(path, registry=registry)
        if (
            classification.course is None
            or classification.course.code != course_code
            or classification.confidence < 0.80
        ):
            continue
        results.append(organizer.organize(path, minimum_confidence=0.80))
    return results
