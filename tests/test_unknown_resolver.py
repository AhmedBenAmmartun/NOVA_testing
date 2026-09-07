from __future__ import annotations

from pathlib import Path

from nova_intelligence.resolver import (
    ProjectCandidate,
    ProjectResolver,
    ResolutionStatus,
)


def test_exact_alias_resolves() -> None:
    nova = ProjectCandidate("nova", "NOVA", Path("/projects/nova"), aliases=("ai agent",))
    decision = ProjectResolver([nova]).resolve("AI Agent")
    assert decision.status is ResolutionStatus.VERIFIED
    assert decision.project_id == "nova"
    assert decision.safe_for_protected_decision


def test_unknown_name_does_not_fuzzy_guess() -> None:
    nova = ProjectCandidate("nova", "NOVA", Path("/projects/nova"))
    valo = ProjectCandidate("valo", "Valo", Path("/projects/valo"))
    decision = ProjectResolver([nova, valo]).resolve("nov")
    assert decision.status is ResolutionStatus.UNKNOWN
    assert not decision.safe_for_protected_decision


def test_duplicate_alias_is_ambiguous() -> None:
    a = ProjectCandidate("a", "Project A", Path("/a"), aliases=("agent",))
    b = ProjectCandidate("b", "Project B", Path("/b"), aliases=("agent",))
    decision = ProjectResolver([a, b]).resolve("agent")
    assert decision.status is ResolutionStatus.AMBIGUOUS
    assert decision.root is None


def test_cwd_containment_requires_unique_project(tmp_path: Path) -> None:
    a_root = tmp_path / "a"
    b_root = tmp_path / "b"
    (a_root / "src").mkdir(parents=True)
    b_root.mkdir()
    resolver = ProjectResolver(
        [
            ProjectCandidate("a", "A", a_root),
            ProjectCandidate("b", "B", b_root),
        ]
    )
    decision = resolver.resolve(cwd=a_root / "src")
    assert decision.status is ResolutionStatus.VERIFIED
    assert decision.project_id == "a"
