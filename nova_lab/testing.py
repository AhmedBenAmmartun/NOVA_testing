"""Allow-listed test execution for NOVA Lab."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .workspace import WorkspaceSafetyError


APPROVED_TEST_PROFILES: dict[str, tuple[str, ...]] = {
    "official": ("-m", "pytest", "-q", "tests"),
    "nova_lab": (
        "-m",
        "pytest",
        "-q",
        "tests/test_nova_lab_models.py",
        "tests/test_nova_lab_registry.py",
        "tests/test_nova_lab_workspace.py",
        "tests/test_nova_lab_testing.py",
        "tests/test_nova_lab_service.py",
        "tests/test_nova_lab_development_capability.py",
    ),
}


@dataclass(frozen=True, slots=True)
class TestRunResult:
    profile: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


class ApprovedTestRunner:
    """Run only named test profiles inside a verified lab/* Git worktree."""

    def __init__(
        self,
        *,
        labs_root: Path | str,
        python_executable: Path | str | None = None,
    ) -> None:
        self.labs_root = Path(labs_root).resolve()
        self.python_executable = str(python_executable or sys.executable)

    def run(
        self,
        *,
        profile: str,
        worktree: Path | str,
        timeout_seconds: int = 900,
    ) -> TestRunResult:
        if profile not in APPROVED_TEST_PROFILES:
            raise ValueError(
                f"Unknown NOVA Lab test profile '{profile}'. "
                f"Allowed: {', '.join(sorted(APPROVED_TEST_PROFILES))}"
            )

        cwd = Path(worktree).resolve()
        try:
            cwd.relative_to(self.labs_root)
        except ValueError as exc:
            raise WorkspaceSafetyError(
                f"Tests may only run under NOVA Labs root: {self.labs_root}"
            ) from exc

        self._verify_lab_worktree(cwd)

        args = APPROVED_TEST_PROFILES[profile]
        result = subprocess.run(
            [self.python_executable, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=max(1, min(int(timeout_seconds), 1800)),
        )
        return TestRunResult(
            profile=profile,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    @staticmethod
    def _verify_lab_worktree(cwd: Path) -> None:
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )
        if root_result.returncode != 0:
            raise WorkspaceSafetyError("Test target is not a Git worktree.")

        actual_root = Path(root_result.stdout.strip()).resolve()
        if actual_root != cwd:
            raise WorkspaceSafetyError(
                "Tests must run from the root of the NOVA Lab worktree."
            )

        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
        if not branch.startswith("lab/"):
            raise WorkspaceSafetyError(
                "Approved tests may run only from a checked-out lab/* branch."
            )
