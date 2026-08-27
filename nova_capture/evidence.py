"""Session Evidence Model V1 — the authoritative read of one class session.

This module sits between RAW EVIDENCE (the append-only ``*.jsonl`` files the
live capture writes) and HUMAN STUDY OUTPUT (notes, study guides, slides). It
owns exactly one job: turn every raw artifact a session recorded into a single
ordered, provenance-carrying, deterministically serializable structure.

Design constraints this module deliberately honors:

* **Raw evidence is never replaced.** Nothing here writes to ``transcript.jsonl``
  or any other capture journal; it only reads them.
* **Deterministic.** :meth:`SessionEvidence.to_dict` carries no clock reads, so
  the same raw files always produce byte-identical output. The generation
  timestamp is added by :func:`write_session_evidence`, not by the model.
* **Tolerant.** A missing or corrupt journal degrades that one evidence kind and
  is reported in ``warnings``; it never blocks the rest of the session.
* **Model-free.** No LLM calls and no prompt construction; selection and ranking
  are deterministic. It does render two Markdown views of the evidence
  (:func:`lecture_timeline_markdown`, :func:`evidence_digest_markdown`) for
  consumers to embed, but it makes no decision about where anything is stored
  beyond its own serialization.

It is intentionally distinct from ``nova_knowledge.EvidenceManifest``, which
records *which source files* fed a session (sha256, import disposition). This
module records *what was actually said*, when, and by whom.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Iterator

from .storage import ClassCaptureStorage


logger = logging.getLogger("nova.class_capture.evidence")

#: 2 added the derived ``structure`` block (see :func:`derive_lecture_structure`).
EVIDENCE_SCHEMA_VERSION = 2
EVIDENCE_FILENAME = "session_evidence.json"

# Raw journals this model reads. Order is stable so provenance is deterministic.
_SOURCE_FILES = (
    "session.json",
    "transcript.jsonl",
    "questions.jsonl",
    "markers.jsonl",
    "topics.jsonl",
    "speaker_roles.json",
    "attachments.jsonl",
    "live_qa_events.jsonl",
)

_WHITESPACE = re.compile(r"\s+")


class EvidenceKind(StrEnum):
    """What kind of thing an evidence item is."""

    TRANSCRIPT = "transcript"
    QUESTION = "question"
    ANSWER = "answer"
    MARKER = "marker"
    TOPIC = "topic"
    ATTACHMENT = "attachment"


class Provenance(StrEnum):
    """Where an evidence item came from.

    This is the trust boundary that keeps generated content from being mistaken
    for something the professor actually said.
    """

    CAPTURED_AUDIO = "captured_audio"
    USER_MARKED = "user_marked"
    NOVA_LIVE_ANSWER = "nova_live_answer"
    SOURCE_MATERIAL = "source_material"
    #: Structure NOVA reconstructed from captured evidence. It is grounded in
    #: the professor's own words but is NOT something the professor said or
    #: labelled, so it must never be presented as a professor statement.
    NOVA_DERIVED = "nova_derived"


#: Provenance values that represent something a human actually said or did.
#: Anything outside this set is NOVA output and must be labeled as such.
HUMAN_PROVENANCE = frozenset(
    {
        Provenance.CAPTURED_AUDIO,
        Provenance.USER_MARKED,
        Provenance.SOURCE_MATERIAL,
    }
)


def normalize_text(value: Any) -> str:
    """Collapse whitespace so IDs stay stable across trivial reformatting."""
    return _WHITESPACE.sub(" ", str(value or "")).strip()


def _coerce_seconds(value: Any, *, default: float = 0.0) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    if seconds != seconds:  # NaN
        return default
    return max(0.0, seconds)


def evidence_id(kind: EvidenceKind, ordinal: int, start_seconds: float, text: str) -> str:
    """Build a stable, deterministic ID for one evidence item.

    The ordinal is included so two identical utterances at the same timestamp
    still get distinct IDs, and the text is normalized so re-serializing the raw
    journal with different whitespace does not renumber the whole session.
    """
    payload = f"{kind.value}|{ordinal}|{start_seconds:.3f}|{normalize_text(text)}"
    digest = hashlib.blake2s(payload.encode("utf-8"), digest_size=6).hexdigest()
    return f"{kind.value[:2]}_{digest}"


def format_elapsed(seconds: float) -> str:
    """Render lecture-relative seconds as ``MM:SS`` or ``H:MM:SS``."""
    total = int(_coerce_seconds(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass(slots=True)
class EvidenceItem:
    """One grounded thing that happened during a class session."""

    evidence_id: str
    kind: EvidenceKind
    provenance: Provenance
    start_seconds: float
    text: str
    end_seconds: float | None = None
    speaker_id: str | None = None
    speaker_role: str | None = None
    speaker_label: str | None = None
    topic: str | None = None
    confidence: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_human_evidence(self) -> bool:
        return self.provenance in HUMAN_PROVENANCE

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        payload["provenance"] = self.provenance.value
        return payload


@dataclass(slots=True)
class SourceFile:
    """Provenance record for one raw journal this model read."""

    name: str
    exists: bool
    bytes: int = 0
    sha256: str = ""
    records: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SessionEvidence:
    """Every grounded item one class session produced, in chronological order."""

    session_id: str
    course: str
    title: str
    items: list[EvidenceItem] = field(default_factory=list)
    speakers: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[SourceFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: int = EVIDENCE_SCHEMA_VERSION

    # -- views ---------------------------------------------------------------

    def by_kind(self, *kinds: EvidenceKind) -> list[EvidenceItem]:
        wanted = set(kinds)
        return [item for item in self.items if item.kind in wanted]

    @property
    def transcript(self) -> list[EvidenceItem]:
        return self.by_kind(EvidenceKind.TRANSCRIPT)

    @property
    def markers(self) -> list[EvidenceItem]:
        return self.by_kind(EvidenceKind.MARKER)

    @property
    def questions(self) -> list[EvidenceItem]:
        return self.by_kind(EvidenceKind.QUESTION)

    @property
    def topics(self) -> list[EvidenceItem]:
        return self.by_kind(EvidenceKind.TOPIC)

    @property
    def duration_seconds(self) -> float:
        if not self.items:
            return 0.0
        return max(
            max(item.start_seconds, item.end_seconds or 0.0) for item in self.items
        )

    def speaker_label(self, speaker_id: str | None, role: str | None = None) -> str:
        if speaker_id is not None:
            resolved = self.speakers.get(str(speaker_id))
            if isinstance(resolved, dict):
                label = resolved.get("label")
                if label:
                    return str(label)
        if role and role != "unknown":
            return str(role).title()
        return f"Speaker {speaker_id}" if speaker_id is not None else "Unknown speaker"

    def coverage(self) -> dict[str, int]:
        """Counts per evidence kind — cheap health signal for logs and status."""
        counts = {kind.value: 0 for kind in EvidenceKind}
        for item in self.items:
            counts[item.kind.value] += 1
        return counts

    def lecture_structure(self) -> list["LectureSection"]:
        """The lecture's topic progression — captured if present, else derived."""
        return derive_lecture_structure(self)

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Deterministic payload. Contains no clock reads by design."""
        return {
            "schema_version": self.schema_version,
            "layer": "working_intelligence",
            "session_id": self.session_id,
            "course": self.course,
            "title": self.title,
            "duration_seconds": round(self.duration_seconds, 3),
            "coverage": self.coverage(),
            "speakers": self.speakers,
            "metadata": self.metadata,
            "sources": [source.to_dict() for source in self.sources],
            "warnings": list(self.warnings),
            "structure": [section.to_dict() for section in self.lecture_structure()],
            "items": [item.to_dict() for item in self.items],
        }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        logger.warning("could not read class evidence file: %s", path.name)
        return default


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return well-formed records plus the count of lines that failed to parse."""
    records: list[dict[str, Any]] = []
    skipped = 0
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return records, skipped
    except OSError:
        logger.warning("could not read class evidence journal: %s", path.name)
        return records, skipped

    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            skipped += 1
    return records, skipped


def _describe_source(path: Path, records: int) -> SourceFile:
    try:
        raw = path.read_bytes()
    except OSError:
        return SourceFile(name=path.name, exists=False)
    return SourceFile(
        name=path.name,
        exists=True,
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        records=records,
    )


def _speaker_map(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    speakers = payload.get("speakers")
    if not isinstance(speakers, dict):
        return {}
    return {
        str(key): value for key, value in speakers.items() if isinstance(value, dict)
    }


def load_session_evidence(session_path: str | Path) -> SessionEvidence:
    """Read every raw journal in ``session_path`` into one ordered evidence model.

    Missing files are normal (a session with no markers has no ``markers.jsonl``
    content) and are recorded in ``sources`` rather than raised.
    """
    root = Path(session_path).expanduser().resolve()

    metadata = _read_json(root / "session.json", {})
    if not isinstance(metadata, dict):
        metadata = {}

    speaker_payload = _read_json(root / "speaker_roles.json", {})
    speakers = _speaker_map(speaker_payload)

    transcript_rows, transcript_skipped = _read_jsonl(root / "transcript.jsonl")
    question_rows, question_skipped = _read_jsonl(root / "questions.jsonl")
    marker_rows, marker_skipped = _read_jsonl(root / "markers.jsonl")
    topic_rows, topic_skipped = _read_jsonl(root / "topics.jsonl")
    attachment_rows, attachment_skipped = _read_jsonl(root / "attachments.jsonl")

    evidence = SessionEvidence(
        session_id=str(metadata.get("session_id") or root.name),
        course=str(metadata.get("course") or root.parent.name),
        title=str(metadata.get("title") or "Class Session"),
        speakers=speakers,
        metadata={
            key: metadata.get(key)
            for key in (
                "started_at",
                "stopped_at",
                "status",
                "capture_version",
                "audio_enabled",
                "transcript_segment_count",
                "question_count",
            )
            if key in metadata
        },
    )

    items: list[EvidenceItem] = []

    for ordinal, row in enumerate(transcript_rows):
        text = normalize_text(row.get("text"))
        if not text:
            continue
        start = _coerce_seconds(row.get("start_seconds"))
        speaker_id = row.get("speaker_id")
        speaker_id = str(speaker_id) if speaker_id is not None else None
        role = str(row.get("speaker") or "unknown")
        items.append(
            EvidenceItem(
                evidence_id=evidence_id(EvidenceKind.TRANSCRIPT, ordinal, start, text),
                kind=EvidenceKind.TRANSCRIPT,
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=start,
                end_seconds=_coerce_seconds(row.get("end_seconds"), default=start),
                text=text,
                speaker_id=speaker_id,
                speaker_role=role,
                speaker_label=evidence.speaker_label(speaker_id, role),
                topic=row.get("topic") or None,
                confidence=_coerce_seconds(row.get("speaker_confidence")),
                attributes={"is_question": bool(row.get("is_question"))},
            )
        )

    for ordinal, row in enumerate(question_rows):
        text = normalize_text(row.get("question"))
        if not text:
            continue
        start = _coerce_seconds(row.get("timestamp_seconds"))
        speaker_id = row.get("speaker_id")
        speaker_id = str(speaker_id) if speaker_id is not None else None
        role = str(row.get("speaker") or "unknown")
        items.append(
            EvidenceItem(
                evidence_id=evidence_id(EvidenceKind.QUESTION, ordinal, start, text),
                kind=EvidenceKind.QUESTION,
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=start,
                text=text,
                speaker_id=speaker_id,
                speaker_role=role,
                speaker_label=evidence.speaker_label(speaker_id, role),
                topic=row.get("topic") or None,
                attributes={"study_value": str(row.get("study_value") or "unknown")},
            )
        )

        answer = normalize_text(row.get("answer"))
        if answer:
            items.append(
                EvidenceItem(
                    evidence_id=evidence_id(EvidenceKind.ANSWER, ordinal, start, answer),
                    kind=EvidenceKind.ANSWER,
                    provenance=Provenance.NOVA_LIVE_ANSWER,
                    start_seconds=start,
                    text=answer,
                    topic=row.get("topic") or None,
                    attributes={"answers_question": text},
                )
            )

    for ordinal, row in enumerate(marker_rows):
        label = normalize_text(row.get("label"))
        start = _coerce_seconds(row.get("timestamp_seconds"))
        kind_value = str(row.get("kind") or "bookmark")
        items.append(
            EvidenceItem(
                evidence_id=evidence_id(EvidenceKind.MARKER, ordinal, start, label or kind_value),
                kind=EvidenceKind.MARKER,
                provenance=Provenance.USER_MARKED,
                start_seconds=start,
                text=label or kind_value.replace("_", " ").title(),
                topic=row.get("topic") or None,
                attributes={"marker_kind": kind_value},
            )
        )

    for ordinal, row in enumerate(topic_rows):
        topic = normalize_text(row.get("topic"))
        if not topic:
            continue
        start = _coerce_seconds(row.get("start_seconds"))
        items.append(
            EvidenceItem(
                evidence_id=evidence_id(EvidenceKind.TOPIC, ordinal, start, topic),
                kind=EvidenceKind.TOPIC,
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=start,
                text=topic,
                topic=topic,
                attributes={
                    "subtopic": row.get("subtopic") or None,
                    "summary": normalize_text(row.get("summary")),
                },
            )
        )

    for ordinal, row in enumerate(attachment_rows):
        destination = str(row.get("destination") or "")
        if not destination:
            continue
        items.append(
            EvidenceItem(
                evidence_id=evidence_id(EvidenceKind.ATTACHMENT, ordinal, 0.0, destination),
                kind=EvidenceKind.ATTACHMENT,
                provenance=Provenance.SOURCE_MATERIAL,
                start_seconds=0.0,
                text=Path(destination).name,
                attributes={
                    "destination": destination,
                    "sha256": str(row.get("sha256") or ""),
                    "attached_at": str(row.get("attached_at") or ""),
                },
            )
        )

    # Chronological, with a stable tie-break so serialization is reproducible.
    _KIND_ORDER = {
        EvidenceKind.TOPIC: 0,
        EvidenceKind.MARKER: 1,
        EvidenceKind.TRANSCRIPT: 2,
        EvidenceKind.QUESTION: 3,
        EvidenceKind.ANSWER: 4,
        EvidenceKind.ATTACHMENT: 5,
    }
    items.sort(
        key=lambda item: (
            item.start_seconds,
            _KIND_ORDER[item.kind],
            item.evidence_id,
        )
    )
    evidence.items = items

    counts = {
        "transcript.jsonl": len(transcript_rows),
        "questions.jsonl": len(question_rows),
        "markers.jsonl": len(marker_rows),
        "topics.jsonl": len(topic_rows),
        "attachments.jsonl": len(attachment_rows),
    }
    evidence.sources = [
        _describe_source(root / name, counts.get(name, 0)) for name in _SOURCE_FILES
    ]

    for name, skipped in (
        ("transcript.jsonl", transcript_skipped),
        ("questions.jsonl", question_skipped),
        ("markers.jsonl", marker_skipped),
        ("topics.jsonl", topic_skipped),
        ("attachments.jsonl", attachment_skipped),
    ):
        if skipped:
            evidence.warnings.append(f"{name}: skipped {skipped} malformed record(s)")

    return evidence


def write_session_evidence(
    session_path: str | Path,
    evidence: SessionEvidence,
    *,
    generated_at: str | None = None,
) -> Path:
    """Persist the derived evidence model beside the raw journals.

    The generation timestamp lives here rather than in
    :meth:`SessionEvidence.to_dict` so the model itself stays deterministic and
    diffable across re-runs.
    """
    target = Path(session_path).expanduser().resolve() / EVIDENCE_FILENAME
    payload = evidence.to_dict()
    if generated_at is not None:
        payload["generated_at"] = generated_at
    ClassCaptureStorage.write_json(target, payload)
    return target


# ---------------------------------------------------------------------------
# Lecture structure (topic progression)
# ---------------------------------------------------------------------------
#
# The live capture never records topics: ``LectureContext.set_topic`` and
# ``TopicTracker.update`` have no production callers, so ``topics.jsonl`` is
# always empty and every ``topic`` field on every record is ``None``. The
# professor's intellectual progression — the one thing lecture notes most need
# to preserve — was therefore absent from every session.
#
# Rather than make the live recorder do topic detection (a model call in the
# hot path, and a change to a stabilized capture loop), the progression is
# reconstructed afterwards from the transcript itself using lexical cohesion —
# a deterministic, offline TextTiling-style pass. Captured topics, if the
# recorder ever starts writing them, always win over derived ones.

#: Speech-heavy stopwords. Deliberately local so this module keeps its
#: stdlib-only dependency surface.
_STRUCTURE_STOPWORDS = frozenset(
    """
    a about actually after again all also am an and another any anything are as at
    back be because been before being between both but by can cant come could did
    do does doing done dont down each else even every everything first for from get
    gets getting go going good got had has have having he her here hers him his how
    i if im in into is it its itself just kind know last let like little look lot
    made make makes many may maybe me mean means might more most much must my need
    no not now of off ok okay on once one only or other our out over own part people
    put really right said same say says see seen she should show so some something
    sort still such sure take talk than that thats the their them then there these
    they thing things think this those though thought three through time to today
    together too two under up us use used uses using very want was way we well were
    what when where which while who why will with within without would yeah yes yet
    you your youre
    """.split()
)

_STRUCTURE_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_+#/.-]{2,}")

#: Tuning. Blocks are the unit of cohesion comparison; a lecture shorter than a
#: couple of blocks simply becomes one section.
_BLOCK_TOKENS = 60
_COMPARISON_BLOCKS = 2
#: Minimum section length is enforced in TIME, not in blocks, so boundary
#: resolution does not silently depend on how token-dense the speech is.
_MIN_SECTION_SECONDS = 90.0
_MIN_BLOCK_SEPARATION = 2
#: A lecture's note headings stop being useful past roughly a dozen sections, so
#: the minimum section length grows with the lecture. Without this a 90-minute
#: class fragments into ~34 headings; with it the same class yields ~12.
_MAX_SECTIONS = 12
#: Hearst's TextTiling cutoff: boundaries are gaps whose depth score exceeds
#: mean - std/2. Proposing generously and folding short spans afterwards is the
#: safer error direction — a missed boundary silently loses a topic, whereas an
#: extra boundary is absorbed by the ``min_section_seconds`` fold below.
_DEPTH_CUTOFF_FACTOR = 0.5


@dataclass(slots=True)
class LectureSection:
    """One stretch of the lecture that hangs together on a single subject."""

    section_id: str
    ordinal: int
    start_seconds: float
    end_seconds: float
    label: str
    keywords: list[str] = field(default_factory=list)
    provenance: Provenance = Provenance.NOVA_DERIVED
    transcript_count: int = 0
    marker_ids: list[str] = field(default_factory=list)
    question_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)

    @property
    def is_derived(self) -> bool:
        return self.provenance is Provenance.NOVA_DERIVED

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provenance"] = self.provenance.value
        payload["duration_seconds"] = round(self.duration_seconds, 3)
        return payload


def _structure_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _STRUCTURE_TOKEN.finditer(text):
        # Trailing punctuation rides along with the regex (e.g. "exam." at the
        # end of a sentence) and would otherwise leak into section labels.
        token = match.group(0).casefold().strip("._-/#+")
        if len(token) < 3 or token.isdigit() or token in _STRUCTURE_STOPWORDS:
            continue
        tokens.append(token)
    return tokens


@dataclass(slots=True)
class _Block:
    start_seconds: float
    end_seconds: float
    tokens: list[str]
    item_count: int


def _build_blocks(transcript: list[EvidenceItem]) -> list[_Block]:
    blocks: list[_Block] = []
    tokens: list[str] = []
    start = 0.0
    end = 0.0
    count = 0
    for item in transcript:
        if count == 0:
            start = item.start_seconds
        end = max(end, item.end_seconds or item.start_seconds)
        tokens.extend(_structure_tokens(item.text))
        count += 1
        if len(tokens) >= _BLOCK_TOKENS:
            blocks.append(_Block(start, end, tokens, count))
            tokens, count = [], 0
    if tokens:
        blocks.append(_Block(start, end, tokens, count))
    return blocks


def _cosine(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0
    shared = left.keys() & right.keys()
    if not shared:
        return 0.0
    dot = sum(left[token] * right[token] for token in sorted(shared))
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _window_counts(blocks: list[_Block], start: int, stop: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks[max(0, start):max(0, stop)]:
        for token in block.tokens:
            counts[token] = counts.get(token, 0) + 1
    return counts


def _cohesion_boundaries(blocks: list[_Block]) -> list[int]:
    """Return block indices where a new section starts (TextTiling depth scores)."""
    gaps = len(blocks) - 1
    if gaps < 2:
        return []

    similarity = [
        _cosine(
            _window_counts(blocks, gap + 1 - _COMPARISON_BLOCKS, gap + 1),
            _window_counts(blocks, gap + 1, gap + 1 + _COMPARISON_BLOCKS),
        )
        for gap in range(gaps)
    ]

    depths: list[float] = []
    for gap, value in enumerate(similarity):
        left = value
        index = gap - 1
        while index >= 0 and similarity[index] >= left:
            left = similarity[index]
            index -= 1
        right = value
        index = gap + 1
        while index < gaps and similarity[index] >= right:
            right = similarity[index]
            index += 1
        depths.append((left - value) + (right - value))

    positive = [depth for depth in depths if depth > 0.0]
    if not positive:
        return []
    mean = sum(positive) / len(positive)
    variance = sum((depth - mean) ** 2 for depth in positive) / len(positive)
    cutoff = mean - _DEPTH_CUTOFF_FACTOR * math.sqrt(variance)

    candidates = sorted(
        (gap for gap, depth in enumerate(depths) if depth >= cutoff and depth > 0.0),
        key=lambda gap: (-depths[gap], gap),
    )

    chosen: list[int] = []
    for gap in candidates:
        boundary = gap + 1
        if all(abs(boundary - existing) >= _MIN_BLOCK_SEPARATION for existing in chosen):
            chosen.append(boundary)
    return sorted(chosen)


def _label_sections(
    spans: list[tuple[int, int]],
    blocks: list[_Block],
    boosted: list[set[str]],
) -> list[tuple[str, list[str]]]:
    """Name each span by the terms that distinguish it from the rest of the lecture."""
    section_counts: list[dict[str, int]] = []
    for start, stop in spans:
        section_counts.append(_window_counts(blocks, start, stop))

    document_frequency: dict[str, int] = {}
    for counts in section_counts:
        for token in counts:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    total = max(1, len(section_counts))
    labels: list[tuple[str, list[str]]] = []
    for index, counts in enumerate(section_counts):
        scored: list[tuple[float, str]] = []
        for token, count in counts.items():
            if len(token) < 4:
                continue
            idf = math.log(total / document_frequency.get(token, 1)) + 1.0
            score = (1.0 + math.log(count)) * idf
            if token in boosted[index]:
                # Terms Ahmed marked or that were asked about are human-salient.
                score *= 1.6
            scored.append((score, token))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        keywords = [token for _, token in scored[:4]]
        if keywords:
            label = ", ".join(word.title() for word in keywords[:3])
        else:
            label = f"Section {index + 1}"
        labels.append((label, keywords))
    return labels


def derive_lecture_structure(
    evidence: SessionEvidence,
    *,
    min_section_seconds: float = _MIN_SECTION_SECONDS,
) -> list[LectureSection]:
    """Reconstruct the lecture's topic progression from captured evidence.

    Captured topics win when the recorder actually wrote any. Otherwise the
    progression is derived from lexical cohesion in the professor's own words.
    Fully deterministic: same evidence always yields the same sections.
    """
    captured = evidence.topics
    if captured:
        return _sections_from_captured_topics(evidence, captured)

    transcript = evidence.transcript
    blocks = _build_blocks(transcript)
    if not blocks:
        return []

    boundaries = _cohesion_boundaries(blocks)
    effective_minimum = max(
        max(0.0, float(min_section_seconds)),
        evidence.duration_seconds / _MAX_SECTIONS,
    )
    # Walk the proposed boundaries and only close a section once it has actually
    # accumulated enough lecture time. Accumulating (rather than folding into the
    # previous section) is what keeps a long lecture from collapsing into one
    # giant heading.
    spans: list[tuple[int, int]] = []
    start_block = 0
    for boundary in [*boundaries, len(blocks)]:
        if boundary <= start_block:
            continue
        span_seconds = blocks[boundary - 1].end_seconds - blocks[start_block].start_seconds
        if span_seconds < effective_minimum and boundary < len(blocks):
            continue
        spans.append((start_block, boundary))
        start_block = boundary

    if not spans:
        spans = [(0, len(blocks))]
    elif spans[-1][1] < len(blocks):
        spans[-1] = (spans[-1][0], len(blocks))

    # A stub tail (the professor trailing off) belongs to the section before it.
    if len(spans) > 1:
        tail_start, tail_stop = spans[-1]
        tail_seconds = blocks[tail_stop - 1].end_seconds - blocks[tail_start].start_seconds
        if tail_seconds < effective_minimum * 0.5:
            spans[-2] = (spans[-2][0], tail_stop)
            spans.pop()

    boosted: list[set[str]] = []
    for start, stop in spans:
        window_start = blocks[start].start_seconds
        window_end = blocks[stop - 1].end_seconds
        terms: set[str] = set()
        for item in evidence.items:
            if item.kind not in {EvidenceKind.MARKER, EvidenceKind.QUESTION}:
                continue
            if window_start <= item.start_seconds <= window_end:
                terms.update(_structure_tokens(item.text))
        boosted.append(terms)

    labelled = _label_sections(spans, blocks, boosted)

    sections: list[LectureSection] = []
    for ordinal, ((start, stop), (label, keywords)) in enumerate(zip(spans, labelled)):
        window_start = blocks[start].start_seconds
        window_end = blocks[stop - 1].end_seconds
        markers = [
            item.evidence_id
            for item in evidence.markers
            if window_start <= item.start_seconds <= window_end
        ]
        questions = [
            item.evidence_id
            for item in evidence.questions
            if window_start <= item.start_seconds <= window_end
        ]
        # More distinct keywords and more human signal means a more trustworthy
        # section boundary. Kept in [0, 1] so consumers can threshold on it.
        confidence = min(
            1.0,
            0.25 * len(keywords) / 4.0
            + 0.35 * min(1.0, (stop - start) / 4.0)
            + 0.40 * min(1.0, (len(markers) + len(questions)) / 2.0),
        )
        sections.append(
            LectureSection(
                section_id=evidence_id(
                    EvidenceKind.TOPIC, ordinal, window_start, label
                ).replace("to_", "sec_", 1),
                ordinal=ordinal,
                start_seconds=window_start,
                end_seconds=window_end,
                label=label,
                keywords=keywords,
                provenance=Provenance.NOVA_DERIVED,
                transcript_count=sum(block.item_count for block in blocks[start:stop]),
                marker_ids=markers,
                question_ids=questions,
                confidence=round(confidence, 4),
            )
        )
    return sections


def _sections_from_captured_topics(
    evidence: SessionEvidence,
    captured: list[EvidenceItem],
) -> list[LectureSection]:
    """Trust the recorder when it actually recorded topic changes."""
    duration = evidence.duration_seconds
    sections: list[LectureSection] = []
    for ordinal, item in enumerate(captured):
        end = captured[ordinal + 1].start_seconds if ordinal + 1 < len(captured) else duration
        end = max(end, item.start_seconds)
        markers = [
            marker.evidence_id
            for marker in evidence.markers
            if item.start_seconds <= marker.start_seconds <= end
        ]
        questions = [
            question.evidence_id
            for question in evidence.questions
            if item.start_seconds <= question.start_seconds <= end
        ]
        sections.append(
            LectureSection(
                section_id=item.evidence_id.replace("to_", "sec_", 1),
                ordinal=ordinal,
                start_seconds=item.start_seconds,
                end_seconds=end,
                label=item.text,
                keywords=_structure_tokens(item.text)[:4],
                provenance=Provenance.CAPTURED_AUDIO,
                transcript_count=sum(
                    1
                    for line in evidence.transcript
                    if item.start_seconds <= line.start_seconds <= end
                ),
                marker_ids=markers,
                question_ids=questions,
                confidence=1.0,
            )
        )
    return sections


def lecture_structure_markdown(evidence: SessionEvidence) -> str:
    """Compact, prompt-friendly rendering of the lecture's progression."""
    sections = evidence.lecture_structure()
    if not sections:
        return ""

    derived = all(section.is_derived for section in sections)
    lines = ["## Lecture progression"]
    if derived:
        lines.append(
            "> Reconstructed by NOVA from lexical shifts in the transcript. These are "
            "NOT the professor's own section headings — follow this ordering, but do "
            "not quote these labels as if the professor said them."
        )
    else:
        lines.append("> Recorded during the lecture.")
    lines.append("")
    for section in sections:
        span = f"{format_elapsed(section.start_seconds)}–{format_elapsed(section.end_seconds)}"
        signal = []
        if section.marker_ids:
            signal.append(f"{len(section.marker_ids)} marked")
        if section.question_ids:
            signal.append(f"{len(section.question_ids)} question(s)")
        suffix = f" [{', '.join(signal)}]" if signal else ""
        lines.append(f"{section.ordinal + 1}. [{span}] {section.label}{suffix}")
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Budgeted lecture timeline
# ---------------------------------------------------------------------------


def _anchor_times(evidence: SessionEvidence) -> list[float]:
    return [
        item.start_seconds
        for item in evidence.items
        if item.kind in {EvidenceKind.MARKER, EvidenceKind.QUESTION, EvidenceKind.TOPIC}
    ]


def _salience(item: EvidenceItem, anchors: Iterable[float]) -> float:
    """Rank a transcript segment's study value. Deterministic, no model calls."""
    score = 0.0
    if (item.speaker_role or "") == "professor":
        score += 2.0
    if item.attributes.get("is_question"):
        score += 1.0

    for anchor in anchors:
        distance = abs(item.start_seconds - anchor)
        if distance <= 20.0:
            score += 3.0
            break
        if distance <= 45.0:
            score += 1.5
            break

    # Substantive utterances beat "okay", "right", "so".
    words = len(item.text.split())
    if words >= 25:
        score += 1.5
    elif words >= 12:
        score += 0.75
    elif words <= 3:
        score -= 1.0

    return score


def select_timeline_items(
    evidence: SessionEvidence,
    *,
    max_chars: int = 40_000,
    bucket_seconds: float = 300.0,
) -> list[EvidenceItem]:
    """Choose what fits in the budget without ever dropping the lecture's tail.

    Non-transcript evidence (topics, markers, questions, answers) is always
    kept — it is low-volume and high-value. The remaining budget is spent on
    transcript segments in two passes: first a uniform pass that guarantees every
    ``bucket_seconds`` window of the lecture keeps its best segments, then a
    global pass by salience. This is what replaces head-truncation, which
    silently discarded everything after the first ~15 minutes.
    """
    budget = max(2_000, int(max_chars))

    def cost(item: EvidenceItem) -> int:
        # Roughly the rendered line length; exact width is not important, the
        # point is that the budget tracks real output size.
        return len(item.text) + 32

    always_keep = [
        item for item in evidence.items if item.kind is not EvidenceKind.TRANSCRIPT
    ]
    selected: dict[str, EvidenceItem] = {item.evidence_id: item for item in always_keep}
    used = sum(cost(item) for item in always_keep)

    transcript = evidence.transcript
    if not transcript:
        return sorted(selected.values(), key=lambda item: (item.start_seconds, item.evidence_id))

    anchors = _anchor_times(evidence)
    ranked = sorted(
        transcript,
        key=lambda item: (-_salience(item, anchors), item.start_seconds, item.evidence_id),
    )

    # Pass 1 — uniform coverage. Reserve most of the budget so that late-lecture
    # material (exam hints, assignments) is never starved by a dense opening.
    buckets: dict[int, list[EvidenceItem]] = {}
    for item in ranked:
        index = int(item.start_seconds // max(30.0, float(bucket_seconds)))
        buckets.setdefault(index, []).append(item)

    coverage_budget = int(budget * 0.6)
    for index in sorted(buckets):
        spent_here = 0
        per_bucket = max(1, coverage_budget // max(1, len(buckets)))
        for item in buckets[index]:
            if item.evidence_id in selected:
                continue
            item_cost = cost(item)
            if used + item_cost > budget or spent_here + item_cost > per_bucket:
                continue
            selected[item.evidence_id] = item
            used += item_cost
            spent_here += item_cost

    # Pass 2 — spend whatever is left on the most study-relevant remaining lines.
    for item in ranked:
        if item.evidence_id in selected:
            continue
        item_cost = cost(item)
        if used + item_cost > budget:
            continue
        selected[item.evidence_id] = item
        used += item_cost

    return sorted(
        selected.values(), key=lambda item: (item.start_seconds, item.evidence_id)
    )


def _render_item(item: EvidenceItem) -> str:
    stamp = format_elapsed(item.start_seconds)
    if item.kind is EvidenceKind.TOPIC:
        return f"\n### [{stamp}] TOPIC: {item.text}"
    if item.kind is EvidenceKind.MARKER:
        marker_kind = str(item.attributes.get("marker_kind") or "bookmark")
        readable = marker_kind.replace("_", " ").upper()
        return f"[{stamp}] >>> MARKED BY AHMED ({readable}): {item.text}"
    if item.kind is EvidenceKind.QUESTION:
        who = item.speaker_label or "Unknown speaker"
        return f"[{stamp}] QUESTION ({who}): {item.text}"
    if item.kind is EvidenceKind.ANSWER:
        return f"[{stamp}] NOVA LIVE ANSWER (not a professor statement): {item.text}"
    if item.kind is EvidenceKind.ATTACHMENT:
        return f"[--:--] ATTACHED MATERIAL: {item.text}"
    who = item.speaker_label or "Unknown speaker"
    return f"[{stamp}] {who}: {item.text}"


def lecture_timeline_markdown(
    evidence: SessionEvidence,
    *,
    max_chars: int = 40_000,
) -> str:
    """Render the whole lecture in order, within budget, tail included."""
    items = select_timeline_items(evidence, max_chars=max_chars)
    if not items:
        return "(no lecture evidence was captured for this session)"

    kept_transcript = sum(1 for item in items if item.kind is EvidenceKind.TRANSCRIPT)
    total_transcript = len(evidence.transcript)
    lines = [
        f"LECTURE TIMELINE — {evidence.course} — {evidence.title}",
        f"Duration captured: {format_elapsed(evidence.duration_seconds)}",
    ]
    if total_transcript:
        lines.append(
            f"Transcript coverage: {kept_transcript}/{total_transcript} segments "
            "selected across the full lecture (chronological, not truncated)."
        )
    lines.append("")
    lines.extend(_render_item(item) for item in items)
    return "\n".join(lines).strip() + "\n"


def evidence_digest_markdown(evidence: SessionEvidence) -> str:
    """Deterministic digest of the high-signal, low-volume evidence.

    Markers, topic progression and logged Q&A are cheap to render in full and
    are exactly the evidence that used to be dropped entirely.
    """
    sections: list[str] = []

    progression = lecture_structure_markdown(evidence)
    if progression:
        sections.append(progression)

    topics = evidence.topics
    if topics:
        sections.append("## Topic progression (in lecture order)")
        sections.extend(
            f"- [{format_elapsed(item.start_seconds)}] {item.text}"
            + (f" — {item.attributes.get('subtopic')}" if item.attributes.get("subtopic") else "")
            for item in topics
        )
        sections.append("")

    markers = evidence.markers
    if markers:
        sections.append("## Moments Ahmed marked during the lecture")
        sections.extend(
            f"- [{format_elapsed(item.start_seconds)}] "
            f"({str(item.attributes.get('marker_kind') or 'bookmark').replace('_', ' ')}) {item.text}"
            for item in markers
        )
        sections.append("")

    questions = evidence.questions
    if questions:
        answers = {
            str(item.attributes.get("answers_question") or ""): item.text
            for item in evidence.by_kind(EvidenceKind.ANSWER)
        }
        sections.append("## Questions asked in class")
        for item in questions:
            sections.append(
                f"- [{format_elapsed(item.start_seconds)}] "
                f"{item.speaker_label or 'Unknown speaker'}: {item.text}"
            )
            answer = answers.get(item.text)
            if answer:
                sections.append(f"  - NOVA answered live (not a professor statement): {answer}")
        sections.append("")

    attachments = evidence.by_kind(EvidenceKind.ATTACHMENT)
    if attachments:
        sections.append("## Materials attached to this session")
        sections.extend(f"- {item.text}" for item in attachments)
        sections.append("")

    if not sections:
        return "(no markers, topics, questions, or attachments were recorded)"
    return "\n".join(sections).rstrip() + "\n"


def iter_evidence(evidence: SessionEvidence, *kinds: EvidenceKind) -> Iterator[EvidenceItem]:
    """Small helper so consumers do not re-implement filtering."""
    wanted = set(kinds) or set(EvidenceKind)
    for item in evidence.items:
        if item.kind in wanted:
            yield item
