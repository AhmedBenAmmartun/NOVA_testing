from __future__ import annotations

import pytest

from nova_lab.workspace import GitWorkspace, WorkspaceSafetyError


def test_lab_branch_names_are_constrained() -> None:
    assert (
        GitWorkspace.validate_lab_branch_name("lab/granola-class-provider")
        == "lab/granola-class-provider"
    )

    for value in ("feature/x", "main", "lab/../main", "lab\\x", "lab/my branch"):
        with pytest.raises(WorkspaceSafetyError):
            GitWorkspace.validate_lab_branch_name(value)


def test_worktree_path_must_stay_under_labs_root(tmp_path) -> None:
    labs = tmp_path / "labs"
    labs.mkdir()

    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path)
    object.__setattr__(workspace, "labs_root", labs.resolve())

    assert workspace.require_lab_path(labs / "x") == (labs / "x").resolve()

    with pytest.raises(WorkspaceSafetyError):
        workspace.require_lab_path(tmp_path / "outside")


def test_base_refs_reject_option_and_revision_syntax() -> None:
    assert GitWorkspace.validate_base_ref("cd6e8d0") == "cd6e8d0"
    assert (
        GitWorkspace.validate_base_ref("safety/pre-nova-lab-20260904")
        == "safety/pre-nova-lab-20260904"
    )

    for value in (
        "",
        "--force",
        "../main",
        "main..other",
        "main@{1}",
        "main^",
        "main~1",
        "main:README.md",
        "bad ref",
    ):
        with pytest.raises(WorkspaceSafetyError):
            GitWorkspace.validate_base_ref(value)
