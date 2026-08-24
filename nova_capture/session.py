from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

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
        notes_enabled: bool = True,
        capture_version: str = "1.3",
    ) -> None:
        self.course = course.strip() or "Unsorted"
        self.title = title.strip() or "Class Session"
        self.storage = storage or ClassCaptureStorage()
        self.keep_audio = bool(keep_audio)
        self.notes_enabled = bool(notes_enabled)
        self.capture_version = str(capture_version)
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

    def expected_path(self) -> Path:
        return self.storage.session_dir(self.course, self.session_id)

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
            notes_enabled=self.notes_enabled,
            capture_version=self.capture_version,
        )
        self._write_metadata()

        self.transcript = TranscriptJournal(self.path / "transcript.jsonl")
        self.markers = MarkerJournal(self.path / "markers.jsonl")
        self.questions = QuestionJournal(self.path / "questions.jsonl")
        self.topics = TopicTracker(self.path / "topics.jsonl")
        (self.path / "attachments.jsonl").touch(exist_ok=True)
        self.storage.write_json(
            self.path / "speaker_roles.json",
            {"version": 1, "teacher_speaker_id": None, "speakers": {}},
        )
        self.state = ClassCaptureState.ACTIVE
        return self.path

    def _write_metadata(self) -> None:
        if self.path is None or self.metadata is None:
            return
        self.storage.write_json(
            self.path / "session.json",
            self.metadata.as_dict(),
        )

    def update_metadata(self, **changes: Any) -> None:
        if self.metadata is None:
            raise RuntimeError("Class Capture session has not started.")
        for name, value in changes.items():
            if not hasattr(self.metadata, name):
                raise AttributeError(f"Unknown class-session metadata field: {name}")
            setattr(self.metadata, name, value)
        self._write_metadata()

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

    def stop(self, status: str = "completed") -> Path:
        if self.state is not ClassCaptureState.ACTIVE:
            raise RuntimeError("Class Capture is not active.")
        assert self.path is not None
        assert self.metadata is not None

        self.metadata.stopped_at = datetime.now(timezone.utc)
        self.metadata.status = status.strip() or "completed"
        self._write_metadata()
        self.state = ClassCaptureState.STOPPED
        return self.path
