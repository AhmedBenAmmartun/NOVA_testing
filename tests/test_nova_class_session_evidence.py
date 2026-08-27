"""Behavioural tests for the Session Evidence Model V1.

These exercise real loading/selection/rendering against a temporary session
directory rather than grepping source text, so a refactor that preserves
behaviour keeps them green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nova_capture.evidence import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceKind,
    Provenance,
    SessionEvidence,
    derive_lecture_structure,
    evidence_digest_markdown,
    evidence_id,
    format_elapsed,
    lecture_structure_markdown,
    lecture_timeline_markdown,
    load_session_evidence,
    select_timeline_items,
    write_session_evidence,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


@pytest.fixture()
def session(tmp_path: Path) -> Path:
    root = tmp_path / "CEN4065" / "session1"
    root.mkdir(parents=True)

    (root / "session.json").write_text(
        json.dumps(
            {
                "session_id": "session1",
                "course": "CEN4065",
                "title": "Sorting and Complexity",
                "started_at": "2026-08-25T12:00:00+00:00",
                "status": "completed",
                "capture_version": "1.3.6",
            }
        ),
        encoding="utf-8",
    )
    (root / "speaker_roles.json").write_text(
        json.dumps(
            {
                "speakers": {
                    "0": {"label": "Professor Reed", "role": "professor", "confidence": 0.9},
                    "1": {"label": "Student", "role": "student", "confidence": 0.5},
                }
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        root / "transcript.jsonl",
        [
            {
                "start_seconds": 0.0,
                "end_seconds": 6.0,
                "text": "Today we review Big-O notation before we get to insertion sort.",
                "speaker": "professor",
                "speaker_id": "0",
            },
            {
                "start_seconds": 6.0,
                "end_seconds": 8.0,
                "text": "Okay.",
                "speaker": "student",
                "speaker_id": "1",
            },
            {
                "start_seconds": 1800.0,
                "end_seconds": 1812.0,
                "text": "The worst case for insertion sort is quadratic, and this will be on the exam.",
                "speaker": "professor",
                "speaker_id": "0",
            },
        ],
    )
    _write_jsonl(
        root / "questions.jsonl",
        [
            {
                "timestamp_seconds": 1805.0,
                "question": "Is the best case linear?",
                "answer": "Yes, insertion sort is linear when the input is already sorted.",
                "speaker": "student",
                "speaker_id": "1",
            }
        ],
    )
    _write_jsonl(
        root / "markers.jsonl",
        [
            {
                "timestamp_seconds": 1801.0,
                "kind": "exam_likely",
                "label": "Worst case complexity",
                "topic": "Insertion sort",
            }
        ],
    )
    _write_jsonl(
        root / "topics.jsonl",
        [
            {"start_seconds": 0.0, "topic": "Big-O review", "subtopic": None, "summary": ""},
            {"start_seconds": 1700.0, "topic": "Insertion sort", "subtopic": "Worst case", "summary": ""},
        ],
    )
    return root


def test_loads_every_raw_journal_into_one_ordered_model(session: Path) -> None:
    evidence = load_session_evidence(session)

    assert evidence.session_id == "session1"
    assert evidence.course == "CEN4065"
    assert evidence.title == "Sorting and Complexity"

    coverage = evidence.coverage()
    assert coverage["transcript"] == 3
    assert coverage["question"] == 1
    assert coverage["answer"] == 1
    assert coverage["marker"] == 1
    assert coverage["topic"] == 2

    times = [item.start_seconds for item in evidence.items]
    assert times == sorted(times), "evidence must be chronological"


def test_markers_and_topics_are_not_dropped(session: Path) -> None:
    """The v1.3.6 regression: markers/topics were captured then ignored."""
    evidence = load_session_evidence(session)

    marker = evidence.markers[0]
    assert marker.text == "Worst case complexity"
    assert marker.attributes["marker_kind"] == "exam_likely"
    assert marker.provenance is Provenance.USER_MARKED

    digest = evidence_digest_markdown(evidence)
    assert "Worst case complexity" in digest
    assert "Big-O review" in digest
    assert "Insertion sort" in digest


def test_nova_answers_are_labelled_as_nova_not_professor(session: Path) -> None:
    evidence = load_session_evidence(session)
    answer = evidence.by_kind(EvidenceKind.ANSWER)[0]

    assert answer.provenance is Provenance.NOVA_LIVE_ANSWER
    assert not answer.is_human_evidence

    timeline = lecture_timeline_markdown(evidence)
    assert "NOVA LIVE ANSWER (not a professor statement)" in timeline


def test_speaker_labels_resolve_from_speaker_roles(session: Path) -> None:
    evidence = load_session_evidence(session)
    professor_lines = [
        item for item in evidence.transcript if item.speaker_id == "0"
    ]
    assert professor_lines
    assert all(item.speaker_label == "Professor Reed" for item in professor_lines)


def test_evidence_ids_are_stable_across_reloads(session: Path) -> None:
    first = load_session_evidence(session)
    second = load_session_evidence(session)
    assert [item.evidence_id for item in first.items] == [
        item.evidence_id for item in second.items
    ]


def test_evidence_ids_survive_whitespace_reformatting() -> None:
    original = evidence_id(EvidenceKind.TRANSCRIPT, 0, 1.0, "Big-O  review")
    reformatted = evidence_id(EvidenceKind.TRANSCRIPT, 0, 1.0, "Big-O review")
    assert original == reformatted


def test_serialization_is_deterministic_and_carries_no_clock(session: Path) -> None:
    evidence = load_session_evidence(session)
    first = json.dumps(evidence.to_dict(), sort_keys=True)
    second = json.dumps(load_session_evidence(session).to_dict(), sort_keys=True)
    assert first == second
    assert "generated_at" not in evidence.to_dict()
    assert evidence.to_dict()["schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert evidence.to_dict()["layer"] == "working_intelligence"


def test_write_session_evidence_adds_timestamp_without_touching_raw(session: Path) -> None:
    before = {
        path.name: path.read_bytes()
        for path in session.iterdir()
        if path.is_file()
    }
    evidence = load_session_evidence(session)
    target = write_session_evidence(session, evidence, generated_at="2026-08-26T10:00:00+00:00")

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["generated_at"] == "2026-08-26T10:00:00+00:00"
    assert payload["session_id"] == "session1"

    for name, raw in before.items():
        assert session.joinpath(name).read_bytes() == raw, f"raw evidence mutated: {name}"


def test_source_provenance_records_hashes(session: Path) -> None:
    evidence = load_session_evidence(session)
    by_name = {source.name: source for source in evidence.sources}

    assert by_name["transcript.jsonl"].exists
    assert by_name["transcript.jsonl"].records == 3
    assert len(by_name["transcript.jsonl"].sha256) == 64
    assert not by_name["live_qa_events.jsonl"].exists


def test_malformed_journal_lines_are_reported_not_fatal(session: Path) -> None:
    with (session / "markers.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    evidence = load_session_evidence(session)
    assert evidence.markers, "valid markers must still load"
    assert any("markers.jsonl" in warning for warning in evidence.warnings)


def test_missing_session_directory_degrades_gracefully(tmp_path: Path) -> None:
    evidence = load_session_evidence(tmp_path / "does-not-exist")
    assert evidence.items == []
    assert evidence.coverage()["transcript"] == 0


class TestTimelineBudget:
    """The head-truncation fix: the end of a lecture must survive the budget."""

    @staticmethod
    def _long_session(root: Path, *, minutes: int = 90) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "session.json").write_text(
            json.dumps({"session_id": "long", "course": "CEN4065", "title": "Long Lecture"}),
            encoding="utf-8",
        )
        rows = []
        for index in range(minutes * 6):  # one segment every 10 seconds
            start = index * 10.0
            rows.append(
                {
                    "start_seconds": start,
                    "end_seconds": start + 10.0,
                    "text": f"Segment {index} discussing course material in detail " * 3,
                    "speaker": "professor",
                    "speaker_id": "0",
                }
            )
        _write_jsonl(root / "transcript.jsonl", rows)
        return root

    def test_final_minutes_are_represented(self, tmp_path: Path) -> None:
        session = self._long_session(tmp_path / "long")
        evidence = load_session_evidence(session)
        total_seconds = evidence.duration_seconds
        assert total_seconds > 5000, "fixture should be a long lecture"

        selected = select_timeline_items(evidence, max_chars=16_000)
        latest = max(item.start_seconds for item in selected)

        # Old behaviour truncated at 16k chars of transcript, which for this
        # fixture stopped well inside the first quarter of the lecture.
        assert latest > total_seconds * 0.9, (
            f"tail of the lecture was dropped: last kept segment at {latest}s "
            f"of {total_seconds}s"
        )

    def test_every_stretch_of_the_lecture_keeps_something(self, tmp_path: Path) -> None:
        session = self._long_session(tmp_path / "long2")
        evidence = load_session_evidence(session)
        selected = select_timeline_items(evidence, max_chars=20_000, bucket_seconds=300.0)

        buckets = {int(item.start_seconds // 300.0) for item in selected}
        expected = {int(item.start_seconds // 300.0) for item in evidence.transcript}
        missing = expected - buckets
        assert not missing, f"5-minute windows with no evidence at all: {sorted(missing)}"

    def test_budget_is_respected(self, tmp_path: Path) -> None:
        session = self._long_session(tmp_path / "long3")
        evidence = load_session_evidence(session)
        rendered = lecture_timeline_markdown(evidence, max_chars=12_000)
        # Header lines add a small fixed overhead on top of the item budget.
        assert len(rendered) < 12_000 * 1.5

    def test_high_value_evidence_is_never_budgeted_out(self, session: Path) -> None:
        evidence = load_session_evidence(session)
        selected = select_timeline_items(evidence, max_chars=2_000)
        kinds = {item.kind for item in selected}
        assert EvidenceKind.MARKER in kinds
        assert EvidenceKind.QUESTION in kinds
        assert EvidenceKind.TOPIC in kinds


def test_timeline_is_chronological_and_marks_ahmeds_moments(session: Path) -> None:
    evidence = load_session_evidence(session)
    timeline = lecture_timeline_markdown(evidence)

    assert "MARKED BY AHMED (EXAM LIKELY)" in timeline
    assert "not truncated" in timeline

    big_o = timeline.index("Big-O notation")
    insertion = timeline.index("worst case for insertion sort")
    assert big_o < insertion, "lecture progression must be preserved in order"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00"), (65, "01:05"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_format_elapsed(seconds: float, expected: str) -> None:
    assert format_elapsed(seconds) == expected


class TestLectureStructure:
    """Topic progression must exist even though the recorder never captures it.

    ``LectureContext.set_topic`` and ``TopicTracker.update`` have no production
    callers, so ``topics.jsonl`` is empty in every real session and every
    ``topic`` field is ``None``. The progression is therefore reconstructed from
    lexical cohesion in the professor's own words.
    """

    PHASES = [
        "We review asymptotic notation. Big-O describes an upper bound on growth "
        "rate. Constant factors drop out of asymptotic analysis entirely.",
        "Count the iterations of each loop. A nested loop over n elements executes "
        "n squared iterations. Counting iterations gives the running time.",
        "Insertion sort builds a sorted prefix. Each new key is inserted into the "
        "sorted prefix by shifting larger keys rightward.",
        "Take the array five two four six one three. Trace the array after each "
        "pass of the algorithm on the board.",
        "This will appear on the midterm exam. You must be able to state the worst "
        "case and justify it for the exam.",
    ]

    @classmethod
    def _lecture(cls, root: Path, *, markers: list[dict] | None = None) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "session.json").write_text(
            json.dumps({"session_id": "s", "course": "CEN4065", "title": "Sorting"}),
            encoding="utf-8",
        )
        rows: list[dict] = []
        stamp = 0.0
        for body in cls.PHASES:
            for _ in range(12):
                rows.append(
                    {
                        "start_seconds": stamp,
                        "end_seconds": stamp + 10,
                        "text": body,
                        "speaker": "professor",
                        "speaker_id": "0",
                    }
                )
                stamp += 10
        _write_jsonl(root / "transcript.jsonl", rows)
        if markers:
            _write_jsonl(root / "markers.jsonl", markers)
        return root

    def test_progression_is_recovered_without_any_captured_topics(
        self, tmp_path: Path
    ) -> None:
        evidence = load_session_evidence(self._lecture(tmp_path / "lecture"))
        assert evidence.topics == [], "fixture must have no captured topics"

        sections = evidence.lecture_structure()
        assert len(sections) >= 4, "a five-phase lecture must not collapse to one topic"
        assert [s.ordinal for s in sections] == list(range(len(sections)))

        starts = [s.start_seconds for s in sections]
        assert starts == sorted(starts), "sections must follow lecture order"
        for section in sections:
            assert section.end_seconds >= section.start_seconds

    def test_section_labels_come_from_the_professors_own_words(
        self, tmp_path: Path
    ) -> None:
        evidence = load_session_evidence(self._lecture(tmp_path / "lecture"))
        sections = evidence.lecture_structure()

        first = " ".join(sections[0].keywords)
        last = " ".join(sections[-1].keywords)
        assert "asymptotic" in first or "big-o" in first, first
        assert "midterm" in last or "exam" in last or "worst" in last, last
        assert all(
            not keyword.endswith((".", "-", "_")) for s in sections for keyword in s.keywords
        ), "punctuation must not leak into labels"

    def test_derived_structure_is_never_presented_as_professor_speech(
        self, tmp_path: Path
    ) -> None:
        evidence = load_session_evidence(self._lecture(tmp_path / "lecture"))
        sections = evidence.lecture_structure()

        assert all(s.provenance is Provenance.NOVA_DERIVED for s in sections)
        assert all(s.is_derived for s in sections)

        rendered = lecture_structure_markdown(evidence)
        assert "Reconstructed by NOVA" in rendered
        assert "NOT the professor's own section headings" in rendered

    def test_captured_topics_win_over_derivation(self, tmp_path: Path) -> None:
        session = self._lecture(tmp_path / "lecture")
        _write_jsonl(
            session / "topics.jsonl",
            [
                {"start_seconds": 0.0, "topic": "Big-O review"},
                {"start_seconds": 300.0, "topic": "Insertion sort"},
            ],
        )
        evidence = load_session_evidence(session)
        sections = evidence.lecture_structure()

        assert [s.label for s in sections] == ["Big-O review", "Insertion sort"]
        assert all(s.provenance is Provenance.CAPTURED_AUDIO for s in sections)
        assert all(s.confidence == 1.0 for s in sections)
        assert "Recorded during the lecture" in lecture_structure_markdown(evidence)

    def test_markers_and_questions_attach_to_their_section(self, tmp_path: Path) -> None:
        session = self._lecture(
            tmp_path / "lecture",
            markers=[
                {
                    "timestamp_seconds": 540.0,
                    "kind": "exam_likely",
                    "label": "worst case on the midterm",
                }
            ],
        )
        evidence = load_session_evidence(session)
        sections = evidence.lecture_structure()

        owning = [s for s in sections if s.marker_ids]
        assert len(owning) == 1, "the marker must land in exactly one section"
        assert owning[0].start_seconds <= 540.0 <= owning[0].end_seconds
        assert owning[0].marker_ids == [evidence.markers[0].evidence_id]
        assert owning[0].confidence > 0.0

    def test_structure_is_deterministic(self, tmp_path: Path) -> None:
        session = self._lecture(tmp_path / "lecture")
        first = [s.to_dict() for s in load_session_evidence(session).lecture_structure()]
        second = [s.to_dict() for s in load_session_evidence(session).lecture_structure()]
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_structure_is_serialized_into_the_evidence_payload(
        self, tmp_path: Path
    ) -> None:
        session = self._lecture(tmp_path / "lecture")
        evidence = load_session_evidence(session)
        payload = evidence.to_dict()

        assert payload["schema_version"] == EVIDENCE_SCHEMA_VERSION >= 2
        assert payload["structure"], "structure must be persisted for downstream consumers"
        assert payload["structure"][0]["provenance"] == "nova_derived"

    def test_short_and_empty_lectures_do_not_over_segment(self, tmp_path: Path) -> None:
        root = tmp_path / "tiny"
        root.mkdir(parents=True)
        _write_jsonl(
            root / "transcript.jsonl",
            [{"start_seconds": 0.0, "end_seconds": 4.0, "text": "Hello everyone."}],
        )
        assert len(load_session_evidence(root).lecture_structure()) <= 1

        assert derive_lecture_structure(SessionEvidence(session_id="s", course="c", title="t")) == []

    @staticmethod
    def _synthetic_lecture(root: Path, *, minutes: int, topics: int) -> Path:
        import random

        random.seed(7)
        root.mkdir(parents=True, exist_ok=True)
        (root / "session.json").write_text(
            json.dumps({"session_id": "s", "course": "C", "title": "x"}), encoding="utf-8"
        )
        vocabulary = [f"concept{i}" for i in range(topics * 4 + 8)]
        segments = minutes * 6
        per_topic = max(1, segments // topics)
        rows = []
        for index in range(segments):
            topic = min(topics - 1, index // per_topic)
            words = " ".join(
                random.choice(vocabulary[topic * 4 : topic * 4 + 8]) for _ in range(18)
            )
            rows.append(
                {
                    "start_seconds": index * 10.0,
                    "end_seconds": index * 10 + 10,
                    "text": f"The professor explains {words} in detail",
                    "speaker": "professor",
                    "speaker_id": "0",
                }
            )
        _write_jsonl(root / "transcript.jsonl", rows)
        return root

    @pytest.mark.parametrize("minutes", [14, 50, 90, 120])
    def test_long_lectures_neither_collapse_nor_fragment(
        self, tmp_path: Path, minutes: int
    ) -> None:
        """Regression: an over-eager minimum folded whole lectures into 1 section."""
        session = self._synthetic_lecture(
            tmp_path / f"lecture{minutes}", minutes=minutes, topics=8
        )
        evidence = load_session_evidence(session)
        sections = evidence.lecture_structure()

        assert 2 <= len(sections) <= 14, f"{minutes} min produced {len(sections)} sections"
        # The progression must span the whole lecture, not just its opening.
        assert sections[0].start_seconds == 0.0
        assert sections[-1].end_seconds >= evidence.duration_seconds * 0.95
        # And it must be contiguous and ordered.
        for earlier, later in zip(sections, sections[1:]):
            assert later.start_seconds >= earlier.start_seconds

    def test_digest_carries_the_progression(self, tmp_path: Path) -> None:
        evidence = load_session_evidence(self._lecture(tmp_path / "lecture"))
        digest = evidence_digest_markdown(evidence)
        assert "## Lecture progression" in digest


class TestCorruptSessionDegradation:
    """A malformed journal must degrade, never abort the post-class job.

    Both helpers exercised here crashed on corrupt input at baseline 776c53d:
    ``_elapsed`` raised ``ValueError`` on a non-numeric timestamp and
    ``_role_label`` raised ``AttributeError`` when ``speaker_roles.json``
    carried a non-dict ``speakers`` value.
    """

    @staticmethod
    def _corrupt_session(root: Path) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "session.json").write_text("{ this is not json", encoding="utf-8")
        (root / "transcript.jsonl").write_text(
            '{"start_seconds":"abc","text":"non-numeric timestamp"}\n'
            "not json at all\n"
            '["a","list","not","a","dict"]\n'
            '{"start_seconds":-50,"text":"negative timestamp"}\n'
            '{"start_seconds":null,"text":"null timestamp"}\n'
            '{"text":"   "}\n'
            '{"start_seconds":1,"text":"a good line","speaker_id":7}\n'
            '{"start_seconds":2,"text":"truncated mid-write"',
            encoding="utf-8",
        )
        (root / "speaker_roles.json").write_text(
            json.dumps({"speakers": "not a dict"}), encoding="utf-8"
        )
        return root

    def test_evidence_loader_survives_corrupt_journals(self, tmp_path: Path) -> None:
        session = self._corrupt_session(tmp_path / "corrupt")
        evidence = load_session_evidence(session)

        assert evidence.speakers == {}, "non-dict speaker map must fall back"
        assert any("transcript.jsonl" in w for w in evidence.warnings)
        assert all(item.start_seconds >= 0 for item in evidence.items)
        assert lecture_timeline_markdown(evidence)

    def test_elapsed_tolerates_unusable_timestamps(self) -> None:
        from nova_capture.postprocess import _elapsed

        assert _elapsed("abc") == "00:00"
        assert _elapsed(None) == "00:00"
        assert _elapsed(-50) == "00:00"
        assert _elapsed(65) == "01:05"

    def test_postprocess_completes_on_a_corrupt_session(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from nova_capture import postprocess
        import nova_school.context as context_module

        session = self._corrupt_session(tmp_path / "raw" / "CEN4065" / "s")
        monkeypatch.setattr(
            postprocess, "course_sessions_root", lambda _: tmp_path / "vault"
        )
        monkeypatch.setattr(
            context_module, "course_materials_root", lambda _: tmp_path / "materials"
        )
        monkeypatch.setattr(
            context_module, "course_sessions_root", lambda _: tmp_path / "prior"
        )

        async def unavailable(task: str, *, role: str = "reasoning"):
            return None

        monkeypatch.setattr(postprocess, "_route", unavailable)

        import asyncio

        folder = asyncio.run(postprocess.process_session(session))
        state = json.loads((session / "postprocess.json").read_text(encoding="utf-8"))

        assert state["status"] == "completed"
        assert state["evidence_warnings"]
        assert (folder / "Lecture.md").exists()

    def test_postprocess_completes_on_an_empty_session(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from nova_capture import postprocess
        import nova_school.context as context_module

        session = tmp_path / "raw" / "CEN4065" / "empty"
        session.mkdir(parents=True)
        monkeypatch.setattr(
            postprocess, "course_sessions_root", lambda _: tmp_path / "vault"
        )
        monkeypatch.setattr(
            context_module, "course_materials_root", lambda _: tmp_path / "materials"
        )
        monkeypatch.setattr(
            context_module, "course_sessions_root", lambda _: tmp_path / "prior"
        )

        async def unavailable(task: str, *, role: str = "reasoning"):
            return None

        monkeypatch.setattr(postprocess, "_route", unavailable)

        import asyncio

        folder = asyncio.run(postprocess.process_session(session))
        state = json.loads((session / "postprocess.json").read_text(encoding="utf-8"))
        assert state["status"] == "completed"
        assert (folder / "Summary.md").exists()


def test_empty_evidence_renders_safely() -> None:
    empty = SessionEvidence(session_id="s", course="c", title="t")
    assert "no lecture evidence" in lecture_timeline_markdown(empty)
    assert "no markers" in evidence_digest_markdown(empty)
    assert empty.duration_seconds == 0.0
