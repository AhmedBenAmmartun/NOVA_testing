"""U2 persistent-runtime foundation tests."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

from nova_runtime import HealthState, NovaRuntime, TaskStore


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_owns_the_durable_task_store(tmp_path) -> None:
    store = TaskStore(tmp_path)
    runtime = NovaRuntime(task_store=store)

    assert runtime.task_store is store


def test_generic_runtime_does_not_implicitly_own_durable_state() -> None:
    runtime = NovaRuntime()

    assert runtime.task_store is None


def test_agent_session_does_not_own_canonical_task_store() -> None:
    source = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    assert "runtime = NovaRuntime()" in source
    assert "runtime.task_store.recover()" not in source
    assert "TaskStore(" not in source


def test_startup_constructs_the_provider_independent_core() -> None:
    source = (ROOT / "nova_startup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "def build_core_runtime()" in source
    assert "NovaRuntime(task_store=TaskStore())" in source
    assert "recover_runtime_tasks(core_runtime)" in source
    assert "await core_runtime.shutdown()" in source

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden_prefixes = (
        "livekit",
        "providers",
        "nova_core",
        "openai",
        "groq",
        "google",
    )
    assert not any(
        module == prefix or module.startswith(prefix + ".")
        for module in imported
        for prefix in forbidden_prefixes
    )


def test_startup_state_is_outside_the_repository() -> None:
    source = (ROOT / "nova_startup.py").read_text(encoding="utf-8")

    assert 'RUNTIME_DIRECTORY = runtime_root() / "runtime"' in source
    assert 'LOG_PATH = RUNTIME_DIRECTORY / "nova_startup.log"' in source
    assert 'STATUS_PATH = RUNTIME_DIRECTORY / "nova_status.json"' in source
    assert 'PROJECT_ROOT / "logs"' not in source


def test_task_recovery_failure_degrades_without_killing_core() -> None:
    import nova_startup

    class BrokenStore:
        def recover(self):
            raise OSError("unreadable")

    runtime = NovaRuntime(task_store=BrokenStore())

    recovered = nova_startup.recover_runtime_tasks(runtime)

    assert recovered == 0
    health = runtime.health.get("task_store")
    assert health is not None
    assert health.state is HealthState.DEGRADED
    assert health.detail == "recovery:OSError"


def test_startup_check_runs_without_any_ai_provider(monkeypatch, tmp_path) -> None:
    import nova_startup

    runtime = NovaRuntime(task_store=TaskStore(tmp_path))

    class FakeGuardian:
        def __init__(self) -> None:
            self.running = False

        async def start(self) -> bool:
            self.running = True
            return True

        async def stop(self) -> bool:
            was_running = self.running
            self.running = False
            return was_running

        def safe_summary(self):
            return {"running": self.running}

    guardian = FakeGuardian()
    statuses: list[str] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(nova_startup, "build_core_runtime", lambda: runtime)
    monkeypatch.setattr(nova_startup, "get_guardian_runtime", lambda: guardian)
    monkeypatch.setattr(nova_startup.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        nova_startup,
        "write_status",
        lambda **kwargs: statuses.append(kwargs["state"]),
    )

    result = asyncio.run(nova_startup.run_startup_check())

    assert result == 0
    assert runtime.closed is True
    assert statuses == ["startup_check_running", "startup_check_complete"]


def test_startup_check_survives_guardian_start_failure(monkeypatch, tmp_path) -> None:
    import nova_startup

    runtime = NovaRuntime(task_store=TaskStore(tmp_path))

    class BrokenGuardian:
        async def start(self) -> bool:
            raise RuntimeError("guardian unavailable")

        async def stop(self) -> bool:
            return False

        def safe_summary(self):
            return {"running": False}

    statuses: list[str] = []

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(nova_startup, "build_core_runtime", lambda: runtime)
    monkeypatch.setattr(
        nova_startup,
        "get_guardian_runtime",
        lambda: BrokenGuardian(),
    )
    monkeypatch.setattr(nova_startup.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(
        nova_startup,
        "write_status",
        lambda **kwargs: statuses.append(kwargs["state"]),
    )

    result = asyncio.run(nova_startup.run_startup_check())

    assert result == 0
    assert runtime.closed is True
    guardian_health = runtime.health.get("guardian")
    assert guardian_health is not None
    assert guardian_health.state is HealthState.DEGRADED
    assert guardian_health.detail == "start:RuntimeError"
    assert statuses == ["startup_check_running", "startup_check_complete"]


def test_standby_core_survives_without_provider_startup(monkeypatch, tmp_path) -> None:
    import nova_startup

    runtime = NovaRuntime(task_store=TaskStore(tmp_path))

    class FakeGuardian:
        def __init__(self) -> None:
            self.running = False

        async def start(self) -> bool:
            self.running = True
            return True

        async def stop(self) -> bool:
            was_running = self.running
            self.running = False
            return was_running

        def safe_summary(self):
            return {"running": self.running}

    guardian = FakeGuardian()
    stopped_integrations: list[bool] = []

    async def cancel_after_first_loop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(nova_startup, "build_core_runtime", lambda: runtime)
    monkeypatch.setattr(nova_startup, "get_guardian_runtime", lambda: guardian)
    monkeypatch.setattr(nova_startup, "start_integrations_safely", lambda: False)
    monkeypatch.setattr(
        nova_startup,
        "stop_integrations_safely",
        lambda: stopped_integrations.append(True),
    )
    monkeypatch.setattr(nova_startup.asyncio, "sleep", cancel_after_first_loop)
    monkeypatch.setattr(nova_startup, "write_status", lambda **kwargs: None)

    result = asyncio.run(nova_startup.run_standby())

    assert result == 0
    assert runtime.closed is True
    assert stopped_integrations == [True]


def test_standby_core_survives_guardian_failure(monkeypatch, tmp_path) -> None:
    import nova_startup

    runtime = NovaRuntime(task_store=TaskStore(tmp_path))

    class BrokenGuardian:
        async def start(self) -> bool:
            raise RuntimeError("guardian unavailable")

        async def stop(self) -> bool:
            return False

        def safe_summary(self):
            return {"running": False}

    async def cancel_after_first_loop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(nova_startup, "build_core_runtime", lambda: runtime)
    monkeypatch.setattr(
        nova_startup,
        "get_guardian_runtime",
        lambda: BrokenGuardian(),
    )
    monkeypatch.setattr(nova_startup, "start_integrations_safely", lambda: False)
    monkeypatch.setattr(nova_startup, "stop_integrations_safely", lambda: None)
    monkeypatch.setattr(nova_startup.asyncio, "sleep", cancel_after_first_loop)
    monkeypatch.setattr(nova_startup, "write_status", lambda **kwargs: None)

    result = asyncio.run(nova_startup.run_standby())

    assert result == 0
    assert runtime.closed is True
    guardian_health = runtime.health.get("guardian")
    assert guardian_health is not None
    assert guardian_health.state is HealthState.DEGRADED
    assert guardian_health.detail == "start:RuntimeError"


def test_standby_core_survives_guardian_summary_failure(monkeypatch, tmp_path) -> None:
    import nova_startup

    runtime = NovaRuntime(task_store=TaskStore(tmp_path))

    class BrokenSummaryGuardian:
        async def start(self) -> bool:
            return True

        async def stop(self) -> bool:
            return True

        def safe_summary(self):
            raise ValueError("summary unavailable")

    async def cancel_after_first_loop(_seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(nova_startup, "build_core_runtime", lambda: runtime)
    monkeypatch.setattr(
        nova_startup,
        "get_guardian_runtime",
        lambda: BrokenSummaryGuardian(),
    )
    monkeypatch.setattr(nova_startup, "start_integrations_safely", lambda: False)
    monkeypatch.setattr(nova_startup, "stop_integrations_safely", lambda: None)
    monkeypatch.setattr(nova_startup.asyncio, "sleep", cancel_after_first_loop)
    monkeypatch.setattr(nova_startup, "write_status", lambda **kwargs: None)

    result = asyncio.run(nova_startup.run_standby())

    assert result == 0
    assert runtime.closed is True
    guardian_health = runtime.health.get("guardian")
    assert guardian_health is not None
    assert guardian_health.state is HealthState.DEGRADED
    assert guardian_health.detail == "summary:ValueError"
