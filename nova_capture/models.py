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

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        value["stopped_at"] = self.stopped_at.isoformat() if self.stopped_at else None
        return value
