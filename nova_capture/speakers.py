from __future__ import annotations

from dataclasses import asdict, dataclass

from .models import SpeakerRole


@dataclass(slots=True)
class SpeakerEvidence:
    speaker_id: str
    words: int = 0
    turns: int = 0
    estimated_speech_seconds: float = 0.0
    first_seen_seconds: float = 0.0
    last_seen_seconds: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class SpeakerResolution:
    role: SpeakerRole
    label: str
    confidence: float


class SpeakerRoleTracker:
    """Conservatively map raw diarized speaker IDs to classroom roles.

    Raw Deepgram speaker IDs are authoritative. Automatic Teacher/Student
    labels are intentionally delayed until finalization so a single early
    speaker can never become a permanently locked "Teacher" before other
    voices have even appeared. A manual teacher speaker ID always wins and is
    available immediately.
    """

    def __init__(
        self,
        *,
        observation_seconds: float | None = None,
        minimum_total_words: int = 180,
        dominance_ratio: float = 1.55,
        minimum_share: float = 0.58,
        minimum_teacher_words: int = 100,
        minimum_teacher_speech_seconds: float = 40.0,
        teacher_start_window_seconds: float = 90.0,
        teacher_speaker_id: str | None = None,
    ) -> None:
        # observation_seconds is accepted for backward API compatibility with
        # V1.3 callers/tests. V1.3.3 no longer uses elapsed time alone to lock
        # a teacher during capture.
        self.observation_seconds = (
            None if observation_seconds is None else max(0.0, float(observation_seconds))
        )
        self.minimum_total_words = max(40, int(minimum_total_words))
        self.dominance_ratio = max(1.10, float(dominance_ratio))
        self.minimum_share = min(0.90, max(0.40, float(minimum_share)))
        self.minimum_teacher_words = max(40, int(minimum_teacher_words))
        self.minimum_teacher_speech_seconds = max(
            15.0,
            float(minimum_teacher_speech_seconds),
        )
        self.teacher_start_window_seconds = max(
            30.0,
            float(teacher_start_window_seconds),
        )
        self.manual_teacher = (
            str(teacher_speaker_id).strip()
            if teacher_speaker_id is not None
            else None
        ) or None
        self._evidence: dict[str, SpeakerEvidence] = {}
        self._teacher_id: str | None = self.manual_teacher
        self._teacher_confidence: float = 1.0 if self.manual_teacher else 0.0
        self._student_order: list[str] = []
        self._auto_finalized = bool(self.manual_teacher)
        self._inference_reason = (
            "manual_teacher_override" if self.manual_teacher else "not_finalized"
        )

    @staticmethod
    def _estimated_speech_seconds(text: str) -> float:
        # Approx. 132 wpm. Word-count evidence avoids treating silence between
        # STT chunks as speaking time.
        words = max(0, len((text or "").split()))
        return words / 2.2

    def observe(
        self,
        speaker_id: str | int | None,
        text: str,
        *,
        elapsed_seconds: float,
    ) -> SpeakerResolution:
        if speaker_id is None:
            return SpeakerResolution(SpeakerRole.UNKNOWN, "Unknown", 0.0)

        key = str(speaker_id)
        words = len((text or "").split())
        item = self._evidence.get(key)
        if item is None:
            item = SpeakerEvidence(
                speaker_id=key,
                first_seen_seconds=max(0.0, float(elapsed_seconds)),
            )
            self._evidence[key] = item

        item.words += words
        item.turns += 1
        item.estimated_speech_seconds += self._estimated_speech_seconds(text)
        item.last_seen_seconds = max(0.0, float(elapsed_seconds))

        # Do not auto-lock a role during capture. Live labels stay raw/generic
        # unless the user explicitly supplied NOVA_CLASS_TEACHER_SPEAKER_ID.
        return self.resolve(key)

    def finalize_roles(self) -> str | None:
        """Infer a Teacher only when the completed session supports it strongly.

        This deliberately prefers UNKNOWN over a confident-but-wrong role.
        A valid automatic Teacher candidate must:
        - be one of at least two observed speakers;
        - have appeared near the beginning of the class;
        - dominate the completed transcript by both share and ratio;
        - have enough absolute speech to look lecture-shaped.
        """

        if self.manual_teacher is not None:
            self._teacher_id = self.manual_teacher
            self._teacher_confidence = 1.0
            self._auto_finalized = True
            self._inference_reason = "manual_teacher_override"
            return self._teacher_id

        self._teacher_id = None
        self._teacher_confidence = 0.0
        self._auto_finalized = True

        ranked = sorted(
            self._evidence.values(),
            key=lambda item: (item.words, item.turns),
            reverse=True,
        )

        if len(ranked) < 2:
            self._inference_reason = "insufficient_distinct_speakers"
            return None

        total_words = sum(item.words for item in ranked)
        if total_words < self.minimum_total_words:
            self._inference_reason = "insufficient_total_speech"
            return None

        top = ranked[0]
        second = ranked[1]
        share = top.words / max(1, total_words)
        ratio = top.words / max(1, second.words)

        if top.first_seen_seconds > self.teacher_start_window_seconds:
            self._inference_reason = "dominant_speaker_started_too_late"
            return None

        if top.words < self.minimum_teacher_words:
            self._inference_reason = "insufficient_teacher_words"
            return None

        if top.estimated_speech_seconds < self.minimum_teacher_speech_seconds:
            self._inference_reason = "insufficient_teacher_speech_time"
            return None

        if share < self.minimum_share or ratio < self.dominance_ratio:
            self._inference_reason = "no_stable_dominant_lecturer"
            return None

        self._teacher_id = top.speaker_id
        share_margin = min(
            1.0,
            max(0.0, (share - self.minimum_share) / max(0.01, 0.90 - self.minimum_share)),
        )
        ratio_margin = min(
            1.0,
            max(0.0, (ratio - self.dominance_ratio) / 1.5),
        )
        self._teacher_confidence = min(
            0.97,
            0.76 + 0.11 * share_margin + 0.10 * ratio_margin,
        )
        self._inference_reason = "stable_multi_speaker_dominance"
        return self._teacher_id

    def resolve(self, speaker_id: str | int | None) -> SpeakerResolution:
        if speaker_id is None:
            return SpeakerResolution(SpeakerRole.UNKNOWN, "Unknown", 0.0)

        key = str(speaker_id)

        if self._teacher_id is None:
            return SpeakerResolution(
                SpeakerRole.UNKNOWN,
                f"Speaker {key}",
                0.0,
            )

        if key == self._teacher_id:
            return SpeakerResolution(
                SpeakerRole.PROFESSOR,
                "Teacher",
                self._teacher_confidence,
            )

        if key not in self._student_order:
            self._student_order.append(key)
        index = self._student_order.index(key) + 1
        return SpeakerResolution(
            SpeakerRole.STUDENT,
            f"Student {index}",
            self._teacher_confidence,
        )

    def teacher_speaker_id(self) -> str | None:
        return self._teacher_id

    def role_map(self) -> dict[str, dict[str, object]]:
        output: dict[str, dict[str, object]] = {}
        for key in sorted(self._evidence, key=lambda value: (len(value), value)):
            resolution = self.resolve(key)
            output[key] = {
                "role": resolution.role.value,
                "label": resolution.label,
                "confidence": round(resolution.confidence, 4),
                "evidence": self._evidence[key].as_dict(),
            }
        return output

    def snapshot(self) -> dict[str, object]:
        return {
            "version": 2,
            "teacher_speaker_id": self._teacher_id,
            "teacher_confidence": round(self._teacher_confidence, 4),
            "manual_teacher": self.manual_teacher,
            "roles_finalized": self._auto_finalized,
            "inference_reason": self._inference_reason,
            "speakers": self.role_map(),
        }
