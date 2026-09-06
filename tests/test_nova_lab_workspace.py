from __future__ import annotations

from pathlib import Path

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

def test_resolve_commit_uses_commit_peeling_and_validated_ref(tmp_path, monkeypatch) -> None:
    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path.resolve())
    labs = tmp_path / "labs"
    labs.mkdir()
    object.__setattr__(workspace, "labs_root", labs.resolve())

    calls = []

    def fake_git(self, *args, cwd=None):
        calls.append((args, cwd))
        return "a" * 40 + "\n"

    monkeypatch.setattr(GitWorkspace, "_git", fake_git)

    assert workspace.resolve_commit("lab/example") == "a" * 40
    assert calls == [(("rev-parse", "--verify", "lab/example^{commit}"), None)]


def test_verify_existing_lab_worktree_requires_exact_root_and_matching_branch(
    tmp_path, monkeypatch
) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)

    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path.resolve())
    object.__setattr__(workspace, "labs_root", labs.resolve())

    def fake_git(self, *args, cwd=None):
        if args == ("rev-parse", "--show-toplevel"):
            return str(worktree) + "\n"
        if args == ("rev-parse", "--git-common-dir"):
            return str(tmp_path / ".git") + "\n"
        if args == ("branch", "--show-current"):
            return "lab/example\n"
        raise AssertionError(args)

    monkeypatch.setattr(GitWorkspace, "_git", fake_git)

    assert (
        workspace.verify_existing_lab_worktree(
            worktree,
            expected_branch="lab/example",
        )
        == worktree.resolve()
    )

    with pytest.raises(WorkspaceSafetyError, match="branch mismatch"):
        workspace.verify_existing_lab_worktree(
            worktree,
            expected_branch="lab/other",
        )


def test_verify_existing_lab_worktree_rejects_nested_path(
    tmp_path, monkeypatch
) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    nested = worktree / "src"
    nested.mkdir(parents=True)

    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path.resolve())
    object.__setattr__(workspace, "labs_root", labs.resolve())

    def fake_git(self, *args, cwd=None):
        if args == ("rev-parse", "--show-toplevel"):
            return str(worktree) + "\n"
        raise AssertionError(args)

    monkeypatch.setattr(GitWorkspace, "_git", fake_git)

    with pytest.raises(WorkspaceSafetyError, match="worktree root"):
        workspace.verify_existing_lab_worktree(nested)


def test_verify_existing_lab_worktree_rejects_different_git_repository(
    tmp_path, monkeypatch
) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)

    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path.resolve())
    object.__setattr__(workspace, "labs_root", labs.resolve())

    def fake_git(self, *args, cwd=None):
        cwd = Path(cwd).resolve() if cwd is not None else tmp_path.resolve()

        if args == ("rev-parse", "--show-toplevel"):
            return str(worktree) + "\n"
        if args == ("rev-parse", "--git-common-dir"):
            if cwd == worktree.resolve():
                return str(worktree / ".git") + "\n"
            return str(tmp_path / ".git") + "\n"
        if args == ("branch", "--show-current"):
            return "lab/example\n"
        raise AssertionError(args)

    monkeypatch.setattr(GitWorkspace, "_git", fake_git)

    with pytest.raises(WorkspaceSafetyError, match="same NOVA Git repository"):
        workspace.verify_existing_lab_worktree(
            worktree,
            expected_branch="lab/example",
        )


def test_is_ancestor_uses_fixed_git_arguments(tmp_path, monkeypatch) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)

    workspace = object.__new__(GitWorkspace)
    object.__setattr__(workspace, "repo_root", tmp_path.resolve())
    object.__setattr__(workspace, "labs_root", labs.resolve())

    monkeypatch.setattr(
        GitWorkspace,
        "resolve_commit",
        lambda self, ref: "a" * 40,
    )

    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr("nova_lab.workspace.subprocess.run", fake_run)

    assert workspace.is_ancestor("HEAD", cwd=worktree) is True
    args, kwargs = calls[0]
    assert args == [
        "git",
        "merge-base",
        "--is-ancestor",
        "a" * 40,
        "HEAD",
    ]
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == worktree.resolve()
