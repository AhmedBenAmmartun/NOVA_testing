"""Constrained Git/worktree operations for NOVA Lab."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class WorkspaceSafetyError(RuntimeError):
    """Raised when a requested workspace escapes NOVA Lab boundaries."""


_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


@dataclass(frozen=True, slots=True)
class GitWorkspace:
    repo_root: Path
    labs_root: Path

    def __init__(self, repo_root: Path | str, labs_root: Path | str) -> None:
        object.__setattr__(self, "repo_root", Path(repo_root).resolve())
        object.__setattr__(self, "labs_root", Path(labs_root).resolve())
        self._verify_repo_root()

    @staticmethod
    def validate_lab_branch_name(branch: str) -> str:
        cleaned = str(branch).strip()
        if not cleaned.startswith("lab/"):
            raise WorkspaceSafetyError("NOVA Lab branches must start with 'lab/'.")
        if any(token in cleaned for token in ("..", "\\", " ", "~", "^", ":")):
            raise WorkspaceSafetyError("Unsafe NOVA Lab branch name.")
        return cleaned

    @staticmethod
    def validate_base_ref(base_ref: str) -> str:
        cleaned = str(base_ref).strip()
        forbidden = ("..", "//", "@{", "\\", ":", "?", "*", "[", "^", "~")
        if not cleaned or cleaned.startswith("-"):
            raise WorkspaceSafetyError("Unsafe or empty Git base ref.")
        if not _SAFE_REF.fullmatch(cleaned):
            raise WorkspaceSafetyError("Unsafe Git base ref.")
        if any(token in cleaned for token in forbidden):
            raise WorkspaceSafetyError("Unsafe Git base ref.")
        if cleaned.endswith(("/", ".", ".lock")):
            raise WorkspaceSafetyError("Unsafe Git base ref.")
        return cleaned

    def require_lab_path(self, path: Path | str) -> Path:
        candidate = Path(path).resolve()
        try:
            candidate.relative_to(self.labs_root)
        except ValueError as exc:
            raise WorkspaceSafetyError(
                f"Worktree must stay under NOVA Labs root: {self.labs_root}"
            ) from exc
        return candidate

    def head(self, *, cwd: Path | str | None = None) -> str:
        return self._git("rev-parse", "HEAD", cwd=cwd).strip()

    def current_branch(self, *, cwd: Path | str | None = None) -> str:
        return self._git("branch", "--show-current", cwd=cwd).strip()

    def status_short(self, *, cwd: Path | str | None = None) -> str:
        return self._git("status", "--short", cwd=cwd)

    def is_clean(self, *, cwd: Path | str | None = None) -> bool:
        return not self.status_short(cwd=cwd).strip()

    def list_worktrees(self) -> str:
        return self._git("worktree", "list", "--porcelain")

    def resolve_commit(self, base_ref: str) -> str:
        """Resolve a validated ref to an exact commit SHA."""
        base_ref = self.validate_base_ref(base_ref)
        return self._git(
            "rev-parse",
            "--verify",
            f"{base_ref}^{{commit}}",
        ).strip()

    def git_common_dir(self, *, cwd: Path | str | None = None) -> Path:
        """Return the normalized common Git directory for a repo/worktree."""
        base = Path(cwd).resolve() if cwd is not None else self.repo_root
        raw = self._git("rev-parse", "--git-common-dir", cwd=base).strip()
        path = Path(raw)
        if not path.is_absolute():
            path = base / path
        return path.resolve()

    def is_ancestor(
        self,
        ancestor_ref: str,
        *,
        cwd: Path | str,
    ) -> bool:
        """Return whether a validated NOVA commit is an ancestor of HEAD."""
        ancestor_sha = self.resolve_commit(ancestor_ref)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor_sha, "HEAD"],
            cwd=Path(cwd).resolve(),
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Git ancestry check failed: {message}")

    def verify_existing_lab_worktree(
        self,
        path: Path | str,
        *,
        expected_branch: str | None = None,
    ) -> Path:
        """Verify an existing path is exactly a lab/* worktree root."""
        candidate = self.require_lab_path(path)
        if not candidate.is_dir():
            raise WorkspaceSafetyError(f"Lab worktree does not exist: {candidate}")

        actual = Path(
            self._git("rev-parse", "--show-toplevel", cwd=candidate).strip()
        ).resolve()
        if actual != candidate:
            raise WorkspaceSafetyError(
                "Registered Lab worktree paths must point to the Git worktree root."
            )

        candidate_common = os.path.normcase(str(self.git_common_dir(cwd=candidate)))
        nova_common = os.path.normcase(str(self.git_common_dir(cwd=self.repo_root)))
        if candidate_common != nova_common:
            raise WorkspaceSafetyError(
                "Registered Lab worktrees must belong to the same NOVA Git repository."
            )

        branch = self.current_branch(cwd=candidate)
        self.validate_lab_branch_name(branch)

        if expected_branch is not None:
            expected = self.validate_lab_branch_name(expected_branch)
            if branch != expected:
                raise WorkspaceSafetyError(
                    f"Lab worktree branch mismatch: expected {expected}, got {branch}."
                )

        return candidate

    def create_lab_worktree(
        self,
        *,
        branch: str,
        path: Path | str,
        base_ref: str,
    ) -> Path:
        branch = self.validate_lab_branch_name(branch)
        base_ref = self.validate_base_ref(base_ref)
        destination = self.require_lab_path(path)
        if destination.exists():
            raise WorkspaceSafetyError(f"Worktree path already exists: {destination}")

        # Verify the supplied ref resolves to a commit before creating folders
        # or asking worktree-add to interpret it.
        self.resolve_commit(base_ref)

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._git(
            "worktree",
            "add",
            "-b",
            branch,
            str(destination),
            base_ref,
        )
        return destination

    def _verify_repo_root(self) -> None:
        actual = Path(
            self._git("rev-parse", "--show-toplevel", cwd=self.repo_root).strip()
        ).resolve()
        if actual != self.repo_root:
            raise WorkspaceSafetyError(
                f"Expected Git root {self.repo_root}, got {actual}"
            )

    def _git(self, *args: str, cwd: Path | str | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(cwd).resolve() if cwd is not None else self.repo_root,
            capture_output=True,
            text=True,
            shell=False,
            timeout=120,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"Git command failed: {message}")
        return result.stdout
