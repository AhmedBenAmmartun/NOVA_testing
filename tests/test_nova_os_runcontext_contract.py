from types import SimpleNamespace

from tools.capabilities import _manager_from_context


class DummyManager:
    pass


class DummyAgent:
    def __init__(self) -> None:
        self.capability_manager = DummyManager()


def test_capability_tools_resolve_agent_through_livekit_session() -> None:
    agent = DummyAgent()
    context = SimpleNamespace(session=SimpleNamespace(current_agent=agent))
    resolved_agent, manager = _manager_from_context(context)
    assert resolved_agent is agent
    assert manager is agent.capability_manager


def test_capability_tools_do_not_require_removed_runcontext_agent_property() -> None:
    text = __import__("pathlib").Path("tools/capabilities.py").read_text(encoding="utf-8-sig")
    assert 'getattr(context, "agent"' not in text
    assert "session.current_agent" in text
