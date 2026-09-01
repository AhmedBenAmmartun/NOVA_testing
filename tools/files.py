import asyncio
import os
from pathlib import Path
from datetime import datetime

from livekit.agents import RunContext, function_tool

from .common import (
    COURSE_MATERIALS_DENIED,
    DEFAULT_DESKTOP_PATH,
    NOTES_PATH,
    SANDBOX_DENIED,
    SAFE_DIRS,
    logger,
    resolve_course_material_path,
    resolve_safe_path,
)


MAX_COURSE_MATERIAL_CHARS = 15_000
MAX_FILE_SEARCH_RESULTS = 12
MAX_FILE_SEARCH_DEPTH = 6
SUPPORTED_COURSE_EXTENSIONS = {".pdf", ".txt", ".md"}
SKIPPED_SEARCH_DIRS = {
    ".git",
    ".obsidian",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
}
KNOWN_FOLDER_NAMES = {
    "desktop": "Desktop",
    "documents": "Documents",
    "downloads": "Downloads",
    "pictures": "Pictures",
    "music": "Music",
    "videos": "Videos",
}

#: What `open_file_or_folder` is allowed to hand to `os.startfile`.
#:
#: `os.startfile` runs the Windows shell's default verb. For a document that
#: means *view*; for `.exe`, `.bat`, `.vbs`, `.lnk` and friends it means
#: *execute*. Before this list existed, `web_download` (registered REVERSIBLE,
#: so it never prompts) into `~/Downloads` -- a SAFE_DIR -- followed by
#: `open_file_or_folder` was unconfirmed code execution, using two tools that
#: are both active by default. `create_file` to the Desktop did the same with
#: no network at all.
#:
#: This is an ALLOWLIST on purpose. A denylist loses to whatever extension
#: Windows decides to make executable next, and to the ones nobody remembered
#: (`.pif`, `.wsh`, `.application`, `.msp`).
LAUNCHABLE_SUFFIXES = frozenset(
    {
        # documents
        ".pdf", ".txt", ".md", ".rtf", ".csv", ".tsv", ".log", ".json", ".xml",
        ".doc", ".docx", ".odt", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp",
        ".epub",
        # images
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff",
        ".heic", ".ico",
        # audio / video
        ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv",
    }
)


def is_launchable(path: Path) -> bool:
    """True only for suffixes that Windows opens rather than runs.

    Directories are handled by the caller: they have no suffix, and opening a
    folder in Explorer executes nothing.
    """
    return path.suffix.lower() in LAUNCHABLE_SUFFIXES


@function_tool()
async def save_note(
    context: RunContext,
    note: str,
) -> str:
    """Save a note to NOVA's notes file."""
    try:
        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        with NOTES_PATH.open(
            "a",
            encoding="utf-8",
        ) as notes_file:
            notes_file.write(
                f"[{timestamp}] {note}\n"
            )

        logger.info(
            "save_note: %d chars",
            len(note),
        )

        return "Note saved."

    except Exception:
        logger.exception("save_note failed")
        return "I could not save the note."


@function_tool()
async def read_notes(context: RunContext) -> str:
    """Read NOVA's saved notes."""
    try:
        if not NOTES_PATH.exists():
            return "You do not have any saved notes yet."

        return NOTES_PATH.read_text(
            encoding="utf-8"
        )

    except Exception:
        logger.exception("read_notes failed")
        return "I could not read the saved notes."


@function_tool()
async def list_files(
    context: RunContext,
    folder_path: str = ".",
) -> str:
    """List files inside an approved folder."""
    folder = resolve_safe_path(folder_path)

    if folder is None:
        logger.warning(
            "list_files denied: %r",
            folder_path,
        )

        return SANDBOX_DENIED

    try:
        if not folder.exists():
            return "That folder does not exist."

        if not folder.is_dir():
            return "That path is not a folder."

        items = list(folder.iterdir())

        if not items:
            return "The folder is empty."

        formatted_items = []

        for item in items[:50]:
            if item.is_dir():
                formatted_items.append(
                    f"[Folder] {item.name}"
                )
            else:
                formatted_items.append(
                    f"[File] {item.name}"
                )

        return "\n".join(formatted_items)

    except Exception:
        logger.exception("list_files failed")
        return "I could not list that folder."


def _search_roots(folder: str) -> list[Path] | None:
    cleaned = folder.lower().strip()
    if cleaned in {"", "all", "approved"}:
        return [root for root in SAFE_DIRS if root.exists()]

    known_folder = KNOWN_FOLDER_NAMES.get(cleaned)
    if known_folder is not None:
        return [
            root
            for root in SAFE_DIRS
            if root.name.lower() == known_folder.lower() and root.exists()
        ]

    root = resolve_safe_path(folder)
    if root is None:
        return None

    return [root]


def _path_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return MAX_FILE_SEARCH_DEPTH + 1


def _find_user_files_sync(query: str, folder: str, max_results: int) -> list[Path] | None:
    roots = _search_roots(folder)
    if roots is None:
        return None

    query_lower = query.lower().strip()
    matches: list[Path] = []

    for root in roots:
        if not root.exists():
            continue

        for current_root, dir_names, file_names in os.walk(root):
            current_path = Path(current_root)
            if _path_depth(current_path, root) > MAX_FILE_SEARCH_DEPTH:
                dir_names[:] = []
                continue

            dir_names[:] = [
                name
                for name in dir_names
                if name not in SKIPPED_SEARCH_DIRS and not name.startswith(".env")
            ]

            candidates = [current_path / name for name in [*dir_names, *file_names]]
            for candidate in candidates:
                if candidate.name.startswith(".env"):
                    continue
                if query_lower in candidate.name.lower():
                    matches.append(candidate)
                    if len(matches) >= max_results:
                        return matches

    return matches


def _format_path_list(paths: list[Path]) -> str:
    lines = []
    for path in paths:
        kind = "Folder" if path.is_dir() else "File"
        lines.append(f"[{kind}] {path}")
    return "\n".join(lines)


@function_tool()
async def find_user_file(
    context: RunContext,
    query: str,
    folder: str = "all",
    max_results: int = 10,
) -> str:
    """Find files or folders by name inside NOVA's approved user folders."""
    query = query.strip()
    if not query:
        return "Tell me the file or folder name to search for."

    max_results = max(1, min(max_results, MAX_FILE_SEARCH_RESULTS))

    try:
        matches = await asyncio.to_thread(
            _find_user_files_sync,
            query,
            folder,
            max_results,
        )

        if matches is None:
            logger.warning(
                "find_user_file denied folder=%r query=%r",
                folder,
                query,
            )
            return SANDBOX_DENIED

        if not matches:
            return "I could not find a matching file or folder in the approved locations."

        logger.info(
            "find_user_file query=%r results=%s",
            query,
            len(matches),
        )
        return "Matching files and folders:\n" + _format_path_list(matches)

    except Exception:
        logger.exception("find_user_file failed")
        return "I could not search for that file."


@function_tool()
async def open_file_or_folder(
    context: RunContext,
    file_path_or_name: str,
) -> str:
    """Open a file or folder from NOVA's approved user folders."""
    raw = file_path_or_name.strip()
    if not raw:
        return "Tell me which file or folder to open."

    path = resolve_safe_path(raw)

    if path is None or not path.exists():
        matches = await asyncio.to_thread(
            _find_user_files_sync,
            raw,
            "all",
            2,
        )
        if matches:
            path = matches[0]

    if path is None:
        logger.warning("open_file_or_folder denied: %r", file_path_or_name)
        return SANDBOX_DENIED

    try:
        if not path.exists():
            return "That file or folder does not exist."

        # A folder opens in Explorer and runs nothing. A FILE goes to the shell's
        # default verb, which for an executable means run it -- so anything that
        # is not a known document/media type is refused here. Being inside a
        # SAFE_DIR says the path is allowed, never that its contents are safe.
        if path.is_file() and not is_launchable(path):
            logger.warning(
                "open_file_or_folder refused a non-document suffix: %s", path.suffix
            )
            return (
                f"I will not open '{path.name}'. Opening a {path.suffix or 'file with no'} "
                "file would ask Windows to run it, and NOVA only opens documents "
                "and media. Open it yourself if you are sure it is safe."
            )

        os.startfile(path)  # type: ignore[attr-defined]
        logger.info("open_file_or_folder: %s", path)
        return f"Opened {path}."

    except Exception:
        logger.exception("open_file_or_folder failed")
        return "I could not open that file or folder."


@function_tool()
async def read_file(
    context: RunContext,
    file_path: str,
) -> str:
    """Read a small text file inside an approved folder."""
    path = resolve_safe_path(file_path)

    if path is None:
        logger.warning(
            "read_file denied: %r",
            file_path,
        )

        return SANDBOX_DENIED

    try:
        if not path.exists():
            return "That file does not exist."

        if not path.is_file():
            return "That path is not a file."

        if path.stat().st_size > 20_000:
            return (
                "The file is too large to read safely "
                "with this tool."
            )

        return path.read_text(
            encoding="utf-8"
        )

    except UnicodeDecodeError:
        return (
            "That file is not a supported text file."
        )

    except Exception:
        logger.exception("read_file failed")
        return "I could not read that file."


def _trim_course_text(text: str) -> tuple[str, bool]:
    """Return text capped to the course-material tool limit."""
    if len(text) <= MAX_COURSE_MATERIAL_CHARS:
        return text, False

    return text[:MAX_COURSE_MATERIAL_CHARS].rstrip(), True


def _format_course_material_result(
    path: Path,
    source_description: str,
    text: str,
    was_trimmed: bool,
) -> str:
    if not text.strip():
        return (
            "I could not find readable text in that course material. "
            "It may be scanned, image-only, or empty."
        )

    suffix = ""
    if was_trimmed:
        suffix = (
            "\n\n[Output capped at about "
            f"{MAX_COURSE_MATERIAL_CHARS:,} characters. "
            "Ask for a smaller page range if you need more.]"
        )

    return (
        f"Extracted text from {path.name} ({source_description}):\n\n"
        f"{text.strip()}"
        f"{suffix}"
    )


def _read_text_course_material(path: Path) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8")
    return _trim_course_text(text)


def _read_pdf_course_material(
    path: Path,
    start_page: int,
    end_page: int,
) -> tuple[str, str, bool]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    total_pages = len(reader.pages)

    if total_pages == 0:
        return "", "0 pages", False

    if start_page > total_pages:
        raise ValueError(
            f"That PDF has {total_pages} page(s), so page {start_page} is outside its range."
        )

    last_page = total_pages if end_page == 0 else min(end_page, total_pages)
    selected_pages = reader.pages[start_page - 1:last_page]
    extracted_parts = []

    for page in selected_pages:
        extracted_parts.append(page.extract_text() or "")

    text = "\n\n".join(part.strip() for part in extracted_parts if part.strip())
    trimmed_text, was_trimmed = _trim_course_text(text)

    if start_page == last_page:
        description = f"page {start_page} of {total_pages}"
    else:
        description = f"pages {start_page}-{last_page} of {total_pages}"

    return trimmed_text, description, was_trimmed


@function_tool()
async def read_course_material(
    context: RunContext,
    material_path: str,
    start_page: int = 1,
    end_page: int = 0,
) -> str:
    """Extract text from a PDF, Markdown, or text file in course_materials."""
    path = resolve_course_material_path(material_path)

    if path is None:
        logger.warning(
            "read_course_material denied: %r",
            material_path,
        )

        return COURSE_MATERIALS_DENIED

    try:
        if start_page < 1:
            return "Start page must be 1 or higher."

        if end_page < 0:
            return "End page must be 0 or higher. Use 0 to read through the end of the PDF."

        if end_page and end_page < start_page:
            return "End page must be greater than or equal to start page."

        if not path.exists():
            return (
                "That course material does not exist. Put it in the "
                "course_materials folder first."
            )

        if not path.is_file():
            return "That course material path is not a file."

        extension = path.suffix.lower()
        if extension not in SUPPORTED_COURSE_EXTENSIONS:
            return (
                "That course material type is not supported yet. "
                "Use a PDF, Markdown file, or text file."
            )

        if extension == ".pdf":
            text, description, was_trimmed = await asyncio.to_thread(
                _read_pdf_course_material,
                path,
                start_page,
                end_page,
            )
        else:
            if start_page != 1 or end_page != 0:
                return "Page ranges only apply to PDF course materials."

            text, was_trimmed = await asyncio.to_thread(
                _read_text_course_material,
                path,
            )
            description = "text file"

        logger.info(
            "read_course_material: %s",
            path.name,
        )

        return _format_course_material_result(
            path,
            description,
            text,
            was_trimmed,
        )

    except ImportError:
        logger.exception("read_course_material missing pypdf")
        return (
            "PDF reading needs the pypdf package. "
            "Install requirements.txt, then try again."
        )

    except UnicodeDecodeError:
        return "That course material is not valid UTF-8 text."

    except ValueError as exc:
        return str(exc)

    except Exception:
        logger.exception("read_course_material failed")
        return "I could not read that course material."


@function_tool()
async def create_file(
    context: RunContext,
    file_path: str,
    content: str,
) -> str:
    """Create a new file without overwriting existing files."""
    path = resolve_safe_path(file_path)

    if path is None:
        logger.warning(
            "create_file denied: %r",
            file_path,
        )

        return SANDBOX_DENIED

    try:
        if path.exists():
            return (
                "That file already exists. I will not "
                "overwrite it without confirmation."
            )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            content,
            encoding="utf-8",
        )

        logger.info(
            "create_file: %s",
            path,
        )

        return f"Created file: {path}"

    except Exception:
        logger.exception("create_file failed")
        return "I could not create that file."


def _safe_desktop_child(name: str, *, extension: str = "") -> Path | None:
    cleaned = name.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith(".env") or "/" in cleaned:
        return None

    path = DEFAULT_DESKTOP_PATH / cleaned
    if extension and path.suffix == "":
        path = path.with_suffix(extension)

    # A requested ".bat"/".exe" used to pass straight through, because the
    # default extension was only applied when the suffix was EMPTY. That let
    # NOVA write a runnable file and then launch it. Writing a document is a
    # reasonable thing to ask for; writing a program is not.
    if not is_launchable(path):
        path = path.with_suffix(path.suffix + (extension or ".txt"))

    return path


@function_tool()
async def create_desktop_file(
    context: RunContext,
    file_name: str,
    content: str = "",
) -> str:
    """Create a new file on Ahmed's Desktop without overwriting."""
    path = _safe_desktop_child(file_name, extension=".txt")
    if path is None:
        return "Use a simple file name without folders or unsafe names."

    try:
        DEFAULT_DESKTOP_PATH.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return "That Desktop file already exists. I will not overwrite it."

        path.write_text(content, encoding="utf-8")
        logger.info("create_desktop_file: %s", path)
        return f"Created Desktop file: {path}"

    except Exception:
        logger.exception("create_desktop_file failed")
        return "I could not create that Desktop file."


@function_tool()
async def create_desktop_folder(
    context: RunContext,
    folder_name: str,
) -> str:
    """Create a new folder on Ahmed's Desktop without overwriting."""
    path = _safe_desktop_child(folder_name)
    if path is None:
        return "Use a simple folder name without folders or unsafe names."

    try:
        DEFAULT_DESKTOP_PATH.mkdir(parents=True, exist_ok=True)

        if path.exists():
            return "That Desktop folder already exists."

        path.mkdir()
        logger.info("create_desktop_folder: %s", path)
        return f"Created Desktop folder: {path}"

    except Exception:
        logger.exception("create_desktop_folder failed")
        return "I could not create that Desktop folder."
