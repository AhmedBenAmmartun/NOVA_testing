"""Preserve the notes a regeneration replaces, and why it replaced them.

Post-class generation writes into the session folder in place, so re-running it
overwrote everything. That is about to cost something real: the 2026-08-31
COT3400 notes were produced by a local fallback model after the Groq credential
failed, and they contain a definition fabricated from a mishearing
("The condition GNRO >= N is a property stated in the lecture slide"). Re-running
after the credential is fixed would erase both the mistake and the fact that it
changed.

The shape here is deliberately boring:

* the CURRENT notes keep their filenames, because those are what Ahmed opens in
  Obsidian, and versioning must not make the common case harder to read;
* previous versions move into a single `_versions/vN/` folder beside them, not
  into `Lecture (v1).md` clutter spread through the vault;
* each version carries a manifest saying when it was archived and WHY, so
  "why did this change?" is answerable from the artifact rather than from
  someone's memory;
* large artifacts (a generated .pptx) are REFERENCED, not copied -- duplicating
  a deck per regeneration is how a vault quietly bloats.

Archiving is best-effort. Losing a version archive is bad; losing the new notes
because archiving failed would be worse, so every failure here degrades to
"no archive" and regeneration continues.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("nova.class_capture.note_versions")

VERSIONS_DIRNAME = "_versions"
MANIFEST_NAME = "version.json"

#: Copied into an archived version. Anything else -- decks, media, binaries --
#: is recorded by name only.
_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json"})


def versions_root(session_folder: Path | str) -> Path:
    return Path(session_folder) / VERSIONS_DIRNAME


def note_versions(session_folder: Path | str) -> tuple[Path, ...]:
    """Archived versions, oldest first."""
    root = versions_root(session_folder)
    if not root.is_dir():
        return ()
    versions = [path for path in root.iterdir() if path.is_dir()]
    return tuple(sorted(versions, key=_version_number))


def _version_number(path: Path) -> int:
    try:
        return int(path.name.lstrip("v"))
    except ValueError:
        return 0


def archive_existing_notes(
    session_folder: Path | str,
    *,
    reason: str,
) -> Path | None:
    """Move the current notes into `_versions/vN/`. Returns that folder.

    ``None`` means nothing was archived -- either this is a first generation
    with no previous notes, or archiving failed and regeneration should carry
    on regardless.
    """
    folder = Path(session_folder)
    try:
        if not folder.is_dir():
            return None

        current = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.name != MANIFEST_NAME
        ]
        if not current:
            return None

        root = versions_root(folder)
        root.mkdir(parents=True, exist_ok=True)
        version = len(note_versions(folder)) + 1
        destination = root / f"v{version}"
        destination.mkdir(parents=True, exist_ok=True)

        copied: list[str] = []
        referenced: list[str] = []
        for path in current:
            if path.suffix.lower() in _TEXT_SUFFIXES:
                shutil.copy2(path, destination / path.name)
                copied.append(path.name)
            else:
                # Large artifacts stay file-backed and are referenced by name.
                referenced.append(path.name)

        (destination / MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "version": version,
                    "archived_at": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "reason": reason,
                    "files": sorted(copied),
                    "referenced_artifacts": sorted(referenced),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return destination

    except Exception:
        # Never let a bookkeeping failure cost the regeneration itself.
        logger.exception("could not archive previous notes; regenerating anyway")
        return None
