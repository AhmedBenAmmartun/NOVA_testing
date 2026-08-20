from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

from .context import LectureContext
from .markers import MarkerJournal
from .models import ClassSessionMetadata, MarkerKind
from .questions import QuestionJournal
from .storage import ClassCaptureStorage
from .topics import TopicTracker
from .transcript import TranscriptJournal


class ClassCaptureState(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    STOPPED = "stopped"


class ClassCaptureSession:
    def __init__(
        self,
        course: str,
        title: str,
        *,
        storage: ClassCaptureStorage | None = None,
        keep_audio: bool = True,
    ) -> None:
        self.course = course.strip() or "Unsorted"
        self.title = title.strip() or "Class Session"
        self.storage = storage or ClassCaptureStorage()
        self.keep_audio = bool(keep_audio)
        self.state = ClassCaptureState.IDLE
        self.session_id = self._new_session_id()
        self.path: Path | None = None
        self.metadata: ClassSessionMetadata | None = None
        self.transcript: TranscriptJournal | None = None
        self.markers: MarkerJournal | None = None
        self.questions: QuestionJournal | None = None
        self.topics: TopicTracker | None = None
        self.context = LectureContext()

    @staticmethod
    def _new_session_id() -> str:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{stamp}_{uuid.uuid4().hex[:8]}"

    def start(self) -> Path:
        if self.state is not ClassCaptureState.IDLE:
            raise RuntimeError("Class Capture session has already started.")

        self.path = self.storage.create_session_dir(
            self.course,
            self.session_id,
        )
        self.metadata = ClassSessionMetadata(
            session_id=self.session_id,
            course=self.course,
            title=self.title,
            keep_audio=self.keep_audio,
        )
        self.storage.write_json(
            self.path / "session.json",
            self.metadata.as_dict(),
        )

        self.transcript = TranscriptJournal(self.path / "transcript.jsonl")
        self.markers = MarkerJournal(self.path / "markers.jsonl")
        self.questions = QuestionJournal(self.path / "questions.jsonl")
        self.topics = TopicTracker(self.path / "topics.jsonl")
        self.state = ClassCaptureState.ACTIVE
        return self.path

    def mark(
        self,
        timestamp_seconds: float,
        label: str,
        *,
        kind: MarkerKind = MarkerKind.BOOKMARK,
    ):
        if self.state is not ClassCaptureState.ACTIVE or self.markers is None:
            raise RuntimeError("Class Capture is not active.")
        topic = self.context.current_topic
        return self.markers.add(
            timestamp_seconds,
            kind,
            label,
            topic=topic,
        )

    def stop(self) -> Path:
        if self.state is not ClassCaptureState.ACTIVE:
            raise RuntimeError("Class Capture is not active.")
        assert self.path is not None
        assert self.metadata is not None

        self.metadata.stopped_at = datetime.now(timezone.utc)
        self.storage.write_json(
            self.path / "session.json",
            self.metadata.as_dict(),
        )
        self.state = ClassCaptureState.STOPPED
        return self.path
