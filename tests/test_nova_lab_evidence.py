from __future__ import annotations

from nova_lab.evidence import (
    TestEvidenceRecord as EvidenceRecord,
    TestEvidenceStore as EvidenceStore,
    now_iso,
    safe_summary,
    summarize_test_output,
)


def _record(**overrides) -> EvidenceRecord:
    base = dict(
        evidence_id="e1",
        feature_id="f1",
        capability_id="class_intelligence",
        commit_sha="a" * 40,
        branch="lab/example",
        test_profile="official",
        passed=True,
        returncode=0,
        started_at=now_iso(),
        completed_at=now_iso(),
        summary="returncode=0: 3 passed",
        job_id="job1",
    )
    base.update(overrides)
    return EvidenceRecord(**base)


def test_record_and_get_round_trip(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    evidence = _record()
    store.record(evidence)

    assert store.get("e1") == evidence


def test_unknown_evidence_id_returns_none(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    assert store.get("missing") is None


def test_evidence_survives_store_reconstruction(tmp_path) -> None:
    path = tmp_path / "evidence.jsonl"
    EvidenceStore(path).record(_record())

    reloaded = EvidenceStore(path)
    assert reloaded.get("e1") is not None
    assert reloaded.get("e1").commit_sha == "a" * 40


def test_evidence_for_a_different_commit_is_a_different_fact(tmp_path) -> None:
    """Same feature id, different commit: never conflated as the same evidence."""
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    store.record(_record(evidence_id="e1", commit_sha="a" * 40))
    store.record(_record(evidence_id="e2", commit_sha="b" * 40))

    first = store.get("e1")
    second = store.get("e2")
    assert first.commit_sha != second.commit_sha
    assert first.feature_id == second.feature_id


def test_list_for_feature_filters_by_feature_id(tmp_path) -> None:
    store = EvidenceStore(tmp_path / "evidence.jsonl")
    store.record(_record(evidence_id="e1", feature_id="f1"))
    store.record(_record(evidence_id="e2", feature_id="f2"))
    store.record(_record(evidence_id="e3", feature_id="f1"))

    ids = {item.evidence_id for item in store.list_for_feature("f1")}
    assert ids == {"e1", "e3"}


def test_summarize_test_output_redacts_secret_shaped_content() -> None:
    summary = summarize_test_output(returncode=1, stdout="line one\nAPI_KEY=sk-nope\n")
    assert "sk-nope" not in summary
    assert summary == "[sensitive test output redacted]"


def test_summarize_test_output_keeps_the_final_summary_line() -> None:
    summary = summarize_test_output(
        returncode=0, stdout="collecting...\n\n38 passed in 6.60s\n"
    )
    assert "38 passed" in summary
    assert "returncode=0" in summary


def test_summarize_test_output_never_dumps_full_stdout() -> None:
    huge_stdout = "\n".join(f"line {i}" for i in range(10_000)) + "\n1 failed"
    summary = summarize_test_output(returncode=1, stdout=huge_stdout)
    assert "line 1\n" not in summary
    assert len(summary) <= 400


def test_safe_summary_is_bounded() -> None:
    assert len(safe_summary("x" * 5000)) <= 400
