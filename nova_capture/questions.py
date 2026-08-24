from __future__ import annotations

import json
import re
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

from .models import QuestionRecord, SpeakerRole, TranscriptSegment
from .question_detection import looks_like_question
from .storage import ClassCaptureStorage


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class QuestionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._items: list[QuestionRecord] = []

    def add(self, question: QuestionRecord) -> QuestionRecord:
        self._items.append(question)
        ClassCaptureStorage.append_jsonl(self.path, question.as_dict())
        return question

    def _rewrite(self) -> None:
        temporary = self.path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for item in self._items:
                handle.write(json.dumps(item.as_dict(), ensure_ascii=False) + "\n")
        temporary.replace(self.path)

    def update_answer(self, question: QuestionRecord, answer: str | None) -> None:
        question.answer = answer.strip() if answer else None
        self._rewrite()

    def apply_speaker_roles(self, resolver) -> None:
        for item in self._items:
            item.speaker = resolver(item.speaker_id).role
        self._rewrite()

    def items(self) -> tuple[QuestionRecord, ...]:
        return tuple(self._items)


class QuestionAssembler:
    """Merge fragmented STT chunks and emit complete spoken questions.

    Detection does not rely only on a trailing question mark because streaming
    STT may punctuate a question as a statement. Raw speaker IDs are retained;
    semantic role inference is handled by a separate speaker tracker.
    """

    def __init__(
        self,
        *,
        max_window_seconds: float = 20.0,
        max_chars: int = 800,
    ) -> None:
        self.max_window_seconds = max(5.0, float(max_window_seconds))
        self.max_chars = max(100, int(max_chars))
        self._parts: list[str] = []
        self._start_seconds = 0.0
        self._last_seconds = 0.0
        self._speaker_id: str | None = None
        self._speaker = SpeakerRole.UNKNOWN
        self._speaker_confidence = 0.0
        self._topic: str | None = None

    def _reset(self) -> None:
        self._parts.clear()
        self._start_seconds = 0.0
        self._last_seconds = 0.0
        self._speaker_id = None
        self._speaker = SpeakerRole.UNKNOWN
        self._speaker_confidence = 0.0
        self._topic = None

    def _finish(self) -> QuestionRecord | None:
        text = " ".join(part.strip() for part in self._parts if part.strip()).strip()
        if not text:
            self._reset()
            return None

        record = None
        if looks_like_question(text):
            record = QuestionRecord(
                timestamp_seconds=self._start_seconds,
                question=text,
                speaker=self._speaker,
                speaker_id=self._speaker_id,
                topic=self._topic,
                study_value="unknown",
            )
        self._reset()
        return record

    def _append_piece(
        self,
        piece: str,
        segment: TranscriptSegment,
    ) -> list[QuestionRecord]:
        outputs: list[QuestionRecord] = []
        piece = piece.strip()
        if not piece:
            return outputs

        if self._parts and segment.speaker_id != self._speaker_id:
            prior = self._finish()
            if prior is not None:
                outputs.append(prior)

        # If STT omitted punctuation on a preceding statement and a new
        # question clearly begins, discard/finish the statement buffer first
        # rather than gluing it onto the question.
        if self._parts and looks_like_question(piece):
            buffered = " ".join(self._parts)
            if not looks_like_question(buffered):
                prior = self._finish()
                if prior is not None:
                    outputs.append(prior)

        if not self._parts:
            self._start_seconds = segment.start_seconds
            self._speaker_id = segment.speaker_id
            self._speaker = segment.speaker
            self._speaker_confidence = segment.speaker_confidence
            self._topic = segment.topic

        self._parts.append(piece)
        self._last_seconds = segment.end_seconds

        text = " ".join(self._parts)
        too_long = (
            len(text) >= self.max_chars
            or (self._last_seconds - self._start_seconds) >= self.max_window_seconds
        )
        terminal = piece.endswith((".", "!", "?"))

        if terminal or too_long:
            finished = self._finish()
            if finished is not None:
                outputs.append(finished)

        return outputs

    def feed(self, segment: TranscriptSegment) -> list[QuestionRecord]:
        outputs: list[QuestionRecord] = []
        pieces = _SENTENCE_SPLIT.split(segment.text.strip())
        for piece in pieces:
            outputs.extend(self._append_piece(piece, segment))
        return outputs

    def flush(self) -> QuestionRecord | None:
        return self._finish()


_TURN_CONTINUATION_RE = re.compile(
    r"\b(?P<wh>what|why|how|when|where|who|which)\s+"
    r"(?P<aux>am|is|are|was|were|do|does|did|can|could|should|would|will|have|has)\s+"
    r"(?P<subject>[a-z']+)\?\s+"
    r"(?P<continuation>[a-z']+ing\b)",
    re.IGNORECASE,
)

_DEDUPE_STOPWORDS = {
    "a", "an", "the", "what", "where", "when", "why", "how", "who", "which",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "should",
    "would", "will", "you", "your", "we", "our", "i", "my", "it", "this", "that",
    "from", "to", "of", "for", "and", "or", "like", "know", "please",
}
_DEDUPE_WORD_RE = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def _merge_turn_question_fragments(text: str) -> str:
    """Repair punctuation that prematurely split one spoken WH question.

    Streaming STT may finalize "Like, where are you?" before the speaker
    continues with "Getting the data from?". At a committed human-turn
    boundary these belong to one question, so remove only the internal
    question mark when the second fragment is a grammatical continuation.
    """

    cleaned = " ".join((text or "").split()).strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _TURN_CONTINUATION_RE.sub(
            lambda match: (
                f"{match.group('wh')} {match.group('aux')} "
                f"{match.group('subject')} {match.group('continuation').casefold()}"
            ),
            cleaned,
        )
    return cleaned


class TurnQuestionBuffer:
    """Buffer final STT chunks until NOVA receives a committed user-turn boundary.

    Raw transcript chunks remain authoritative and are saved immediately. This
    buffer is only for deciding when Class Intelligence should classify/answer.
    """

    def __init__(self, *, max_chars: int = 1600) -> None:
        self.max_chars = max(200, int(max_chars))
        self._segments: list[TranscriptSegment] = []

    def feed(self, segment: TranscriptSegment) -> None:
        self._segments.append(segment)
        # Bound memory defensively without altering the authoritative transcript.
        total = sum(len(item.text) for item in self._segments)
        while len(self._segments) > 1 and total > self.max_chars:
            removed = self._segments.pop(0)
            total -= len(removed.text)

    def clear(self) -> None:
        self._segments.clear()

    def flush(self) -> list[TranscriptSegment]:
        if not self._segments:
            return []

        source = self._segments
        self._segments = []

        groups: list[list[TranscriptSegment]] = []
        for segment in source:
            if not groups or groups[-1][-1].speaker_id == segment.speaker_id:
                if not groups:
                    groups.append([])
                groups[-1].append(segment)
            else:
                groups.append([segment])

        outputs: list[TranscriptSegment] = []
        for group in groups:
            if not group:
                continue
            text = _merge_turn_question_fragments(
                " ".join(item.text.strip() for item in group if item.text.strip())
            )
            if not text:
                continue
            first = group[0]
            last = group[-1]
            outputs.append(
                TranscriptSegment(
                    start_seconds=first.start_seconds,
                    end_seconds=last.end_seconds,
                    text=text,
                    speaker=first.speaker,
                    speaker_confidence=first.speaker_confidence,
                    topic=first.topic,
                    is_question=looks_like_question(text),
                    speaker_id=first.speaker_id,
                )
            )
        return outputs


class QuestionDeduplicator:
    """Suppress near-identical live questions repeated within a short window."""

    def __init__(self, *, window_seconds: float = 15.0, history_size: int = 24) -> None:
        self.window_seconds = max(3.0, float(window_seconds))
        self._history: deque[tuple[float, str, tuple[str, ...]]] = deque(
            maxlen=max(4, int(history_size))
        )

    @staticmethod
    def _normalized(text: str) -> str:
        return " ".join(_DEDUPE_WORD_RE.findall((text or "").casefold()))

    @staticmethod
    def _core_tokens(text: str) -> tuple[str, ...]:
        words = _DEDUPE_WORD_RE.findall((text or "").casefold())
        return tuple(word for word in words if word not in _DEDUPE_STOPWORDS)

    @staticmethod
    def _similar(
        normalized_a: str,
        core_a: tuple[str, ...],
        normalized_b: str,
        core_b: tuple[str, ...],
    ) -> bool:
        if normalized_a == normalized_b:
            return True

        if len(core_a) >= 2 and len(core_b) >= 2:
            set_a, set_b = set(core_a), set(core_b)
            intersection = len(set_a & set_b)
            union = len(set_a | set_b)
            if union and (intersection / union) >= 0.80:
                return True
            smaller = min(len(set_a), len(set_b))
            if smaller and intersection / smaller >= 0.90:
                return True

        return SequenceMatcher(None, normalized_a, normalized_b).ratio() >= 0.90

    def is_duplicate(self, text: str, *, timestamp_seconds: float) -> bool:
        normalized = self._normalized(text)
        core = self._core_tokens(text)
        if not normalized:
            return False

        cutoff = float(timestamp_seconds) - self.window_seconds
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        for _, prior_normalized, prior_core in self._history:
            if self._similar(normalized, core, prior_normalized, prior_core):
                return True

        self._history.append((float(timestamp_seconds), normalized, core))
        return False
