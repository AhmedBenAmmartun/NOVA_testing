from .context import LectureContext
from .evidence import (
    EvidenceItem,
    EvidenceKind,
    LectureSection,
    Provenance,
    SessionEvidence,
    derive_lecture_structure,
    evidence_digest_markdown,
    lecture_structure_markdown,
    lecture_timeline_markdown,
    load_session_evidence,
    write_session_evidence,
)
from .markers import MarkerJournal
from .microphone import LocalMicrophoneCapture
from .models import (
    ClassSessionMetadata,
    MarkerKind,
    MarkerRecord,
    QuestionRecord,
    SpeakerRole,
    TopicSegment,
    TranscriptSegment,
)
from .question_detection import (
    is_rhetorical_classroom_filler,
    looks_like_question,
    should_answer_question,
)
from .questions import (
    QuestionAssembler,
    QuestionDeduplicator,
    QuestionJournal,
    TurnQuestionBuffer,
)
from .recorder import LocalWaveRecorder
from .session import ClassCaptureSession, ClassCaptureState
from .speakers import SpeakerResolution, SpeakerRoleTracker
from .storage import ClassCaptureStorage
from .topics import TopicTracker
from .transcript import TranscriptJournal

__all__ = [
    "ClassCaptureSession",
    "ClassCaptureState",
    "ClassCaptureStorage",
    "ClassSessionMetadata",
    "EvidenceItem",
    "EvidenceKind",
    "LectureContext",
    "LectureSection",
    "LocalMicrophoneCapture",
    "LocalWaveRecorder",
    "MarkerJournal",
    "MarkerKind",
    "MarkerRecord",
    "QuestionAssembler",
    "QuestionDeduplicator",
    "QuestionJournal",
    "QuestionRecord",
    "Provenance",
    "SessionEvidence",
    "SpeakerResolution",
    "SpeakerRole",
    "SpeakerRoleTracker",
    "TopicSegment",
    "TurnQuestionBuffer",
    "TopicTracker",
    "TranscriptJournal",
    "TranscriptSegment",
    "derive_lecture_structure",
    "evidence_digest_markdown",
    "is_rhetorical_classroom_filler",
    "lecture_structure_markdown",
    "lecture_timeline_markdown",
    "load_session_evidence",
    "looks_like_question",
    "should_answer_question",
    "write_session_evidence",
]
