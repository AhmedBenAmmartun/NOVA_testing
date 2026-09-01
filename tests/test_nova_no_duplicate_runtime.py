"""NOVA must have exactly one task runtime and exactly one model router.

`core/` is superseded scaffolding that predates both live systems. It is still
on disk, unimported, and it collides by NAME with what actually runs:

    core/router.py:12        class ModelRouter    (47 lines, dead)
    nova_core/router.py:59   class ModelRouter    (421+ lines, live)

    core/task.py:25          class NovaTask       (dead task model)
    nova_runtime/task_state.py:17  class TaskSnapshot  (live task model)

    core/orchestrator.py:22  class NovaOrchestrator  (dead, zero importers)

The danger is not that `core/` runs -- nothing imports it. The danger is that
someone building the orchestrator imports `ModelRouter` and silently gets the
47-line stub, or revives `NovaOrchestrator` because the name is already there
and looks authoritative. That would give NOVA two routers and two task models
at once.

These tests make the ownership decision executable rather than a comment:

    nova_runtime  owns background jobs and task state
    nova_core     owns model routing and provider fallback
    core/         is history

`DEVELOPMENT.md` records that `core/` must not be deleted without Ahmed's
decision, so this file locks the boundary instead of removing the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Directories that are not NOVA's own source.
_SKIP_PARTS = {"venv", ".venv", "__pycache__", ".git", "worktrees", ".claude", "core"}


def _source_files() -> list[Path]:
    return [
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if not _SKIP_PARTS.intersection(path.parts)
    ]


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_nothing_in_nova_imports_the_superseded_core_package() -> None:
    """If this fails, a second router or task model just came alive."""
    offenders: list[str] = []
    for path in _source_files():
        for module in _imported_modules(path):
            if module == "core" or module.startswith("core."):
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module}")

    assert not offenders, (
        "core/ is superseded scaffolding and must not be imported. "
        "Use nova_runtime for tasks and nova_core for model routing. "
        + "; ".join(offenders)
    )


def test_the_live_task_runtime_is_nova_runtime() -> None:
    from nova_runtime import NovaRuntime

    runtime = NovaRuntime()

    assert runtime.jobs is not None
    assert runtime.events is not None


def test_the_live_model_router_is_nova_core() -> None:
    """Names collide across the two packages, so pin the real one by module."""
    from nova_core.router import ModelRouter

    assert ModelRouter.__module__ == "nova_core.router"


@pytest.mark.parametrize(
    "dead",
    ["core/task.py", "core/orchestrator.py", "core/router.py"],
)
def test_the_superseded_scaffolding_is_documented_where_it_still_exists(
    dead: str,
) -> None:
    """It may stay on disk, but DEVELOPMENT.md must say what it is.

    Deleting `core/` is Ahmed's call. Leaving it undocumented is how a future
    session mistakes it for the real thing.
    """
    path = PROJECT_ROOT / dead
    if not path.exists():
        pytest.skip(f"{dead} has been removed; nothing left to document")

    development = (PROJECT_ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")

    assert "core/" in development
    assert "SUPERSEDED" in development
