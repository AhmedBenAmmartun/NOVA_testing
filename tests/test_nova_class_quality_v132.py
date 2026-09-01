from __future__ import annotations

from pathlib import Path

from nova_capture.class_budget import ClassCloudUsageBudget
from nova_capture.question_detection import should_answer_question


def test_short_greetings_do_not_trigger_live_ai() -> None:
    for text in ("Hello?", "Hi?", "Hey?", "What?", "Why?", "Ready?"):
        assert not should_answer_question(text)


def test_substantive_questions_still_trigger() -> None:
    assert should_answer_question("What is cohesion?")
    assert should_answer_question("What is the difference between aggregation and composition?")
    assert should_answer_question("Can you explain dependency inversion")


def test_class_budget_defaults_are_independent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NOVA_CLASS_CLOUD_BUDGET_ENABLED", raising=False)
    monkeypatch.delenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", raising=False)
    monkeypatch.setenv("NOVA_CLASS_CLOUD_USAGE_FILE", str(tmp_path / "class-budget.json"))
    budget = ClassCloudUsageBudget()
    assert budget.enabled is True
    # Raised 60 -> 200 on 2026-08-28 after a real class exhausted the cap
    # in under two hours. What this test guards is independence from the
    # general NOVA cloud budget, not the specific number.
    assert budget.daily_request_limit == 200
    assert budget.status()["used_today"] == 0


def test_class_budget_counts_without_touching_general_budget(monkeypatch, tmp_path: Path) -> None:
    class_path = tmp_path / "class-budget.json"
    monkeypatch.setenv("NOVA_CLASS_CLOUD_USAGE_FILE", str(class_path))
    monkeypatch.setenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", "2")
    budget = ClassCloudUsageBudget()
    assert budget.try_consume("groq").allowed
    assert budget.try_consume("openai").allowed
    decision = budget.try_consume("groq")
    assert not decision.allowed
    assert decision.reason == "daily_class_cloud_limit_reached"
    assert class_path.exists()


def test_intelligence_uses_dedicated_class_router() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "nova_capture" / "intelligence.py").read_text(encoding="utf-8-sig")
    assert "get_class_cloud_usage_budget" in source
    assert "create_model_router" in source
    assert "from tools.specialist import get_model_router" not in source
