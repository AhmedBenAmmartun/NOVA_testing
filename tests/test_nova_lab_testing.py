from __future__ import annotations

from types import SimpleNamespace

import pytest

from nova_lab.testing import APPROVED_TEST_PROFILES, ApprovedTestRunner
from nova_lab.workspace import WorkspaceSafetyError


def test_only_named_profiles_are_accepted(tmp_path) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)
    runner = ApprovedTestRunner(labs_root=labs)

    with pytest.raises(ValueError):
        runner.run(profile="pytest whatever.py", worktree=worktree)


def test_runner_uses_fixed_profile_without_shell(tmp_path, monkeypatch) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return SimpleNamespace(returncode=0, stdout=str(worktree), stderr="")
        if args[:3] == ["git", "branch", "--show-current"]:
            return SimpleNamespace(returncode=0, stdout="lab/test\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("nova_lab.testing.subprocess.run", fake_run)

    runner = ApprovedTestRunner(
        labs_root=labs,
        python_executable="python-test",
    )
    result = runner.run(profile="official", worktree=worktree)

    test_args, test_kwargs = calls[-1]
    assert test_args == ["python-test", *APPROVED_TEST_PROFILES["official"]]
    assert all(kwargs["shell"] is False for _, kwargs in calls)
    assert test_kwargs["cwd"] == worktree.resolve()
    assert result.passed


def test_runner_rejects_worktree_outside_labs_root(tmp_path) -> None:
    labs = tmp_path / "labs"
    labs.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    runner = ApprovedTestRunner(labs_root=labs)

    with pytest.raises(WorkspaceSafetyError):
        runner.run(profile="official", worktree=outside)


def test_runner_rejects_non_git_folder_inside_labs_root(tmp_path, monkeypatch) -> None:
    labs = tmp_path / "labs"
    folder = labs / "not-a-worktree"
    folder.mkdir(parents=True)

    def fake_run(args, **kwargs):
        return SimpleNamespace(returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr("nova_lab.testing.subprocess.run", fake_run)

    runner = ApprovedTestRunner(labs_root=labs)
    with pytest.raises(WorkspaceSafetyError, match="not a Git worktree"):
        runner.run(profile="official", worktree=folder)


def test_runner_rejects_non_lab_branch(tmp_path, monkeypatch) -> None:
    labs = tmp_path / "labs"
    worktree = labs / "feature"
    worktree.mkdir(parents=True)

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return SimpleNamespace(returncode=0, stdout=str(worktree), stderr="")
        if args[:3] == ["git", "branch", "--show-current"]:
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        raise AssertionError("pytest must not run from a non-lab branch")

    monkeypatch.setattr("nova_lab.testing.subprocess.run", fake_run)

    runner = ApprovedTestRunner(labs_root=labs)
    with pytest.raises(WorkspaceSafetyError, match="lab/"):
        runner.run(profile="official", worktree=worktree)
