from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpeakerRole(StrEnum):
    PROFESSOR = "professor"
    STUDENT = "student"
    # A guest lecturer can out-talk the professor for a whole class, so talk
    # time alone must never promote them; they get their own role instead.
    GUEST = "guest"
    USER = "user"
    UNKNOWN = "unknown"


class MarkerKind(StrEnum):
    IMPORTANT = "important"
    EXAM_LIKELY = "exam_likely"
    PROFESSOR_EMPHASIS = "professor_emphasis"
    STUDENT_QUESTION = "student_question"
    DEFINITION = "definition"
    EXAMPLE = "example"
    FORMULA = "formula"
    ASSIGNMENT = "assignment"
    DUE_DATE = "due_date"
    REVIEW_LATER = "review_later"
    BOOKMARK = "bookmark"


@dataclass(slots=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    speaker: SpeakerRole = SpeakerRole.UNKNOWN
    speaker_confidence: float = 0.0
    topic: str | None = None
    is_question: bool = False
    speaker_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["speaker"] = self.speaker.value
        return value


@dataclass(slots=True)
class MarkerRecord:
    timestamp_seconds: float
    kind: MarkerKind
    label: str
    topic: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value


@dataclass(slots=True)
class QuestionRecord:
    timestamp_seconds: float
    question: str
    answer: str | None = None
    speaker: SpeakerRole = SpeakerRole.UNKNOWN
    topic: str | None = None
    study_value: str = "unknown"
    speaker_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["speaker"] = self.speaker.value
        return value


@dataclass(slots=True)
class TopicSegment:
    start_seconds: float
    topic: str
    subtopic: str | None = None
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ClassSessionMetadata:
    session_id: str
    course: str
    title: str
    started_at: datetime = field(default_factory=utc_now)
    stopped_at: datetime | None = None
    keep_audio: bool = True
    transcript_enabled: bool = True
    notes_enabled: bool = False
    capture_version: str = "1.3"
    status: str = "recording"
    audio_enabled: bool = False
    audio_error: str | None = None
    transcript_segment_count: int = 0
    question_count: int = 0
    speaker_ids: list[str] = field(default_factory=list)
    speaker_roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_answers_enabled: bool = True
    postprocess_enabled: bool = True
    postprocess_pid: int | None = None
    # --- V1.3.7 durable-capture evidence ---------------------------------
    # update_metadata() rejects unknown field names on purpose, so every
    # keyword class_capture.finalize() passes must exist here. It did not on
    # 2026-08-28: finalize() raised AttributeError on `stt_restarts` and the
    # whole session.json was left saying status="recording" with zero counts.
    stt_restarts: int = 0
    audio_chunks: int = 0
    audio_seconds: float = 0.0
    audio_integrity_ok: bool = False
    pipeline: str = "livekit"
    recorder_mode: str = "none"
    recorder_isolated: bool = False
    #: Every field above this line from `transcript_segment_count` down is a
    #: FINALIZATION OUTPUT: it only holds a real measurement once finalize()
    #: has run. Until then they are dataclass defaults, and a reader cannot
    #: tell "measured as zero" from "never measured" -- which is how a live
    #: COT3400 session reported `audio_integrity_ok: false` and
    #: `recorder_mode: "none"` while health.json showed 84 chunks from a
    #: healthy isolated recorder. Read them through
    #: `nova_capture.status.session_metrics()`, never raw.
    metrics_finalized: bool = False

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        value["stopped_at"] = self.stopped_at.isoformat() if self.stopped_at else None
        return value
