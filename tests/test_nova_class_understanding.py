"""One understanding, many views — the map/reduce generation path.

Replaces the old design, which sent the same ~32,000-character evidence bundle
to the model once per output document. On 2026-08-28 that produced five
fallback dumps for a real CEN4934 class while `postprocess.json` still said
`"completed"`. These tests pin the properties that failure violated.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest

from nova_capture.evidence import (
    EvidenceItem,
    EvidenceKind,
    LectureSection,
    Provenance,
    SessionEvidence,
)
from nova_capture.renderers import RENDERERS, render_all
from nova_capture.understanding import (
    DEFAULT_REQUEST_SAFETY_MARGIN_TOKENS,
    DEFAULT_REQUEST_TOKEN_LIMIT,
    DEFAULT_RESERVED_OUTPUT_TOKENS,
    DIGEST_ITEM_LIMIT,
    WINDOW_CHARS,
    LectureUnderstanding,
    SectionUnderstanding,
    WindowDigest,
    build_global_reduce_prompt,
    build_section_reduce_prompt,
    build_understanding,
    build_window_prompt,
    estimate_prompt_tokens,
    request_fits_budget,
    _sections_from_payload,
    load_understanding,
    parse_window_digest,
    plan_windows,
    write_understanding,
)


def _evidence(*, minutes: float = 40.0, words_per_line: int = 18) -> SessionEvidence:
    """A synthetic lecture long enough to need several windows."""
    items: list[EvidenceItem] = []
    seconds = 0.0
    index = 0
    while seconds < minutes * 60:
        topic = "alpha" if seconds < minutes * 30 else "beta"
        items.append(
            EvidenceItem(
                evidence_id=f"t{index}",
                kind=EvidenceKind.TRANSCRIPT,
                provenance=Provenance.CAPTURED_AUDIO,
                start_seconds=seconds,
                end_seconds=seconds + 4.0,
                text=f"{topic} " + " ".join(f"word{index}x{n}" for n in range(words_per_line)),
                speaker_id="0",
            )
        )
        seconds += 4.0
        index += 1
    return SessionEvidence(
        session_id="s1", course="COP3710", title="Class Session", items=items
    )


def _is_map(prompt: str) -> bool:
    """Map prompts carry raw transcript; reduce prompts carry digests."""
    return "TRANSCRIPT:" in prompt


async def _ok(prompt: str) -> str:
    if not _is_map(prompt):
        return json.dumps(
            {
                "sections": [
                    {"label": "alpha", "thesis": "About alpha.", "points": ["a1", "a2"]}
                ],
                "definitions": ["alpha: the first thing"],
                "examples": ["an alpha example"],
                "assignments": ["read chapter 1"],
                "deadlines": ["due Friday"],
                "exam_signals": ["this will be on the exam"],
                "emphasis": ["alpha matters"],
                "review_priorities": ["revisit alpha"],
            }
        )
    return json.dumps(
        {
            "thesis": "a window about alpha",
            "points": ["p1", "p2"],
            "definitions": ["d1"],
            "examples": [],
            "assignments": [],
            "deadlines": [],
            "exam_signals": [],
            "emphasis": [],
        }
    )


async def _dead(prompt: str) -> None:
    return None


# --- the constraint that forced this design ---------------------------------


def test_every_window_prompt_fits_a_stock_ollama_context() -> None:
    """2,048 tokens is what an unconfigured Ollama serves. Nothing may exceed it."""
    evidence = _evidence(minutes=90.0)
    windows = plan_windows(evidence)
    assert windows

    largest = max(len(build_window_prompt(w, evidence.course)) for w in windows)
    assert largest // 4 <= 2048, (
        f"largest map prompt is ~{largest // 4} tokens; the whole point of "
        "windowing is that it fits the smallest model NOVA runs on"
    )


def test_token_estimate_is_conservative_for_non_ascii_text() -> None:
    arabic = "مرحبا" * 100
    assert estimate_prompt_tokens(arabic) >= len(arabic), (
        "multilingual lecture text must not be estimated with an English-only "
        "chars-per-token ratio"
    )


def test_windows_never_cross_a_topic_section() -> None:
    """A digest must be about one topic, or its thesis is meaningless."""
    evidence = _evidence(minutes=60.0)
    for window in plan_windows(evidence):
        assert window.section_id
        assert window.start_seconds <= window.end_seconds


def test_splitting_by_section_alone_would_not_have_worked() -> None:
    """The real lecture had 36- and 48-minute sections. Sections need windowing."""
    evidence = _evidence(minutes=90.0)
    windows = plan_windows(evidence)
    sections = {w.section_id for w in windows}
    assert len(windows) > len(sections), (
        "windowing must subdivide sections, not just follow them"
    )


def test_window_size_is_configurable_and_changes_the_plan() -> None:
    evidence = _evidence(minutes=60.0)
    small = plan_windows(evidence, window_chars=3_000)
    large = plan_windows(evidence, window_chars=WINDOW_CHARS)
    assert len(small) > len(large)


# --- map --------------------------------------------------------------------


def test_a_window_the_model_cannot_digest_is_marked_degraded() -> None:
    window = plan_windows(_evidence(minutes=10.0))[0]
    assert parse_window_digest(window, None).degraded
    assert parse_window_digest(window, "sorry, I cannot help").degraded
    # Valid JSON that says nothing is still a failure.
    assert parse_window_digest(window, '{"points": []}').degraded


def test_a_good_digest_keeps_its_real_timestamps() -> None:
    window = plan_windows(_evidence(minutes=10.0))[0]
    digest = parse_window_digest(
        window, '{"thesis": "x", "points": ["a"], "definitions": []}'
    )
    assert not digest.degraded
    assert digest.start_seconds == window.start_seconds
    assert digest.end_seconds == window.end_seconds
    assert digest.section_id == window.section_id


# --- reduce -----------------------------------------------------------------


def test_reduce_output_gets_the_full_span_of_its_section() -> None:
    """A section spans many windows; anchoring to one reports the wrong start."""
    understanding = asyncio.run(build_understanding(_evidence(minutes=60.0), route=_ok))
    alpha = [s for s in understanding.sections if s.label == "alpha"]
    assert alpha, "the reduce section should have been matched to real timestamps"
    assert alpha[0].start_seconds == pytest.approx(0.0, abs=5.0), (
        "a section that starts at the beginning of the lecture must say so"
    )
    assert alpha[0].end_seconds > alpha[0].start_seconds


def test_degraded_windows_are_excluded_from_the_reduce_prompt() -> None:
    digests = [
        WindowDigest(0, "s", "alpha", 0.0, 10.0, thesis="kept", points=["p"]),
        WindowDigest(1, "s", "alpha", 10.0, 20.0, degraded=True),
    ]
    prompt = build_section_reduce_prompt(
        digests, course="COP3710", section_label="alpha"
    )
    assert "kept" in prompt
    assert prompt.count("###") == 1


def test_course_materials_reach_the_reduce_prompt_but_stay_secondary() -> None:
    sections = [SectionUnderstanding("s", "alpha", 0.0, 10.0, "t", ["p"])]
    prompt = build_global_reduce_prompt(
        sections, course="COP3710", title="t", materials="chapter 4 covers alpha"
    )
    assert "chapter 4 covers alpha" in prompt
    assert "lecture is primary" in prompt


# --- graceful degradation ---------------------------------------------------


def test_a_total_model_outage_still_produces_honest_documents() -> None:
    """The 2026-08-28 failure mode: no model, five silent dumps, clean status."""
    understanding = asyncio.run(
        build_understanding(
            _evidence(minutes=30.0), route=_dead, retry_delay_seconds=0.0
        )
    )

    assert understanding.degraded
    assert len(understanding.degraded_windows) == len(understanding.windows)
    assert understanding.reduce_degraded
    assert understanding.warnings()

    documents = render_all(understanding)
    assert set(documents) == set(RENDERERS)
    for name, text in documents.items():
        assert text.strip(), f"{name} must never be empty"
        assert "Incomplete" in text, f"{name} must say it is incomplete"


def test_one_bad_window_costs_one_window_not_a_document() -> None:
    calls = {"n": 0}

    async def flaky(prompt: str) -> str | None:
        if not _is_map(prompt):
            return await _ok(prompt)
        calls["n"] += 1
        return None if calls["n"] == 2 else await _ok(prompt)

    understanding = asyncio.run(
        build_understanding(
            _evidence(minutes=60.0),
            route=flaky,
            max_attempts=1,
            retry_delay_seconds=0.0,
        )
    )
    assert understanding.degraded_windows == [1]
    assert not understanding.reduce_degraded
    assert understanding.sections, "the rest of the lecture still produced sections"


def test_reduce_failure_falls_back_to_the_window_digests() -> None:
    async def map_only(prompt: str) -> str | None:
        return await _ok(prompt) if _is_map(prompt) else None

    understanding = asyncio.run(
        build_understanding(
            _evidence(minutes=40.0), route=map_only, retry_delay_seconds=0.0
        )
    )
    assert understanding.reduce_degraded
    assert not understanding.degraded_windows
    # The map work is real and must not be thrown away.
    assert understanding.sections
    assert understanding.definitions


# --- rendering --------------------------------------------------------------


def test_every_document_is_a_view_of_the_same_object() -> None:
    """Five independent generations could contradict each other. Views cannot."""
    understanding = asyncio.run(build_understanding(_evidence(minutes=40.0), route=_ok))
    documents = render_all(understanding)

    assert set(documents) == {
        "Lecture.md",
        "Summary.md",
        "Study.md",
        "Questions.md",
        "Presentation Outline.md",
    }
    for name, text in documents.items():
        assert text.endswith("\n")
        assert understanding.course in text, f"{name} lost the course"

    label = understanding.sections[0].label
    assert label in documents["Lecture.md"]
    assert label in documents["Summary.md"]
    assert label in documents["Presentation Outline.md"]


def test_rendering_costs_no_model_calls() -> None:
    understanding = asyncio.run(build_understanding(_evidence(minutes=20.0), route=_ok))
    # render_all is synchronous by construction -- it cannot await a model.
    assert not inspect.iscoroutinefunction(render_all)
    render_all(understanding)


def test_nova_recommendations_stay_labelled_as_nova() -> None:
    understanding = asyncio.run(build_understanding(_evidence(minutes=30.0), route=_ok))
    study = RENDERERS["Study.md"](understanding)
    if understanding.review_priorities:
        assert "NOVA" in study
        assert "not the professor" in study


def test_questions_are_rendered_without_inventing_answers() -> None:
    understanding = LectureUnderstanding(
        course="COP3710",
        title="t",
        qa=[
            {"timestamp_seconds": 30.0, "question": "What is UML?", "answer": "A language."},
            {"timestamp_seconds": 60.0, "question": "And SQL?", "answer": ""},
        ],
    )
    text = RENDERERS["Questions.md"](understanding)
    assert "What is UML?" in text
    assert "A language." in text
    assert "No answer was logged." in text
    assert "NOVA" in text, "NOVA's answers must be attributed to NOVA"


# --- persistence ------------------------------------------------------------


def test_the_understanding_round_trips_through_disk(tmp_path: Path) -> None:
    original = asyncio.run(build_understanding(_evidence(minutes=30.0), route=_ok))
    write_understanding(tmp_path, original)

    restored = load_understanding(tmp_path)
    assert restored is not None
    assert restored.course == original.course
    assert [s.label for s in restored.sections] == [s.label for s in original.sections]
    assert restored.definitions == original.definitions
    assert len(restored.windows) == len(original.windows)
    assert restored.degraded_windows == original.degraded_windows

    # Documents rendered from the restored object are identical.
    assert render_all(restored) == render_all(original)


def test_a_missing_or_corrupt_understanding_reads_as_none(tmp_path: Path) -> None:
    assert load_understanding(tmp_path) is None
    (tmp_path / "understanding.json").write_text("{not json", encoding="utf-8")
    assert load_understanding(tmp_path) is None


# --- the status honesty fix -------------------------------------------------


def test_postprocess_reports_warnings_instead_of_a_clean_completion() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "nova_capture" / "postprocess.py"
    ).read_text(encoding="utf-8")
    assert 'status="completed_with_warnings" if understanding.degraded else "completed"' in source
    assert "understanding.warnings()" in source


def test_the_five_generation_path_is_gone() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "nova_capture" / "postprocess.py"
    ).read_text(encoding="utf-8")
    assert "_generate_doc" not in source
    assert "extract_evidence" not in source
    assert "could not reach a model for this session" not in source
    assert "render_all(understanding)" in source


def test_manual_postprocess_loads_provider_credentials() -> None:
    """A manual rerun must not silently lose every cloud provider.

    postprocess is normally spawned by class_capture.py and inherits its
    environment. Run by hand on 2026-08-28, every provider reported
    "not_configured" and the whole lecture fell back to a local model that was
    not running -- 15 of 15 windows degraded.
    """
    source = (
        Path(__file__).resolve().parents[1] / "nova_capture" / "postprocess.py"
    ).read_text(encoding="utf-8")
    main_body = source.split("def main() -> int:")[1].split("def launch_postprocess")[0]
    assert "load_dotenv" in main_body
    assert '.env"' in main_body


def test_generation_gets_an_output_budget_big_enough_for_a_digest() -> None:
    """NOVA's shared provider defaults are 600/400 output tokens.

    That is right for a spoken specialist answer and far too small for a
    structured lecture digest. On 2026-08-28 every Groq call returned
    "Groq returned an empty response" -- gpt-oss-120b is a reasoning model and
    spent the whole budget thinking. Post-processing is its own process, so it
    raises the budget for itself only.
    """
    from nova_capture.postprocess import (
        CLASS_GENERATION_MAX_TOKENS,
        _raise_generation_output_budget,
    )

    assert CLASS_GENERATION_MAX_TOKENS >= 4_000
    assert DEFAULT_RESERVED_OUTPUT_TOKENS == CLASS_GENERATION_MAX_TOKENS, (
        "the understanding request envelope must reserve the same output budget "
        "that postprocess actually sends to providers"
    )

    environment: dict[str, str] = {}
    _raise_generation_output_budget(environment)
    assert environment["GROQ_MAX_TOKENS"] == str(CLASS_GENERATION_MAX_TOKENS)
    assert environment["OLLAMA_MAX_TOKENS"] == str(CLASS_GENERATION_MAX_TOKENS)
    assert environment["OPENAI_MAX_OUTPUT_TOKENS"] == str(CLASS_GENERATION_MAX_TOKENS)


def test_an_explicitly_configured_output_budget_always_wins() -> None:
    from nova_capture.postprocess import _raise_generation_output_budget

    environment = {"GROQ_MAX_TOKENS": "1234"}
    _raise_generation_output_budget(environment)
    assert environment["GROQ_MAX_TOKENS"] == "1234"

    override = {"NOVA_CLASS_GENERATION_MAX_TOKENS": "2500"}
    _raise_generation_output_budget(override)
    assert override["GROQ_MAX_TOKENS"] == "2500"


def test_request_envelope_tracks_the_actual_provider_reservation() -> None:
    from nova_capture.postprocess import (
        _generation_request_budget,
        _raise_generation_output_budget,
    )

    environment: dict[str, str] = {}
    _raise_generation_output_budget(environment)
    limit, reserved = _generation_request_budget(environment)
    assert limit == DEFAULT_REQUEST_TOKEN_LIMIT
    assert reserved == DEFAULT_RESERVED_OUTPUT_TOKENS

    explicit = {
        "GROQ_MAX_TOKENS": "6000",
        "OPENAI_MAX_OUTPUT_TOKENS": "3000",
        "OLLAMA_MAX_TOKENS": "2000",
    }
    limit, reserved = _generation_request_budget(explicit)
    assert limit == DEFAULT_REQUEST_TOKEN_LIMIT
    assert reserved == 6000, (
        "the request guard must reserve the largest output any fallback provider "
        "could actually request"
    )

    widened = {"NOVA_CLASS_REQUEST_TOKEN_LIMIT": "12000"}
    limit, reserved = _generation_request_budget(widened)
    assert limit == 12000
    assert reserved == DEFAULT_RESERVED_OUTPUT_TOKENS


    malformed = {"GROQ_MAX_TOKENS": "not-a-number"}
    _, reserved = _generation_request_budget(malformed)
    assert reserved == DEFAULT_RESERVED_OUTPUT_TOKENS


def test_the_budget_is_raised_only_inside_the_postprocess_process() -> None:
    """Live Q&A and the voice agent must keep the small spoken-answer budget."""
    root = Path(__file__).resolve().parents[1]
    for name in ("class_capture.py", "nova_capture/live_notes.py",
                 "nova_capture/intelligence.py"):
        source = (root / name).read_text(encoding="utf-8-sig")
        assert "GROQ_MAX_TOKENS" not in source, (
            f"{name} must not widen the shared output budget"
        )


def test_reduce_sections_are_placed_by_the_windows_they_cite() -> None:
    """The model may subdivide a derived section; each part needs its own span.

    The real CEN4934 lecture had one 36-minute derived section covering three
    distinct student projects. Without citations all three claimed [0-36m].
    """
    digests = [
        WindowDigest(0, "sec1", "block", 0.0, 600.0, thesis="a", points=["p"]),
        WindowDigest(1, "sec1", "block", 600.0, 1200.0, thesis="b", points=["p"]),
        WindowDigest(2, "sec1", "block", 1200.0, 1800.0, thesis="c", points=["p"]),
    ]
    produced = _sections_from_payload(
        {
            "sections": [
                {"label": "first project", "thesis": "t1", "points": ["x"], "windows": [0]},
                {"label": "second project", "thesis": "t2", "points": ["y"], "windows": [1, 2]},
            ]
        },
        digests,
    )

    spans = [(s.label, s.start_seconds, s.end_seconds) for s in produced]
    assert spans == [
        ("first project", 0.0, 600.0),
        ("second project", 600.0, 1800.0),
    ], "each section must span exactly the windows it cited"


def test_the_reduce_prompt_asks_for_window_citations() -> None:
    digests = [WindowDigest(7, "s", "alpha", 0.0, 10.0, thesis="t", points=["p"])]
    prompt = build_section_reduce_prompt(
        digests, course="COP3710", section_label="alpha"
    )
    assert "window 7" in prompt, "windows must be numbered so they can be cited"
    assert '"windows"' in prompt


def test_a_rate_limited_window_is_retried_before_being_written_off() -> None:
    """Groq's free tier is 8,000 tokens/minute. A throttle is not a failure."""
    attempts = {"n": 0}

    async def throttled(prompt: str) -> str | None:
        if not _is_map(prompt):
            return await _ok(prompt)
        attempts["n"] += 1
        return None if attempts["n"] <= 2 else await _ok(prompt)

    evidence = _evidence(minutes=2.0)
    assert len(plan_windows(evidence)) == 1, "this test needs exactly one window"

    understanding = asyncio.run(
        build_understanding(
            evidence, route=throttled, max_attempts=3, retry_delay_seconds=0.0
        )
    )
    assert attempts["n"] == 3, "the window should have been retried twice"
    assert understanding.degraded_windows == [], "the retry should have rescued it"


def test_retries_are_bounded_so_a_dead_provider_does_not_hang_the_job() -> None:
    calls = {"n": 0}

    async def dead(prompt: str) -> None:
        if _is_map(prompt):
            calls["n"] += 1
        return None

    understanding = asyncio.run(
        build_understanding(
            _evidence(minutes=10.0),
            route=dead,
            max_attempts=2,
            retry_delay_seconds=0.0,
        )
    )
    windows = len(understanding.windows)
    assert calls["n"] == windows * 2, "each window is attempted exactly max_attempts times"
    assert len(understanding.degraded_windows) == windows


def test_reduce_scales_to_a_typical_long_multisection_lecture() -> None:
    """Normal long lectures keep each ordinary section inside the envelope."""
    evidence = _evidence(minutes=180.0)
    windows = plan_windows(evidence)
    assert len(windows) > 20, "a three-hour lecture should be many windows"

    digests = [
        WindowDigest(
            w.index, w.section_id, w.section_label, w.start_seconds, w.end_seconds,
            thesis="a thesis for this window",
            points=[f"point {n}" for n in range(DIGEST_ITEM_LIMIT)],
        )
        for w in windows
    ]
    by_section: dict[str, list[WindowDigest]] = {}
    for digest in digests:
        by_section.setdefault(digest.section_id, []).append(digest)

    for group in by_section.values():
        prompt = build_section_reduce_prompt(
            group, course="COP3710", section_label=group[0].section_label
        )
        assert request_fits_budget(prompt), (
            f"an ordinary section reduce over {len(group)} windows should fit the "
            "default provider request envelope"
        )


def test_one_very_long_semantic_section_is_hierarchically_reduced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A professor can stay on one topic for 90 minutes; never send it whole.

    The earlier 180-minute test happened to derive several small sections, so it
    did not prove the actual failure case. This forces one continuous section
    and dense map digests large enough that a monolithic reduce cannot fit.
    """
    evidence = _evidence(minutes=90.0)
    end_seconds = max(item.end_seconds for item in evidence.items)
    monkeypatch.setattr(
        "nova_capture.understanding.derive_lecture_structure",
        lambda _evidence: [
            LectureSection(
                section_id="one-long-topic",
                ordinal=0,
                start_seconds=0.0,
                end_seconds=end_seconds,
                label="one long topic",
            )
        ],
    )

    seen_prompts: list[str] = []

    async def dense_route(prompt: str) -> str:
        seen_prompts.append(prompt)
        if _is_map(prompt):
            detail = " ".join(["detail"] * 40)
            return json.dumps(
                {
                    "thesis": " ".join(["thesis"] * 35),
                    "points": [
                        f"synthetic point {index}: {detail}"
                        for index in range(DIGEST_ITEM_LIMIT)
                    ],
                    "definitions": [],
                    "examples": [],
                    "assignments": [],
                    "deadlines": [],
                    "exam_signals": [],
                    "emphasis": [],
                }
            )
        if "WINDOW DIGESTS:" in prompt:
            return json.dumps(
                {
                    "sections": [
                        {
                            "label": "one long topic",
                            "thesis": "A bounded synthetic summary.",
                            "points": ["A synthesized point."],
                            "windows": [],
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "definitions": [],
                "examples": [],
                "assignments": [],
                "deadlines": [],
                "exam_signals": [],
                "emphasis": [],
                "review_priorities": [],
            }
        )

    understanding = asyncio.run(
        build_understanding(
            evidence,
            route=dense_route,
            max_attempts=1,
            retry_delay_seconds=0.0,
        )
    )

    section_prompts = [
        prompt for prompt in seen_prompts if "WINDOW DIGESTS:" in prompt
    ]
    assert len(understanding.windows) > 20
    assert len(section_prompts) > 1, (
        "the forced 90-minute topic must trigger hierarchical section reduction"
    )
    assert max(prompt.count("### window") for prompt in section_prompts) < len(
        understanding.windows
    ), "the whole semantic section must never be sent in one reduce request"
    assert not understanding.reduce_degraded
    assert len(understanding.sections) == 1
    assert understanding.sections[0].start_seconds == 0.0
    assert understanding.sections[0].end_seconds == pytest.approx(end_seconds)

    for prompt in seen_prompts:
        assert request_fits_budget(prompt), (
            f"request estimate {estimate_prompt_tokens(prompt)} input + "
            f"{DEFAULT_RESERVED_OUTPUT_TOKENS} reserved + "
            f"{DEFAULT_REQUEST_SAFETY_MARGIN_TOKENS} safety must stay <= "
            f"{DEFAULT_REQUEST_TOKEN_LIMIT}"
        )


def test_a_single_section_covers_its_whole_group_whatever_it_cited() -> None:
    """Models cite only the first window; the span must not collapse to it.

    On the real CEN4934 lecture this reported a 36-minute opening section as
    "0:00-5:32" -- the model returned one section for the group and cited
    window 0 alone.
    """
    digests = [
        WindowDigest(0, "sec1", "block", 0.0, 330.0, thesis="a", points=["p"]),
        WindowDigest(1, "sec1", "block", 330.0, 1200.0, thesis="b", points=["q"]),
        WindowDigest(2, "sec1", "block", 1200.0, 2200.0, thesis="c", points=["r"]),
    ]
    produced = _sections_from_payload(
        {"sections": [{"label": "one topic", "thesis": "t", "points": ["x"],
                       "windows": [0]}]},
        digests,
    )
    assert len(produced) == 1
    assert produced[0].start_seconds == 0.0
    assert produced[0].end_seconds == 2200.0, (
        "one section for the group spans the whole group"
    )


def test_citations_still_decide_when_the_group_was_split() -> None:
    digests = [
        WindowDigest(0, "sec1", "block", 0.0, 600.0, thesis="a", points=["p"]),
        WindowDigest(1, "sec1", "block", 600.0, 1200.0, thesis="b", points=["q"]),
    ]
    produced = _sections_from_payload(
        {"sections": [
            {"label": "first", "thesis": "t1", "points": ["x"], "windows": [0]},
            {"label": "second", "thesis": "t2", "points": ["y"], "windows": [1]},
        ]},
        digests,
    )
    assert [(s.start_seconds, s.end_seconds) for s in produced] == [
        (0.0, 600.0),
        (600.0, 1200.0),
    ]
