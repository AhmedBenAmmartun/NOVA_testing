"""Contract tests for the authoritative NOVA path resolver.

These lock in two things the 2026-08-27 path audit found broken or missing:
a single owner for every school/vault root, and an archive policy that keeps
preserved backups out of live input.

Scope: this file covers only what the Path Authority checkpoint itself ships.
Integration tests for the archive guard inside ``nova_knowledge.discovery``
are deliberately NOT here -- that package is unfinished, untracked Course
Knowledge work, and importing it would make this file uncollectable on a
fresh checkout. Those three cases are deferred to the Course Knowledge
checkpoint; see the note above ``test_archived_source_error_is_exported``.
"""

from pathlib import Path

import pytest

from nova_capture import class_budget, control, storage
from nova_school import context as context_module
from nova_school import paths, registry
from nova_school.organizer import SchoolMaterialOrganizer
from nova_school.paths import ArchivedSourceError, is_archived_path


# --- single owner ---------------------------------------------------------


def test_context_reexports_the_authoritative_sessions_resolver() -> None:
    assert context_module.course_sessions_root is paths.course_sessions_root


def test_context_does_not_redefine_the_sessions_resolver() -> None:
    source = Path(context_module.__file__).read_text(encoding="utf-8")
    assert "def course_sessions_root" not in source


def test_vault_roots_follow_the_configured_vault(monkeypatch, tmp_path) -> None:
    vault = tmp_path / "vault"
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    expected = vault.resolve() / "Knowledge" / "Classes"
    assert paths.class_knowledge_root() == expected
    assert paths.course_materials_root("CEN4065") == expected / "CEN4065" / "Materials"
    assert paths.course_sessions_root("CEN4065") == expected / "CEN4065" / "Sessions"
    assert context_module.course_sessions_root("CEN4065") == expected / "CEN4065" / "Sessions"


def test_runtime_roots_follow_the_runtime_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("NOVA_RUNTIME_ROOT", str(tmp_path / "runtime"))
    assert paths.runtime_root() == (tmp_path / "runtime").resolve()
    assert paths.school_runtime_root() == (tmp_path / "runtime" / "School").resolve()
    assert registry.default_registry_path() == (
        tmp_path / "runtime" / "School" / "courses.json"
    ).resolve()


def test_capture_control_and_budget_follow_the_capture_root(monkeypatch, tmp_path) -> None:
    """The control/lock and budget files must never strand in the old root."""
    monkeypatch.setenv("NOVA_CLASS_CAPTURE_ROOT", str(tmp_path / "capture"))
    capture_root = storage.default_capture_root()
    assert capture_root == (tmp_path / "capture").resolve()
    assert control.control_root() == capture_root / "_control"
    assert class_budget.ClassCloudUsageBudget._usage_path() == (
        capture_root / "_control" / "class_cloud_usage.json"
    )


# --- archive policy -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        ".nova-backups",
        "NOVA Vault CLEAN BUILD",
        "_Class Capture",
        "class_sessions",
        "install-backups",
        "AI-Agent-Before-Split-20260808-101158",
        "NOVA-CLASS-V134-BACKUP-20260823-130512",
        "NOVA-Safety-Backup-20260801-141034",
        "NOVA-DETACHED-DASHBOARD-ARCHIVE-20260815-173650",
    ],
)
def test_archive_directory_names_are_excluded(tmp_path, name: str) -> None:
    assert is_archived_path(tmp_path / name / "material.pdf")


def test_superseded_repository_roots_are_excluded(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert is_archived_path(tmp_path / "OneDrive" / "Desktop" / "AI Agent" / "agent.py")
    assert is_archived_path(tmp_path / "OneDrive" / "Desktop" / "Nova" / "nova")


def test_extra_archive_roots_come_from_the_environment(monkeypatch, tmp_path) -> None:
    extra = tmp_path / "some-old-copy"
    monkeypatch.setenv("NOVA_ARCHIVE_ROOTS", str(extra))
    assert is_archived_path(extra / "slides.pptx")


def test_live_vault_material_is_not_archived(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    live = paths.course_materials_root("COP3350") / "Readings" / "L01.pdf"
    assert not is_archived_path(live)


def test_vault_tracker_backups_folder_is_not_archived(tmp_path) -> None:
    """'Tracker Backups' is live vault content, not a NOVA backup root."""
    assert not is_archived_path(tmp_path / "NOVA" / "Tracker Backups" / "note.md")


# --- archive exclusion enforced by tracked consumers ----------------------

# DEFERRED to the Course Knowledge checkpoint (needs nova_knowledge, which is
# not shipped here): scanning an archive root is refused, a recursive scan
# skips nested archives, and allow_archived=True still permits a deliberate
# import. Those exercise nova_knowledge.discovery.iter_candidate_files and
# belong with that package's own tests.


def test_archived_source_error_is_exported_by_the_path_module() -> None:
    """The refusal error is owned by the resolver, not by any consumer.

    Consumers raise it; the type must live here so a new consumer can adopt
    the policy without redefining its own error and re-splitting ownership.
    """
    assert paths.ArchivedSourceError is ArchivedSourceError
    assert issubclass(ArchivedSourceError, RuntimeError)


def test_organizer_refuses_to_copy_out_of_an_archive(tmp_path) -> None:
    archive = tmp_path / "NOVA Vault CLEAN BUILD"
    archive.mkdir()
    source = archive / "lecture.pdf"
    source.write_bytes(b"x")

    organizer = SchoolMaterialOrganizer()
    organizer.audit_path = tmp_path / "audit.jsonl"
    result = organizer.organize(source)

    assert result.status == "archived_source"
    assert result.destination is None
