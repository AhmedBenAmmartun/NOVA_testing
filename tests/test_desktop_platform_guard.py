"""Regression checks for safe cross-platform import structure in desktop tools."""

from __future__ import annotations

import ast
from pathlib import Path


def test_user32_is_loaded_lazily() -> None:
    source_path = Path(__file__).resolve().parents[1] / "tools" / "desktop.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    module_assignments = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    ]
    assert not any("windll" in ast.unparse(node) for node in module_assignments)

    helper = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_get_user32"
    )
    helper_source = ast.get_source_segment(source, helper) or ""
    assert 'sys.platform != "win32"' in helper_source
    assert "ctypes.windll.user32" in helper_source
