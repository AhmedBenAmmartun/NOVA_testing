from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

from nova_intelligence.models import FactStatus
from nova_intelligence.project_state import ProjectStateBuilder


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "NOVA"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "a1@example.invalid")
    _git(root, "config", "user.name", "A1 Test")
    (root / "README.md").write_text("# NOVA\n", encoding="utf-8")
    (root / "nova_os").mkdir()
    (root / "nova_os" / "capability_definitions.py").write_text(
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class CapabilityDefinition:\n"
        "    capability_id: str\n"
        "    name: str\n"
        "    description: str\n"
        "    risk: str = 'read_only'\n"
        "    default_active: bool = False\n"
        "    locked_active: bool = False\n"
        "CAPABILITY_DEFINITIONS = (\n"
        "    CapabilityDefinition(capability_id='system', name='System', "
        "description='x', default_active=True),\n"
        ")\n",
        encoding="utf-8",
    )
    _git(root, "add", "README.md", "nova_os/capability_definitions.py")
    _git(root, "commit", "-m", "base")
    _git(root, "branch", "-M", "lab/nova-a1-core-intelligence-test")
    return root


def test_builder_reads_verified_git_state(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    state = ProjectStateBuilder(root).build()

    assert state.identity["name"].value == "NOVA"
    assert state.repository["branch"].value == "lab/nova-a1-core-intelligence-test"
    assert state.repository["head"].status in {FactStatus.VERIFIED, FactStatus.STALE}
    assert state.repository["dirty"].value is False
    assert state.active_work["milestone"].value == "A1 Core Intelligence"

    caps = state.systems["capabilities"].value
    assert caps[0]["capability_id"] == "system"


def test_builder_reports_dirty_files(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    (root / "README.md").write_text("# NOVA changed\n", encoding="utf-8")
    state = ProjectStateBuilder(root).build()

    assert state.repository["dirty"].value is True
    assert "README.md" in state.repository["changed_files"].value
    assert any("working tree is dirty" in item for item in state.conflicts)


def test_unmatched_test_evidence_is_stale(tmp_path: Path, monkeypatch) -> None:
    root = _make_repo(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "commit_sha": "0" * 40,
                "passed": True,
                "gates": ["pytest"],
                "verified_at": "2026-09-06T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_CORE_TEST_EVIDENCE", str(evidence))
    state = ProjectStateBuilder(root).build()
    assert state.tests["latest"].status is FactStatus.STALE


def test_matching_but_expired_test_evidence_becomes_stale(tmp_path: Path, monkeypatch) -> None:
    root = _make_repo(tmp_path)
    head = _git(root, "rev-parse", "HEAD")
    evidence = tmp_path / "old-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "commit_sha": head,
                "passed": True,
                "gates": ["pytest"],
                "verified_at": (
                    datetime.now(timezone.utc) - timedelta(days=2)
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_CORE_TEST_EVIDENCE", str(evidence))
    state = ProjectStateBuilder(root).build()
    assert state.tests["latest"].status is FactStatus.STALE
    assert state.tests["latest"].freshness == "expired"


def test_matching_fresh_test_evidence_is_verified(tmp_path: Path, monkeypatch) -> None:
    root = _make_repo(tmp_path)
    head = _git(root, "rev-parse", "HEAD")
    evidence = tmp_path / "fresh-evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "commit_sha": head,
                "passed": True,
                "gates": ["pytest"],
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOVA_CORE_TEST_EVIDENCE", str(evidence))
    state = ProjectStateBuilder(root).build()
    assert state.tests["latest"].status is FactStatus.VERIFIED
    assert state.tests["latest"].freshness == "fresh"
