from __future__ import annotations

from pathlib import Path

from nova_os.capabilities import CANONICAL_CAPABILITY_IDS
from nova_os.catalog import build_default_capability_manager


ROOT = Path(__file__).resolve().parents[1]


def test_development_capability_id_is_canonical() -> None:
    assert "development" in CANONICAL_CAPABILITY_IDS


def test_development_capability_exists_and_is_inactive_by_default() -> None:
    manager = build_default_capability_manager()
    spec = manager.registry.get("development")

    assert spec is not None
    assert spec.default_active is False
    assert manager.is_active("development") is False


def test_development_capability_has_only_v1b_tools() -> None:
    manager = build_default_capability_manager()
    spec = manager.registry.get("development")
    assert spec is not None

    assert set(spec.tool_names) == {
        "lab_status",
        "list_lab_features",
        "get_lab_feature",
        "list_lab_test_profiles",
        "register_lab_feature",
    }


def test_development_capability_exposes_no_release_or_shell_tool() -> None:
    manager = build_default_capability_manager()
    spec = manager.registry.get("development")
    assert spec is not None

    lowered = " ".join(spec.tool_names).lower()
    for forbidden in (
        "promote",
        "retire",
        "restart",
        "rollback",
        "delete",
        "shell",
        "command",
        "run_test",
        "transition",
        "approve",
    ):
        assert forbidden not in lowered


def test_default_tool_context_does_not_load_development_tools() -> None:
    manager = build_default_capability_manager()
    context = manager.build_tool_context()

    rendered = " ".join(str(getattr(item, "id", "")) for item in context)
    assert "nova_development" not in rendered

    result = manager.activate("development")
    assert result.startswith("Activated capability")
    activated = manager.build_tool_context()
    rendered = " ".join(str(getattr(item, "id", "")) for item in activated)
    assert "nova_development" in rendered


def test_development_tool_module_has_no_execution_or_approval_primitive() -> None:
    text = (ROOT / "tools" / "development.py").read_text(encoding="utf-8-sig")
    for forbidden in (
        "subprocess",
        "os.system",
        "permission_engine.approve",
        ".transition(",
        "FeatureState.ACTIVE",
        "FeatureState.RETIRED",
        "run_lab_tests",
    ):
        assert forbidden not in text
