from __future__ import annotations

from pathlib import Path

from .models import QuestionRecord
from .storage import ClassCaptureStorage


class QuestionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: list[QuestionRecord] = []

    def add(self, question: QuestionRecord) -> None:
        self._items.append(question)
        ClassCaptureStorage.append_jsonl(self.path, question.as_dict())

    def items(self) -> tuple[QuestionRecord, ...]:
        return tuple(self._items)
