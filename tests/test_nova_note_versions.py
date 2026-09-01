"""Regenerating notes must not destroy the notes it replaces.

Post-class generation writes straight into the session folder, so a re-run
overwrites every file in place. That is about to matter: the 2026-08-31 COT3400
notes were written by a local fallback model after the Groq credential failed,
and they contain a definition fabricated from a mishearing. The moment that
credential is replaced and postprocess is re-run, the evidence of what NOVA got
wrong -- and of what changed -- disappears.

Section 19 of the knowledge directive asks for the opposite: NOVA should be able
to say *version 1 generated, correction discovered, version 2 regenerated*, and
preserve why.

So a regeneration archives the previous version beside the current one and
records what prompted it. The current files keep their names, because those are
what Ahmed opens in Obsidian -- versioning must not make the common case harder
to read.
"""

from __future__ import annotations

import json
from pathlib import Path

from nova_capture.note_versions import (
    archive_existing_notes,
    note_versions,
    versions_root,
)


def _session_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "11-53 - Class Session - abc123"
    folder.mkdir(parents=True)
    (folder / "Lecture.md").write_text("v1 lecture", encoding="utf-8")
    (folder / "Summary.md").write_text("v1 summary", encoding="utf-8")
    return folder


def test_a_first_generation_archives_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()

    assert archive_existing_notes(folder, reason="first run") is None


def test_regenerating_preserves_the_previous_version(tmp_path: Path) -> None:
    folder = _session_folder(tmp_path)

    archived = archive_existing_notes(folder, reason="Groq credential restored")

    assert archived is not None
    assert (archived / "Lecture.md").read_text(encoding="utf-8") == "v1 lecture"


def test_the_current_notes_keep_their_names(tmp_path: Path) -> None:
    """Ahmed opens `Lecture.md` in Obsidian. Versioning must not rename it."""
    folder = _session_folder(tmp_path)

    archive_existing_notes(folder, reason="rerun")
    (folder / "Lecture.md").write_text("v2 lecture", encoding="utf-8")

    assert (folder / "Lecture.md").read_text(encoding="utf-8") == "v2 lecture"


def test_the_archive_records_why_it_was_regenerated(tmp_path: Path) -> None:
    """"Why did this change?" must be answerable from the artifact itself."""
    folder = _session_folder(tmp_path)

    archived = archive_existing_notes(
        folder, reason="Groq credential restored; notes had been written by a local model"
    )

    manifest = json.loads(
        (archived / "version.json").read_text(encoding="utf-8")
    )
    assert "Groq credential restored" in manifest["reason"]
    assert manifest["version"] == 1
    assert manifest["archived_at"]


def test_versions_accumulate_rather_than_replace_each_other(tmp_path: Path) -> None:
    folder = _session_folder(tmp_path)

    archive_existing_notes(folder, reason="second run")
    (folder / "Lecture.md").write_text("v2 lecture", encoding="utf-8")
    archive_existing_notes(folder, reason="third run")

    versions = note_versions(folder)

    assert len(versions) == 2
    assert (versions[0] / "Lecture.md").read_text(encoding="utf-8") == "v1 lecture"
    assert (versions[1] / "Lecture.md").read_text(encoding="utf-8") == "v2 lecture"


def test_versions_are_listed_oldest_first(tmp_path: Path) -> None:
    folder = _session_folder(tmp_path)
    archive_existing_notes(folder, reason="a")
    (folder / "Lecture.md").write_text("v2", encoding="utf-8")
    archive_existing_notes(folder, reason="b")

    versions = note_versions(folder)
    manifests = [
        json.loads((path / "version.json").read_text(encoding="utf-8"))
        for path in versions
    ]

    assert [item["version"] for item in manifests] == [1, 2]


def test_the_archive_lives_beside_the_notes_not_among_them(tmp_path: Path) -> None:
    """A vault folder full of `Lecture (v1).md` clutter helps nobody."""
    folder = _session_folder(tmp_path)
    archive_existing_notes(folder, reason="rerun")

    top_level = {path.name for path in folder.iterdir() if path.is_file()}

    assert top_level == {"Lecture.md", "Summary.md"}
    assert versions_root(folder).is_dir()


def test_archived_versions_are_not_re_archived(tmp_path: Path) -> None:
    """The versions directory must not recurse into itself."""
    folder = _session_folder(tmp_path)
    archive_existing_notes(folder, reason="one")
    archive_existing_notes(folder, reason="two")

    nested = versions_root(folder) / "v1" / versions_root(folder).name

    assert not nested.exists()


def test_large_binaries_are_referenced_not_copied(tmp_path: Path) -> None:
    """A generated .pptx must not be duplicated into every version.

    Section 7: large artifacts stay file-backed. Copying a 32KB deck per
    regeneration is how a vault quietly bloats.
    """
    folder = _session_folder(tmp_path)
    (folder / "Presentation.pptx").write_bytes(b"PK\x03\x04" + b"0" * 4096)

    archived = archive_existing_notes(folder, reason="rerun")

    assert not (archived / "Presentation.pptx").exists()
    manifest = json.loads((archived / "version.json").read_text(encoding="utf-8"))
    assert "Presentation.pptx" in manifest["referenced_artifacts"]


def test_an_unwritable_archive_does_not_block_regeneration(tmp_path: Path) -> None:
    """Losing a version archive is bad. Losing the new notes is worse."""
    folder = _session_folder(tmp_path)
    # A file where the versions directory should go makes mkdir fail.
    versions_root(folder).write_text("not a directory", encoding="utf-8")

    assert archive_existing_notes(folder, reason="rerun") is None
    assert (folder / "Lecture.md").exists()
