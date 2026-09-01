"""Who is talking, how sure NOVA is, and when it is allowed to say so.

Two different questions get two different answers here, deliberately.

**The authoritative role** (``resolve``) is what the transcript, the questions
journal, and the generated notes are labelled with. It stays conservative:
raw diarized ids during capture, and a Professor/Student decision only at
finalization, only on strong multi-speaker evidence. That rule exists because a
real 2026-08-23 lecture locked the first voice it heard as "Teacher" and never
reconsidered. A wrong label in a study document is worse than a generic one.

**The live assessment** (``live_assessment``) is what the status display and
health file show *during* class: a rolling, evidence-weighted estimate whose
confidence grows as the lecture provides evidence, e.g.

    00:20  Speaker 0 -> Unknown             0.35
    00:45  Speaker 0 -> Probable Professor  0.63
    02:00  Speaker 0 -> Professor           0.91

It is explicitly an estimate, it is never written into the transcript, and it
can say "Unknown" for as long as the evidence is weak.

Talk time alone never earns "Professor". A guest lecturer can dominate an hour
of a class; what separates a professor is early presence plus the language of
running a course. Both are required before confidence is allowed above the
probable band.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .models import SpeakerRole


#: Phrases that indicate someone is *running* a class rather than presenting in
#: one: course administration, assessment, materials, and turn-taking control.
_INSTRUCTIONAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bany questions\b",
        r"\bdoes (?:that|this) make sense\b",
        r"\blet'?s (?:look at|start|move on|go over|talk about)\b",
        r"\bnow (?:we|i)(?:'|\s+a|\s+wi)?\w*\s+(?:look|going|move|turn)\b",
        r"\b(?:on|look at) the (?:slide|board|screen)\b",
        r"\bnext slide\b",
        r"\bin (?:the|your) (?:textbook|book|syllabus|notes)\b",
        r"\byour (?:homework|assignment|project|quiz|exam|midterm|final)\b",
        r"\b(?:homework|assignment|project|quiz|exam|midterm) (?:is|will be|due)\b",
        r"\bis due\b",
        r"\bfor (?:the|your) exam\b",
        r"\bwill be on the (?:exam|test|quiz)\b",
        r"\brecall (?:that|from)\b",
        r"\bas (?:we|you) (?:saw|discussed|covered)\b",
        r"\blast (?:class|lecture|week) we\b",
        r"\bopen your\b",
        r"\btake (?:out|a look at)\b",
        r"\bwrite (?:this|that) down\b",
        r"\bthis is important\b",
        r"\bpay attention\b",
        r"\bwho can tell me\b",
        r"\bgood question\b",
        r"\bcome to office hours\b",
        r"\bin (?:this|today'?s) (?:class|lecture)\b",
    )
)

#: Phrases a guest presenter uses that a course owner rarely needs.
_GUEST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bthank you for having me\b",
        r"\bthanks for having me\b",
        r"\bglad to be here\b",
        r"\bmy (?:company|team|startup|lab|firm)\b",
        r"\bi work (?:at|for|with)\b",
        r"\bwhen i was (?:a student|in school)\b",
        r"\bat my (?:job|company|work)\b",
    )
)


def instructional_hits(text: str) -> int:
    return sum(1 for pattern in _INSTRUCTIONAL_PATTERNS if pattern.search(text or ""))


def guest_hits(text: str) -> int:
    return sum(1 for pattern in _GUEST_PATTERNS if pattern.search(text or ""))


@dataclass(slots=True)
class SpeakerEvidence:
    speaker_id: str
    words: int = 0
    turns: int = 0
    estimated_speech_seconds: float = 0.0
    first_seen_seconds: float = 0.0
    last_seen_seconds: float = 0.0
    instructional_signals: int = 0
    guest_signals: int = 0
    questions_to_class: int = 0
    longest_turn_words: int = 0
    followed_by: dict[str, int] = field(default_factory=dict)

    @property
    def average_turn_words(self) -> float:
        return self.words / max(1, self.turns)

    @property
    def distinct_responders(self) -> int:
        return len(self.followed_by)

    def as_dict(self) -> dict:
        value = asdict(self)
        value["average_turn_words"] = round(self.average_turn_words, 2)
        value["distinct_responders"] = self.distinct_responders
        return value


@dataclass(slots=True)
class SpeakerResolution:
    role: SpeakerRole
    label: str
    confidence: float


@dataclass(slots=True)
class SpeakerAssessment:
    """A live, explicitly provisional read on one speaker."""

    speaker_id: str
    role: SpeakerRole
    label: str
    confidence: float
    stage: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "role": self.role.value,
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "stage": self.stage,
            "reasons": list(self.reasons),
        }


class SpeakerRoleTracker:
    """Conservatively map raw diarized speaker IDs to classroom roles.

    Raw Deepgram speaker IDs stay authoritative during capture. Automatic
    Teacher/Student labels are intentionally delayed until finalization so a
    single early speaker can never become a permanently locked "Teacher" before
    other voices have appeared. A manual teacher speaker ID always wins and is
    available immediately.

    ``live_assessment``/``live_snapshot`` expose the separate rolling estimate
    described in the module docstring; they never change what ``resolve``
    returns.
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
        guest_arrival_seconds: float = 300.0,
        guest_minimum_words: int = 150,
        guest_minimum_turn_words: float = 35.0,
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
        self.guest_arrival_seconds = max(60.0, float(guest_arrival_seconds))
        self.guest_minimum_words = max(60, int(guest_minimum_words))
        self.guest_minimum_turn_words = max(10.0, float(guest_minimum_turn_words))

        self.manual_teacher = (
            str(teacher_speaker_id).strip()
            if teacher_speaker_id is not None
            else None
        ) or None
        self._evidence: dict[str, SpeakerEvidence] = {}
        self._teacher_id: str | None = self.manual_teacher
        self._teacher_confidence: float = 1.0 if self.manual_teacher else 0.0
        self._student_order: list[str] = []
        self._guests: set[str] = set()
        self._auto_finalized = bool(self.manual_teacher)
        self._inference_reason = (
            "manual_teacher_override" if self.manual_teacher else "not_finalized"
        )
        self._last_speaker: str | None = None
        self._live_stage: dict[str, str] = {}

    @staticmethod
    def _estimated_speech_seconds(text: str) -> float:
        # Approx. 132 wpm. Word-count evidence avoids treating silence between
        # STT chunks as speaking time.
        words = max(0, len((text or "").split()))
        return words / 2.2

    @staticmethod
    def _is_question_to_class(text: str) -> bool:
        value = (text or "").strip()
        if not value.endswith("?"):
            return False
        return bool(
            re.search(
                r"\b(?:any(?:one|body)?|you all|everyone|class|who can|does anyone)\b",
                value,
                re.IGNORECASE,
            )
        )

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
        item.longest_turn_words = max(item.longest_turn_words, words)
        item.instructional_signals += instructional_hits(text)
        item.guest_signals += guest_hits(text)
        if self._is_question_to_class(text):
            item.questions_to_class += 1

        # Interaction shape: who answers this speaker. A professor is answered
        # by many different students; a student usually is not.
        if self._last_speaker is not None and self._last_speaker != key:
            previous = self._evidence.get(self._last_speaker)
            if previous is not None:
                previous.followed_by[key] = previous.followed_by.get(key, 0) + 1
        self._last_speaker = key

        # Do not auto-lock a role during capture. Live labels stay raw/generic
        # unless the user explicitly supplied NOVA_CLASS_TEACHER_SPEAKER_ID.
        return self.resolve(key)

    # --- live (provisional) inference ------------------------------------

    def _total_words(self) -> int:
        return sum(item.words for item in self._evidence.values())

    def _signals(self, item: SpeakerEvidence) -> tuple[dict[str, float], list[str]]:
        """The raw evidence signals for one speaker, plus human reasons."""
        total = max(1, self._total_words())
        reasons: list[str] = []

        share = item.words / total
        share_score = min(1.0, share / 0.65)
        if share >= 0.5:
            reasons.append(f"holds {share:.0%} of spoken words")

        monologue_score = min(1.0, item.average_turn_words / 45.0)
        if item.average_turn_words >= 45:
            reasons.append(
                f"sustained turns (~{item.average_turn_words:.0f} words each)"
            )

        per_hundred = item.instructional_signals / max(1.0, item.words / 100.0)
        instructional_score = min(1.0, per_hundred / 1.5)
        if item.instructional_signals:
            reasons.append(f"{item.instructional_signals} course-running phrase(s)")

        early = item.first_seen_seconds <= self.teacher_start_window_seconds
        if early:
            reasons.append("present from the start of class")

        others = max(1, len(self._evidence) - 1)
        interaction_score = min(1.0, item.distinct_responders / others)
        if item.distinct_responders >= 2:
            reasons.append(f"answered by {item.distinct_responders} other speakers")

        if item.questions_to_class:
            reasons.append(f"{item.questions_to_class} question(s) to the class")

        return (
            {
                "share": share_score,
                "monologue": monologue_score,
                "instructional": instructional_score,
                "early": 1.0 if early else 0.0,
                "interaction": interaction_score,
            },
            reasons,
        )

    def _professor_score(self, item: SpeakerEvidence) -> tuple[float, list[str]]:
        signals, reasons = self._signals(item)
        score = (
            0.30 * signals["share"]
            + 0.20 * signals["monologue"]
            + 0.20 * signals["instructional"]
            + 0.15 * signals["early"]
            + 0.15 * signals["interaction"]
        )

        # Talk time alone is never enough. Without the language of running a
        # course, confidence is capped in the "probable" band forever.
        if item.instructional_signals == 0:
            score = min(score, 0.70)
            reasons.append("no course-running language yet")

        return score, reasons

    def _presenter_score(self, item: SpeakerEvidence) -> tuple[float, list[str]]:
        """How strongly this speaker is *presenting to the room*.

        A guest lecturer is judged on this alone. Penalising them for arriving
        late, or for not talking about homework deadlines, would keep an
        obvious guest presenter stuck at "Unknown" for a whole hour -- which is
        exactly what the professor-shaped score did before this split.
        """
        signals, reasons = self._signals(item)
        score = (
            0.45 * signals["share"]
            + 0.35 * signals["monologue"]
            + 0.20 * signals["interaction"]
        )
        return score, reasons

    def _looks_like_guest(self, item: SpeakerEvidence) -> bool:
        """The single definition of guest shape.

        Late arrival is required either way: someone who was in the room from
        the first minute is running the class, whatever they say about their
        job. After that, either explicit guest language or a substantial
        presenting block is enough.
        """
        if item.first_seen_seconds <= self.guest_arrival_seconds:
            return False
        if item.guest_signals >= 2:
            return True
        return (
            item.words >= self.guest_minimum_words
            and item.average_turn_words >= self.guest_minimum_turn_words
        )

    def live_assessment(self, speaker_id: str | int | None) -> SpeakerAssessment:
        """The rolling, explicitly provisional estimate for one speaker."""
        if speaker_id is None:
            return SpeakerAssessment(
                speaker_id="unknown",
                role=SpeakerRole.UNKNOWN,
                label="Unknown",
                confidence=0.0,
                stage="no_speaker_id",
            )

        key = str(speaker_id)
        if self.manual_teacher is not None and key == self.manual_teacher:
            return SpeakerAssessment(
                speaker_id=key,
                role=SpeakerRole.PROFESSOR,
                label="Professor",
                confidence=1.0,
                stage="manual_override",
                reasons=["manual teacher speaker id supplied"],
            )

        item = self._evidence.get(key)
        if item is None:
            return SpeakerAssessment(
                speaker_id=key,
                role=SpeakerRole.UNKNOWN,
                label=f"Speaker {key}",
                confidence=0.0,
                stage="no_evidence",
            )

        guest = self._looks_like_guest(item)
        if guest:
            score, reasons = self._presenter_score(item)
            reasons.append("arrived after the class was already under way")
        else:
            score, reasons = self._professor_score(item)

        # Bootstrap damping: with very little of the lecture heard, even a
        # perfect-looking speaker must stay low-confidence.
        evidence_factor = min(1.0, self._total_words() / float(self.minimum_total_words))
        speaker_count_factor = 0.75 if len(self._evidence) < 2 else 1.0
        confidence = round(score * evidence_factor * speaker_count_factor, 4)

        # Guest shape is decided before the professor bands. A guest lecturer
        # can look statistically identical to a professor -- long turns, most
        # of the talk time -- and the only thing separating them is that they
        # were not there when the class began.
        if guest:
            if confidence >= 0.75:
                role, label, stage = SpeakerRole.GUEST, "Guest Speaker", "confident"
            elif confidence >= 0.35:
                role = SpeakerRole.UNKNOWN
                label, stage = "Probable Guest Speaker", "probable"
            else:
                role, label, stage = SpeakerRole.UNKNOWN, "Unknown", "bootstrap"
        elif confidence >= 0.75:
            role, label, stage = SpeakerRole.PROFESSOR, "Professor", "confident"
        elif confidence >= 0.45:
            role, label, stage = SpeakerRole.UNKNOWN, "Probable Professor", "probable"
        elif item.words >= 25 and item.average_turn_words < 25:
            role, label, stage = SpeakerRole.UNKNOWN, "Probable Student", "probable"
        else:
            role, label, stage = SpeakerRole.UNKNOWN, "Unknown", "bootstrap"

        previous = self._live_stage.get(key)
        self._live_stage[key] = f"{label}:{stage}"
        if previous is not None and previous != self._live_stage[key]:
            reasons.append(f"changed from {previous.split(':')[0]}")

        return SpeakerAssessment(
            speaker_id=key,
            role=role,
            label=label,
            confidence=confidence,
            stage=stage,
            reasons=reasons,
        )

    def live_snapshot(self) -> dict[str, object]:
        """Persistable rolling state, safe to write mid-class."""
        assessments = {
            key: self.live_assessment(key).as_dict()
            for key in sorted(self._evidence)
        }
        return {
            "version": 1,
            "kind": "live_provisional",
            "note": (
                "Provisional in-session estimate. The authoritative roles are "
                "written to speaker_roles.json at finalization."
            ),
            "speaker_count": len(self._evidence),
            "total_words": self._total_words(),
            "assessments": assessments,
            "evidence": {
                key: item.as_dict() for key, item in sorted(self._evidence.items())
            },
        }

    # --- authoritative inference -----------------------------------------

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
            self._classify_guests()
            return self._teacher_id

        self._teacher_id = None
        self._teacher_confidence = 0.0
        self._auto_finalized = True
        self._guests.clear()

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

        # A guest presenter may out-talk the professor for a whole class.
        # Talk time alone must never buy the professor label, so late arrivals
        # are removed from consideration before the dominance test runs -- and
        # removed from the denominator too. A professor who hands an hour to a
        # guest still ran the class; measuring their share against the guest's
        # word count would hide that.
        candidates = [item for item in ranked if not self._looks_like_guest(item)]
        if not candidates:
            self._inference_reason = "only_late_arriving_speakers"
            return None

        top = candidates[0]
        candidate_words = sum(item.words for item in candidates)
        second = candidates[1] if len(candidates) > 1 else None

        share = top.words / max(1, candidate_words)
        ratio = top.words / max(1, second.words if second else 1)

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
        self._classify_guests()
        return self._teacher_id

    def _classify_guests(self) -> None:
        """Separate guest presenters from students among the non-teachers."""
        self._guests = {
            item.speaker_id
            for item in self._evidence.values()
            if item.speaker_id != self._teacher_id
            and self._looks_like_guest(item)
        }

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

        if key in self._guests:
            return SpeakerResolution(
                SpeakerRole.GUEST,
                "Guest Speaker",
                min(self._teacher_confidence, 0.80),
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

    def guest_speaker_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._guests))

    def role_map(self) -> dict[str, dict[str, object]]:
        output: dict[str, dict[str, object]] = {}
        for key in sorted(self._evidence, key=lambda value: (len(value), value)):
            resolution = self.resolve(key)
            live = self.live_assessment(key)
            output[key] = {
                "role": resolution.role.value,
                "label": resolution.label,
                "confidence": round(resolution.confidence, 4),
                "live_role": live.role.value,
                "live_label": live.label,
                "live_confidence": live.confidence,
                "evidence": self._evidence[key].as_dict(),
            }
        return output

    def snapshot(self) -> dict[str, object]:
        return {
            "version": 3,
            "teacher_speaker_id": self._teacher_id,
            "teacher_confidence": round(self._teacher_confidence, 4),
            "manual_teacher": self.manual_teacher,
            "guest_speaker_ids": list(self.guest_speaker_ids()),
            "roles_finalized": self._auto_finalized,
            "inference_reason": self._inference_reason,
            "speakers": self.role_map(),
        }
