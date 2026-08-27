"""Authoritative resolution of every NOVA school / vault filesystem root.

Any module that needs a vault, runtime, or class-knowledge path must call a
helper in this module instead of composing its own. Re-implementing a resolver
elsewhere creates a split-brain where the copy silently stops following this
module -- that already happened with ``course_sessions_root``, which was
defined both here and in ``nova_school.context`` until 2026-08-27.

This module also owns the archive policy: ``archive_roots()`` and
``is_archived_path()`` describe the historical vaults, superseded
repositories, old capture roots, and backup directories that must never be
treated as live input. Nothing here deletes, moves, or migrates those
locations -- they are preserved on disk and simply excluded from scans.

Safe defaults are always available; the environment overrides only relocate a
root, they never remove one.
"""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path


class ArchivedSourceError(RuntimeError):
    """Raised when a preserved archive/backup root is used as live input."""


# --- live roots -----------------------------------------------------------


def project_root() -> Path:
    """The NOVA source repository this module was loaded from."""
    return Path(__file__).resolve().parents[1]


def obsidian_vault_path() -> Path:
    configured = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "NOVA Vault").resolve()


def runtime_root() -> Path:
    """Local-only runtime state root, outside the vault and outside Git."""
    override = os.getenv("NOVA_RUNTIME_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    local = os.getenv("LOCALAPPDATA", "").strip()
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return (base / "NOVA").resolve()


def school_runtime_root() -> Path:
    path = runtime_root() / "School"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def class_knowledge_root() -> Path:
    """Vault subtree that owns per-course materials and derived session notes."""
    return obsidian_vault_path() / "Knowledge" / "Classes"


def course_materials_root(course_code: str) -> Path:
    return class_knowledge_root() / course_code / "Materials"


def course_sessions_root(course_code: str) -> Path:
    return class_knowledge_root() / course_code / "Sessions"


# --- archive policy -------------------------------------------------------

# Directory names that identify a preserved archive wherever they appear.
_ARCHIVE_DIR_NAMES = (
    ".nova-backups",
    "NOVA Vault CLEAN BUILD",
    "_Class Capture",
    "class_sessions",
    "install-backups",
)

# Timestamped backup directories created by NOVA's installer/checkpoint scripts.
_ARCHIVE_DIR_PATTERNS = (
    "AI-Agent-Before-Split-*",
    "NOVA-*-ARCHIVE-*",
    "NOVA-*-BACKUP-*",
    "NOVA-Safety-Backup-*",
)

_NORMALIZED_ARCHIVE_NAMES = frozenset(
    os.path.normcase(name) for name in _ARCHIVE_DIR_NAMES
)


def _matches_archive_name(name: str) -> bool:
    if os.path.normcase(name) in _NORMALIZED_ARCHIVE_NAMES:
        return True
    return any(fnmatch(name, pattern) for pattern in _ARCHIVE_DIR_PATTERNS)


def _extra_archive_roots() -> tuple[Path, ...]:
    """Additional archive roots from ``NOVA_ARCHIVE_ROOTS`` (os.pathsep list)."""
    raw = os.getenv("NOVA_ARCHIVE_ROOTS", "").strip()
    if not raw:
        return ()
    return tuple(
        Path(entry).expanduser().resolve()
        for entry in raw.split(os.pathsep)
        if entry.strip()
    )


def _named_archive_roots() -> tuple[Path, ...]:
    """Archive roots whose own directory name is too generic to match."""
    home = Path.home()
    return (
        home / "OneDrive" / "Desktop" / "AI Agent",
        home / "OneDrive" / "Desktop" / "Nova",
        *_extra_archive_roots(),
    )


def archive_roots() -> tuple[Path, ...]:
    """Every preserved archive/backup root NOVA knows about.

    Read-only by policy. Reported for auditing; never scanned, never written.
    """
    project = project_root()
    candidates: list[Path] = [
        Path.home() / "NOVA Vault CLEAN BUILD",
        obsidian_vault_path() / "Classes" / "_Class Capture",
        project / "class_sessions",
        project / ".nova-backups",
        runtime_root() / "install-backups",
        *_named_archive_roots(),
    ]

    try:
        siblings = sorted(project.parent.iterdir())
    except OSError:
        siblings = []
    for sibling in siblings:
        if sibling == project or not sibling.is_dir():
            continue
        if _matches_archive_name(sibling.name):
            candidates.append(sibling)

    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return tuple(unique)


def is_archived_path(path: str | Path) -> bool:
    """True when ``path`` is inside a preserved archive/backup location.

    Callers use this to refuse historical vaults, superseded repositories, old
    capture roots, and backup directories as live input.
    """
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False

    if any(_matches_archive_name(part) for part in resolved.parts):
        return True

    for root in _named_archive_roots():
        try:
            root = root.expanduser().resolve()
        except OSError:
            continue
        if resolved == root or resolved.is_relative_to(root):
            return True
    return False
