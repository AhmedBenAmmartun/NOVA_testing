from __future__ import annotations

from dataclasses import dataclass, field

from .models import QuestionRecord, TranscriptSegment


@dataclass(slots=True)
class LectureContext:
    current_topic: str | None = None
    current_subtopic: str | None = None
    professor_explaining: str | None = None
    prior_topic: str | None = None
    open_question: str | None = None
    important_terms: list[str] = field(default_factory=list)
    recent_transcript: list[TranscriptSegment] = field(default_factory=list)
    recent_questions: list[QuestionRecord] = field(default_factory=list)

    def set_topic(
        self,
        topic: str,
        *,
        subtopic: str | None = None,
    ) -> None:
        if self.current_topic and self.current_topic != topic:
            self.prior_topic = self.current_topic
        self.current_topic = topic
        self.current_subtopic = subtopic

    def add_transcript(
        self,
        segment: TranscriptSegment,
        *,
        max_items: int = 40,
    ) -> None:
        self.recent_transcript.append(segment)
        del self.recent_transcript[:-max(1, int(max_items))]

    def add_question(
        self,
        question: QuestionRecord,
        *,
        max_items: int = 20,
    ) -> None:
        self.recent_questions.append(question)
        del self.recent_questions[:-max(1, int(max_items))]
        self.open_question = question.question

    def snapshot(self) -> dict[str, object]:
        return {
            "current_topic": self.current_topic,
            "current_subtopic": self.current_subtopic,
            "professor_explaining": self.professor_explaining,
            "prior_topic": self.prior_topic,
            "open_question": self.open_question,
            "important_terms": list(self.important_terms),
            "recent_transcript_count": len(self.recent_transcript),
            "recent_question_count": len(self.recent_questions),
        }
