from __future__ import annotations

from pathlib import Path
import subprocess

from nova_intelligence.context_broker import ContextBroker
from nova_intelligence.shadow_eval import ShadowEvaluationRecord, ShadowEvaluationStore


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "NOVA"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "a1@example.invalid")
    _git(root, "config", "user.name", "A1 Test")
    (root / "README.md").write_text("# NOVA\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "base")
    _git(root, "branch", "-M", "lab/nova-a1-core-intelligence-test")
    return root


def test_non_project_task_gets_tiny_base_only(tmp_path: Path) -> None:
    broker = ContextBroker(_repo(tmp_path), shadow_store=ShadowEvaluationStore(tmp_path / "s.jsonl"))
    packet = broker.build_packet("what time is it")
    assert packet.project is None
    assert packet.project_status == "NOT_NEEDED"
    assert not packet.influence_allowed


def test_addressing_nova_does_not_make_a_weather_task_project_bearing(tmp_path: Path) -> None:
    broker = ContextBroker(_repo(tmp_path), shadow_store=ShadowEvaluationStore(tmp_path / "s.jsonl"))
    packet = broker.build_packet("NOVA, what time is it and what is the weather?")
    assert packet.project is None
    assert packet.project_status == "NOT_NEEDED"


def test_project_task_gets_shadow_packet_by_default(tmp_path: Path) -> None:
    broker = ContextBroker(_repo(tmp_path), shadow_store=ShadowEvaluationStore(tmp_path / "s.jsonl"))
    packet = broker.build_packet("inspect the NOVA git branch")
    assert packet.project is not None
    assert packet.project_status == "SHADOW_ONLY"
    assert not packet.influence_allowed


def test_env_opt_in_alone_cannot_enable_influence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NOVA_CORE_PROJECT_INFLUENCE", "true")
    broker = ContextBroker(_repo(tmp_path), shadow_store=ShadowEvaluationStore(tmp_path / "s.jsonl"))
    assert not broker.project_influence_allowed()


def test_influence_requires_opt_in_and_graduated_metrics(tmp_path: Path, monkeypatch) -> None:
    store = ShadowEvaluationStore(tmp_path / "s.jsonl")
    for _ in range(50):
        store.record(
            ShadowEvaluationRecord.create(
                project_id="nova",
                evaluable=True,
                packet_injected=True,
                project_correct=True,
            )
        )
    broker = ContextBroker(_repo(tmp_path), shadow_store=store)
    assert not broker.project_influence_allowed()

    monkeypatch.setenv("NOVA_CORE_PROJECT_INFLUENCE", "enabled")
    assert broker.project_influence_allowed()


def test_render_labels_unknown_and_shadow_rules(tmp_path: Path) -> None:
    broker = ContextBroker(_repo(tmp_path), shadow_store=ShadowEvaluationStore(tmp_path / "s.jsonl"))
    rendered = broker.render_for_model("NOVA architecture")
    assert "SHADOW_ONLY" in rendered
    assert "UNKNOWN means do not guess" in rendered
    assert "cannot authorize protected technical actions" in rendered
