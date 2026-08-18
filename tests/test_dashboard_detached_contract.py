from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_dashboard_is_not_a_nova_runtime_component() -> None:
    assert not (ROOT / "Dashboard").exists()
    assert not (ROOT / "nova_bridge.py").exists()
    assert not (ROOT / "nova_agent_bridge.py").exists()

    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    for token in (
        "nova_agent_bridge",
        "dashboard_bridge_loop",
        "stop_dashboard_bridge",
        "nova_dashboard_bridge",
        "AgentStatusReporter",
        "bridge_status",
    ):
        assert token not in agent


def test_nova_launchers_and_env_do_not_start_dashboard() -> None:
    start = (ROOT / "Start-NOVA.ps1").read_text(encoding="utf-8-sig")
    assert "Dashboard\\nova-app" not in start
    assert "Start-NovaDashboard" not in start
    assert "NOVA_DASHBOARD_PORT" not in (ROOT / ".env.example").read_text(encoding="utf-8-sig")
    assert "NOVA_BRIDGE_DIR" not in (ROOT / ".env.example").read_text(encoding="utf-8-sig")


def test_dashboard_path_is_reserved_for_external_project() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")
    assert "Dashboard/" in gitignore
    assert "separate project" in gitignore


def test_nova_vision_and_os_remain_present() -> None:
    assert (ROOT / "vision-client").is_dir()
    assert (ROOT / "nova_os").is_dir()
    assert (ROOT / "skills").is_dir()

    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    assert "video_input=True" in agent
    assert "build_default_capability_manager" in agent
    assert "build_default_skill_registry" in agent
