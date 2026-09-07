from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .failed_approaches import FailedApproachIndex
from .freshness import DOC_POLICY, FILE_POLICY, GIT_STATUS_POLICY, TEST_POLICY, apply_freshness
from .models import Fact, FactStatus, ProjectState, ProvenanceRef, utc_now_iso
from .provenance import file_provenance, observation_provenance


def _normalize_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned or "unknown-project"


def _run_git(root: Path, *args: str) -> tuple[bool, str]:
    """Run one fixed read-only Git command with no shell and a short timeout."""
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    if completed.returncode != 0:
        return False, completed.stderr.strip()
    # Preserve leading status columns (e.g. " M README.md") while trimming
    # only line endings. `str.strip()` corrupts porcelain status filenames.
    return True, completed.stdout.rstrip("\r\n")


def _fact(
    key: str,
    value: Any,
    *,
    status: FactStatus,
    provenance,
    freshness_policy=None,
    confidence: float = 1.0,
    note: str = "",
) -> Fact:
    fact = Fact(
        key=key,
        value=value,
        status=status,
        provenance=tuple(provenance),
        confidence=confidence,
        note=note,
    )
    return apply_freshness(fact, freshness_policy) if freshness_policy else fact


def _read_first_heading(path: Path) -> str | None:
    try:
        for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            text = raw.strip()
            if text.startswith("# "):
                return text[2:].strip()
    except OSError:
        return None
    return None


def _literal_keyword(call: ast.Call, name: str, default: Any = None) -> Any:
    for keyword in call.keywords:
        if keyword.arg == name:
            try:
                return ast.literal_eval(keyword.value)
            except (ValueError, TypeError, SyntaxError):
                return default
    return default


def _capability_snapshot(root: Path) -> tuple[list[dict[str, Any]], FactStatus, tuple]:
    path = root / "nova_os" / "capability_definitions.py"
    if not path.is_file():
        return [], FactStatus.UNKNOWN, ()
    provenance = (file_provenance(path, root=root, source_kind="code"),)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError):
        return [], FactStatus.UNKNOWN, provenance

    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_definition = (
            isinstance(fn, ast.Name) and fn.id == "CapabilityDefinition"
        ) or (
            isinstance(fn, ast.Attribute) and fn.attr == "CapabilityDefinition"
        )
        if not is_definition:
            continue
        capability_id = _literal_keyword(node, "capability_id", "")
        if not isinstance(capability_id, str) or not capability_id:
            continue
        found.append(
            {
                "capability_id": capability_id,
                "name": _literal_keyword(node, "name", ""),
                "risk": _literal_keyword(node, "risk", "read_only"),
                "default_active": bool(_literal_keyword(node, "default_active", False)),
                "locked_active": bool(_literal_keyword(node, "locked_active", False)),
            }
        )
    found.sort(key=lambda item: str(item["capability_id"]))
    return found, FactStatus.VERIFIED if found else FactStatus.UNKNOWN, provenance


def _discover_named_docs(
    root: Path,
    *,
    filename_terms: tuple[str, ...],
    max_items: int = 20,
) -> tuple[dict[str, Any], ...]:
    docs = root / "docs"
    candidates = []
    if docs.is_dir():
        candidates.extend(sorted(docs.rglob("*.md")))
    output: list[dict[str, Any]] = []
    for path in candidates:
        lowered = path.name.casefold()
        if not any(term in lowered for term in filename_terms):
            continue
        output.append(
            {
                "name": path.stem,
                "source": path.relative_to(root).as_posix(),
                "provenance": file_provenance(
                    path, root=root, source_kind="documentation"
                ).as_dict(),
            }
        )
        if len(output) >= max_items:
            break
    return tuple(output)


def _default_test_evidence_path() -> Path:
    local = os.getenv("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "NOVA" / "CoreIntelligence" / "last-verification.json"
    return Path.home() / ".nova" / "core-intelligence" / "last-verification.json"


def _verification_evidence(root: Path, head: str) -> Fact:
    configured = os.getenv("NOVA_CORE_TEST_EVIDENCE", "").strip()
    path = (
        Path(configured).expanduser()
        if configured
        else _default_test_evidence_path()
    )
    if not path.is_file():
        return Fact(
            key="latest_verified_tests",
            value=None,
            status=FactStatus.UNKNOWN,
            note="trusted local test-evidence file does not exist",
        )
    file_prov = file_provenance(path, root=root, source_kind="test")
    provenance = (file_prov,)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Fact(
            key="latest_verified_tests",
            value=None,
            status=FactStatus.UNKNOWN,
            provenance=provenance,
            note="test-evidence file is unreadable or invalid",
        )

    verified_at = str(raw.get("verified_at", "")).strip()
    if verified_at:
        provenance = (
            ProvenanceRef(
                source_kind=file_prov.source_kind,
                source=file_prov.source,
                observed_at=verified_at,
                digest=file_prov.digest,
                note=(file_prov.note + "; evidence timestamp").strip("; "),
            ),
        )

    evidence_head = str(raw.get("commit_sha", ""))
    passed = bool(raw.get("passed", False))
    value = {
        "commit_sha": evidence_head,
        "passed": passed,
        "gates": raw.get("gates", []),
        "verified_at": raw.get("verified_at"),
    }
    status = FactStatus.VERIFIED if passed and evidence_head == head else FactStatus.STALE
    fact = Fact(
        key="latest_verified_tests",
        value=value,
        status=status,
        provenance=provenance,
        note=(
            "evidence matches current HEAD"
            if status is FactStatus.VERIFIED
            else "test evidence does not match current HEAD"
        ),
    )
    return apply_freshness(fact, TEST_POLICY)


class ProjectStateBuilder:
    """Generate a read-only ProjectState from current repository evidence."""

    def __init__(self, project_root: Path | str | None = None) -> None:
        self.project_root = Path(
            project_root or Path(__file__).resolve().parents[1]
        ).expanduser().resolve()

    def build(self) -> ProjectState:
        generated_at = utc_now_iso()
        requested_root = self.project_root

        ok_root, root_text = _run_git(requested_root, "rev-parse", "--show-toplevel")
        if ok_root and root_text:
            repo_root = Path(root_text).resolve()
            root_status = FactStatus.VERIFIED
            root_prov = (
                observation_provenance(
                    "git",
                    "git rev-parse --show-toplevel",
                    root_text,
                ),
            )
        else:
            repo_root = requested_root
            root_status = FactStatus.DERIVED
            root_prov = (
                observation_provenance(
                    "configuration",
                    "ProjectStateBuilder.project_root",
                    str(requested_root),
                    note="Git root unavailable; using configured project root",
                ),
            )

        readme = repo_root / "README.md"
        heading = _read_first_heading(readme) if readme.is_file() else None
        project_name = heading or repo_root.name
        name_prov = (
            (file_provenance(readme, root=repo_root, source_kind="documentation"),)
            if heading
            else root_prov
        )
        project_id = _normalize_id(project_name)

        ok_branch, branch = _run_git(repo_root, "branch", "--show-current")
        ok_head, head = _run_git(repo_root, "rev-parse", "HEAD")
        ok_status, status_text = _run_git(repo_root, "status", "--short")
        ok_remote, remote = _run_git(repo_root, "remote", "get-url", "testing")

        git_status_prov = (
            observation_provenance("git", "git status --short", status_text),
        ) if ok_status else ()
        branch_prov = (
            observation_provenance("git", "git branch --show-current", branch),
        ) if ok_branch else ()
        head_prov = (
            observation_provenance("git", "git rev-parse HEAD", head),
        ) if ok_head else ()
        remote_prov = (
            observation_provenance("git", "git remote get-url testing", remote),
        ) if ok_remote else ()

        changed_files = []
        if ok_status:
            for raw in status_text.splitlines():
                if len(raw) >= 4:
                    changed_files.append(raw[3:].strip())

        identity = {
            "name": _fact(
                "project_name",
                project_name,
                status=FactStatus.VERIFIED if heading else FactStatus.DERIVED,
                provenance=name_prov,
                freshness_policy=DOC_POLICY if heading else FILE_POLICY,
            ),
            "root": _fact(
                "project_root",
                str(repo_root),
                status=root_status,
                provenance=root_prov,
                freshness_policy=GIT_STATUS_POLICY if ok_root else FILE_POLICY,
            ),
        }

        repository = {
            "branch": _fact(
                "git_branch",
                branch if ok_branch and branch else None,
                status=FactStatus.VERIFIED if ok_branch and branch else FactStatus.UNKNOWN,
                provenance=branch_prov,
                freshness_policy=GIT_STATUS_POLICY if branch_prov else None,
            ),
            "head": _fact(
                "git_head",
                head if ok_head else None,
                status=FactStatus.VERIFIED if ok_head else FactStatus.UNKNOWN,
                provenance=head_prov,
                freshness_policy=GIT_STATUS_POLICY if head_prov else None,
            ),
            "dirty": _fact(
                "git_dirty",
                bool(status_text) if ok_status else None,
                status=FactStatus.VERIFIED if ok_status else FactStatus.UNKNOWN,
                provenance=git_status_prov,
                freshness_policy=GIT_STATUS_POLICY if git_status_prov else None,
            ),
            "changed_files": _fact(
                "git_changed_files",
                changed_files if ok_status else None,
                status=FactStatus.VERIFIED if ok_status else FactStatus.UNKNOWN,
                provenance=git_status_prov,
                freshness_policy=GIT_STATUS_POLICY if git_status_prov else None,
            ),
            "testing_remote": _fact(
                "testing_remote",
                remote if ok_remote else None,
                status=FactStatus.VERIFIED if ok_remote else FactStatus.UNKNOWN,
                provenance=remote_prov,
                freshness_policy=FILE_POLICY if remote_prov else None,
                note="local Git config only; no network call",
            ),
        }

        milestone_value = None
        milestone_status = FactStatus.UNKNOWN
        milestone_note = "branch did not identify a known NOVA milestone"
        if branch:
            lowered = branch.casefold()
            if "nova-a1" in lowered or "core-intelligence" in lowered:
                milestone_value = "A1 Core Intelligence"
                milestone_status = FactStatus.DERIVED
                milestone_note = "derived from verified branch name"
            elif "nova-a0" in lowered or "verification-contracts" in lowered:
                milestone_value = "A0 Verification Contracts"
                milestone_status = FactStatus.DERIVED
                milestone_note = "derived from verified branch name"
            elif lowered.startswith("lab/"):
                milestone_value = branch
                milestone_status = FactStatus.DERIVED
                milestone_note = "derived from verified Lab branch name"

        active_work = {
            "milestone": _fact(
                "milestone",
                milestone_value,
                status=milestone_status,
                provenance=branch_prov,
                freshness_policy=GIT_STATUS_POLICY if branch_prov else None,
                confidence=0.95 if milestone_value else 0.0,
                note=milestone_note,
            ),
        }

        capabilities, cap_status, cap_prov = _capability_snapshot(repo_root)
        systems = {
            "capabilities": _fact(
                "capabilities",
                capabilities if capabilities else None,
                status=cap_status,
                provenance=cap_prov,
                freshness_policy=FILE_POLICY if cap_prov else None,
            ),
        }

        issues = _discover_named_docs(
            repo_root,
            filename_terms=("issue", "bug", "blocker"),
        )
        decisions = _discover_named_docs(
            repo_root,
            filename_terms=("adr", "decision"),
        )

        failed_index = FailedApproachIndex(repo_root)
        failed = tuple(item.as_dict() for item in failed_index.scan())

        tests = {
            "latest": _verification_evidence(
                repo_root,
                head if ok_head else "",
            )
        }

        continuity = {
            "source_priority": Fact(
                key="source_priority",
                value=[
                    "current repository/files",
                    "Git state",
                    "tests/logs/runtime",
                    "current conversation",
                    "project documentation",
                    "older history",
                ],
                status=FactStatus.DERIVED,
                note="A1 operating contract; repository/runtime evidence outranks documentation",
            ),
            "shadow_mode": Fact(
                key="shadow_mode",
                value=True,
                status=FactStatus.VERIFIED,
                provenance=(
                    observation_provenance(
                        "configuration",
                        "A1 default",
                        "shadow_mode=true",
                    ),
                ),
                note="A1 project packet is advisory until graduation and trusted opt-in",
            ),
        }

        conflicts: list[str] = []
        if repository["dirty"].status is FactStatus.VERIFIED and repository["dirty"].value:
            conflicts.append("working tree is dirty; any documentation claiming a clean checkpoint may be stale")
        if tests["latest"].status in {FactStatus.UNKNOWN, FactStatus.STALE}:
            conflicts.append("current HEAD does not have matching trusted test evidence available to ProjectState")

        return ProjectState(
            schema_version=1,
            project_id=project_id,
            generated_at=generated_at,
            identity=identity,
            repository=repository,
            active_work=active_work,
            systems=systems,
            issues=issues,
            decisions=decisions,
            tests=tests,
            failed_approaches=failed,
            continuity=continuity,
            conflicts=tuple(conflicts),
        )
