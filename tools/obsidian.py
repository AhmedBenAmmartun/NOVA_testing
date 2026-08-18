import os
from pathlib import Path
import re
from datetime import datetime

from .common import logger
from livekit.agents import RunContext, function_tool


MAX_NOTE_READ_CHARS = 20_000
MAX_SEARCH_SCAN_BYTES = 2_000_000
MAX_MEMORY_WRITE_CHARS = 20_000
NOVA_MEMORY_FOLDER = "NOVA"
SECRET_MARKERS = (
    ".env",
    "api key",
    "apikey",
    "bearer ",
    "password",
    "secret",
    "sk-",
    "token",
)


class ObsidianConfigurationError(RuntimeError):
    """Raised when NOVA cannot access its Obsidian vault."""


def get_obsidian_vault_path() -> Path:
    """Return NOVA's configured Obsidian vault."""
    raw_path = os.getenv("OBSIDIAN_VAULT_PATH")

    if not raw_path:
        raise ObsidianConfigurationError(
            "OBSIDIAN_VAULT_PATH is not configured."
        )

    vault_path = Path(raw_path).expanduser().resolve()

    if not vault_path.is_dir():
        raise ObsidianConfigurationError(
            "The configured Obsidian vault does not exist."
        )

    return vault_path


def resolve_obsidian_note(note_path: str) -> Path:
    """Resolve a Markdown note safely inside the vault."""
    vault_path = get_obsidian_vault_path()

    cleaned_path = note_path.strip().replace("\\", "/")

    if not cleaned_path.lower().endswith(".md"):
        cleaned_path += ".md"

    resolved_path = (vault_path / cleaned_path).resolve()

    try:
        relative_path = resolved_path.relative_to(vault_path)
    except ValueError as error:
        raise PermissionError(
            "That note is outside the Obsidian vault."
        ) from error

    if ".obsidian" in relative_path.parts:
        raise PermissionError(
            "NOVA cannot access Obsidian configuration files."
        )

    return resolved_path


def _read_note_text(path: Path, max_bytes: int | None = None) -> str:
    """Read Markdown text safely, optionally bounded by bytes."""
    if max_bytes is None:
        return path.read_text(encoding="utf-8", errors="ignore")

    with path.open("rb") as handle:
        data = handle.read(max_bytes)
    return data.decode("utf-8", errors="ignore")


def _note_excerpt(content: str, query: str, max_excerpts: int = 4) -> str | None:
    query_clean = _clean_text(query).casefold()
    if not query_clean:
        return None

    lowered = content.casefold()
    start = 0
    excerpts: list[str] = []
    while len(excerpts) < max_excerpts:
        index = lowered.find(query_clean, start)
        if index == -1:
            break
        left = max(0, index - 450)
        right = min(len(content), index + len(query_clean) + 450)
        prefix = "..." if left > 0 else ""
        suffix = "..." if right < len(content) else ""
        excerpts.append(prefix + content[left:right].strip() + suffix)
        start = index + len(query_clean)
    return "\n\n---\n\n".join(excerpts) if excerpts else None


def _trim_note_output(content: str, note_path: str, query: str = "") -> str:
    if query:
        excerpt = _note_excerpt(content, query)
        if excerpt:
            return (
                f"Excerpts from {note_path} matching {query!r}:\n\n"
                f"{excerpt}"
            )

    if len(content) <= MAX_NOTE_READ_CHARS:
        return content

    trimmed = content[:MAX_NOTE_READ_CHARS].rstrip()
    return (
        f"{trimmed}\n\n"
        f"[Note shortened: showing {MAX_NOTE_READ_CHARS:,} of "
        f"{len(content):,} characters from {note_path}. "
        "Ask to read it again with a search query for a specific section.]"
    )


def read_obsidian_note(note_path: str, query: str = "") -> str:
    """Read a Markdown note from the vault, with caps for large notes."""
    path = resolve_obsidian_note(note_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Obsidian note not found: {note_path}"
        )

    content = _read_note_text(path)

    logger.info("read_obsidian_note: %s", path)

    return _trim_note_output(content, note_path, query)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "memory"


def _looks_like_secret(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def resolve_nova_memory_folder(folder: str = NOVA_MEMORY_FOLDER) -> Path:
    """Resolve a safe folder under the vault's NOVA memory area."""
    vault_path = get_obsidian_vault_path()
    cleaned = folder.strip().replace("\\", "/").strip("/")
    parts = [part for part in cleaned.split("/") if part]

    if parts and parts[0].casefold() == NOVA_MEMORY_FOLDER.casefold():
        parts = parts[1:]

    for part in parts:
        part_lower = part.casefold()
        if part in {".", ".."} or part_lower.startswith(".env") or part_lower == ".obsidian":
            raise PermissionError(
                "Memory notes can only be saved inside the NOVA vault folder."
            )

    memory_root = (vault_path / NOVA_MEMORY_FOLDER).resolve()
    target = memory_root.joinpath(*parts).resolve()

    try:
        target.relative_to(memory_root)
    except ValueError as error:
        raise PermissionError(
            "Memory notes can only be saved inside the NOVA vault folder."
        ) from error

    return target


def _render_memory_note(title: str, content: str, folder: str) -> str:
    created = datetime.now()
    return (
        f"# {title}\n\n"
        f"- Created: {created:%Y-%m-%d %H:%M:%S}\n"
        "- Source: NOVA\n"
        f"- Folder: {folder}\n\n"
        "## Note\n\n"
        f"{content.strip()}\n"
    )


def write_memory_note(title: str, content: str, folder: str = NOVA_MEMORY_FOLDER) -> Path:
    """Write a new Markdown note under the vault's NOVA folder."""
    title = _clean_text(title)
    content = content.strip()

    if not title:
        raise ValueError("Give the memory note a short title.")

    if not content:
        raise ValueError("Give me something to save in memory.")

    if _looks_like_secret(f"{title}\n{content}"):
        raise ValueError("I will not save passwords, API keys, tokens, or secrets to memory.")

    if len(content) > MAX_MEMORY_WRITE_CHARS:
        content = content[:MAX_MEMORY_WRITE_CHARS].rstrip() + "\n\n[Trimmed for storage.]"

    folder_path = resolve_nova_memory_folder(folder)
    folder_path.mkdir(parents=True, exist_ok=True)

    created = datetime.now()
    base_name = f"{created:%Y-%m-%d_%H%M%S}_{_slugify(title)}"
    path = folder_path / f"{base_name}.md"
    counter = 2
    while path.exists():
        path = folder_path / f"{base_name}-{counter}.md"
        counter += 1

    path.write_text(
        _render_memory_note(title, content, folder),
        encoding="utf-8",
    )

    logger.info("write_memory_note: %s", path)
    return path


def search_obsidian_notes(
    query: str,
    limit: int = 10,
) -> list[str]:
    """Search note names and contents locally."""
    cleaned_query = query.strip().casefold()

    if len(cleaned_query) < 2:
        raise ValueError(
            "The memory search must contain at least two characters."
        )

    vault_path = get_obsidian_vault_path()
    safe_limit = max(1, min(int(limit), 25))
    matches: list[str] = []

    for path in vault_path.rglob("*.md"):
        relative_path = path.relative_to(vault_path)

        if ".obsidian" in relative_path.parts:
            continue

        try:
            content = _read_note_text(
                path,
                max_bytes=MAX_SEARCH_SCAN_BYTES,
            ).casefold()

        except (OSError, UnicodeDecodeError):
            logger.warning(
                "Could not search Obsidian note: %s",
                path,
            )
            continue

        searchable_text = (
            f"{path.stem.casefold()}\n{content}"
        )

        if cleaned_query in searchable_text:
            matches.append(
                relative_path.as_posix()
            )

        if len(matches) >= safe_limit:
            break

    logger.info(
        "search_obsidian_notes: query=%r matches=%d",
        query,
        len(matches),
    )

    return matches


@function_tool()
async def search_memory(
    context: RunContext,
    query: str,
    limit: int = 10,
) -> str:
    """Search NOVA's local memory and return matching note paths."""
    try:
        matches = search_obsidian_notes(
            query=query,
            limit=limit,
        )

        if not matches:
            return (
                "No matching memory notes were found."
            )

        formatted_matches = "\n".join(
            f"- {path}"
            for path in matches
        )

        return (
            "Matching local memory notes:\n"
            f"{formatted_matches}"
        )

    except Exception:
        logger.exception(
            "search_memory failed for query=%r",
            query,
        )

        return (
            "NOVA could not search local memory."
        )


@function_tool()
async def save_memory_note(
    context: RunContext,
    title: str,
    content: str,
    folder: str = NOVA_MEMORY_FOLDER,
) -> str:
    """Save a new Markdown memory note inside the Obsidian vault's NOVA folder."""
    try:
        path = write_memory_note(title, content, folder)
        relative_path = path.relative_to(get_obsidian_vault_path())
        return f"Saved memory note: {relative_path.as_posix()}"

    except (
        ObsidianConfigurationError,
        PermissionError,
        ValueError,
        OSError,
    ) as error:
        logger.warning(
            "save_memory_note refused title=%r folder=%r: %s",
            title,
            folder,
            error,
        )
        return str(error)

    except Exception:
        logger.exception(
            "save_memory_note failed title=%r folder=%r",
            title,
            folder,
        )
        return "NOVA could not save that memory note."


@function_tool()
async def read_memory_note(
    context: RunContext,
    note_path: str,
    query: str = "",
) -> str:
    """Read one memory note that search_memory found; use query for large notes."""
    try:
        return read_obsidian_note(note_path, query)

    except (
        ObsidianConfigurationError,
        FileNotFoundError,
        PermissionError,
        ValueError,
    ) as error:
        logger.warning(
            "read_memory_note refused %r: %s",
            note_path,
            error,
        )

        return str(error)

    except Exception:
        logger.exception(
            "read_memory_note failed for %r",
            note_path,
        )

        return (
            "NOVA could not read that memory note."
        )
# ---------------------------------------------------------------------------
# NOVA Vault Second Brain
# ---------------------------------------------------------------------------

SAFE_VAULT_TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".json",
    ".csv",
    ".yaml",
    ".yml",
}
SECOND_BRAIN_WRITABLE_FOLDERS = {
    "profile",
    "projects",
    "decisions",
    "knowledge",
    "conversations",
    "daily",
    "inbox",
    "pending review",
    "skills",
    "nova",
}
SECOND_BRAIN_READ_ONLY_FOLDERS = {
    "archive",
    "scripts",
}
MAX_VAULT_FILE_READ_CHARS = 50_000
MAX_VAULT_FILE_WRITE_CHARS = 100_000


def _normalize_vault_relative_path(relative_path: str) -> str:
    cleaned = str(relative_path or "").strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise ValueError("Give me a file path inside the NOVA Vault.")

    candidate = Path(cleaned)
    if candidate.is_absolute():
        raise PermissionError("Use a path relative to the NOVA Vault.")

    for part in candidate.parts:
        lowered = part.casefold()
        if part in {".", ".."}:
            raise PermissionError("Parent-directory paths are not allowed in the NOVA Vault.")
        if lowered == ".obsidian" or lowered.startswith(".env") or lowered == ".git":
            raise PermissionError("That protected vault path is not available to NOVA.")

    return cleaned


def _resolve_vault_text_file(relative_path: str, *, for_write: bool) -> Path:
    vault = get_obsidian_vault_path()
    cleaned = _normalize_vault_relative_path(relative_path)

    resolved = (vault / cleaned).resolve()
    try:
        relative = resolved.relative_to(vault)
    except ValueError as error:
        raise PermissionError("That file is outside the NOVA Vault.") from error

    if any(
        part.casefold() == ".obsidian"
        or part.casefold() == ".git"
        or part.casefold().startswith(".env")
        for part in relative.parts
    ):
        raise PermissionError("That protected vault path is not available to NOVA.")

    if not relative.parts:
        raise PermissionError("Choose a file inside the NOVA Vault.")

    if for_write:
        top_folder = relative.parts[0].casefold()
        if top_folder in SECOND_BRAIN_READ_ONLY_FOLDERS:
            raise PermissionError(
                f"{relative.parts[0]} is read-only for NOVA's second-brain tools."
            )
        if top_folder not in SECOND_BRAIN_WRITABLE_FOLDERS:
            allowed = ", ".join(sorted(SECOND_BRAIN_WRITABLE_FOLDERS))
            raise PermissionError(
                f"NOVA may write only to approved second-brain folders: {allowed}"
            )

    suffix = resolved.suffix.casefold()
    if suffix not in SAFE_VAULT_TEXT_EXTENSIONS:
        allowed = ", ".join(sorted(SAFE_VAULT_TEXT_EXTENSIONS))
        raise ValueError(f"That file type is not enabled for the second brain. Allowed: {allowed}")

    return resolved


def list_second_brain_files(folder: str = "", limit: int = 100) -> list[str]:
    vault = get_obsidian_vault_path()
    cleaned_folder = str(folder or "").strip().replace("\\", "/").strip("/")

    base = vault if not cleaned_folder else (vault / cleaned_folder).resolve()
    try:
        base.relative_to(vault)
    except ValueError as error:
        raise PermissionError("That folder is outside the NOVA Vault.") from error

    if ".obsidian" in {part.casefold() for part in base.relative_to(vault).parts}:
        raise PermissionError("NOVA cannot access Obsidian configuration files.")

    if not base.exists():
        return []

    safe_limit = max(1, min(int(limit), 250))
    results: list[str] = []

    for path in sorted(base.rglob("*"), key=lambda p: p.as_posix().casefold()):
        if not path.is_file():
            continue

        rel = path.relative_to(vault)
        lowered_parts = [part.casefold() for part in rel.parts]
        if ".obsidian" in lowered_parts or ".git" in lowered_parts:
            continue
        if any(part.startswith(".env") for part in lowered_parts):
            continue
        if path.suffix.casefold() not in SAFE_VAULT_TEXT_EXTENSIONS:
            continue

        results.append(rel.as_posix())
        if len(results) >= safe_limit:
            break

    return results


def read_second_brain_file(relative_path: str) -> str:
    path = _resolve_vault_text_file(relative_path, for_write=False)
    if not path.is_file():
        raise FileNotFoundError(f"NOVA Vault file not found: {relative_path}")

    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > MAX_VAULT_FILE_READ_CHARS:
        return (
            content[:MAX_VAULT_FILE_READ_CHARS].rstrip()
            + f"\n\n[File shortened: showing {MAX_VAULT_FILE_READ_CHARS:,} "
            + f"of {len(content):,} characters.]"
        )
    return content


def write_second_brain_file(
    relative_path: str,
    content: str,
    *,
    overwrite: bool = False,
) -> Path:
    content = str(content or "")
    if not content.strip():
        raise ValueError("Give me content to save.")

    if _looks_like_secret(f"{relative_path}\n{content}"):
        raise ValueError(
            "I will not save passwords, API keys, tokens, .env content, or secrets to the second brain."
        )

    if len(content) > MAX_VAULT_FILE_WRITE_CHARS:
        raise ValueError(
            f"That file is too large for this tool. Maximum: {MAX_VAULT_FILE_WRITE_CHARS:,} characters."
        )

    path = _resolve_vault_text_file(relative_path, for_write=True)
    if path.exists() and not overwrite:
        relative = path.relative_to(get_obsidian_vault_path()).as_posix()
        raise FileExistsError(
            f"{relative} already exists. Ask explicitly to overwrite it if replacement is intended."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("write_second_brain_file: %s", path)
    return path


@function_tool()
async def second_brain_status(context: RunContext) -> str:
    """Check NOVA's configured persistent NOVA Vault second brain."""
    try:
        vault = get_obsidian_vault_path()
        markdown_count = 0
        for path in vault.rglob("*.md"):
            try:
                rel = path.relative_to(vault)
            except ValueError:
                continue
            if ".obsidian" in {part.casefold() for part in rel.parts}:
                continue
            markdown_count += 1

        return (
            "NOVA second brain is available.\n"
            f"Vault: {vault}\n"
            f"Markdown notes indexed by local search: {markdown_count}\n"
            "Writable folders: Profile, Projects, Decisions, Knowledge, Conversations, "
            "Daily, Inbox, Pending Review, Skills, NOVA.\n"
            "Read-only folders: Archive, Scripts.\n"
            "Protected: .obsidian, .env, .git, secrets, and paths outside the vault."
        )
    except Exception as error:
        logger.warning("second_brain_status failed: %s", error)
        return f"NOVA second brain is not available: {error}"


@function_tool()
async def list_vault_files(
    context: RunContext,
    folder: str = "",
    limit: int = 100,
) -> str:
    """List safe text files in NOVA's second-brain vault."""
    try:
        files = list_second_brain_files(folder, limit)
        if not files:
            return "No matching second-brain files were found."
        return "Second-brain files:\n" + "\n".join(f"- {path}" for path in files)
    except Exception as error:
        logger.warning("list_vault_files failed folder=%r: %s", folder, error)
        return str(error)


@function_tool()
async def read_vault_file(
    context: RunContext,
    relative_path: str,
) -> str:
    """Read a safe text file from the NOVA Vault."""
    try:
        return read_second_brain_file(relative_path)
    except Exception as error:
        logger.warning("read_vault_file failed path=%r: %s", relative_path, error)
        return str(error)


@function_tool()
async def save_vault_file(
    context: RunContext,
    relative_path: str,
    content: str,
    overwrite: bool = False,
) -> str:
    """Save a safe text/data file into an approved existing second-brain folder."""
    try:
        path = write_second_brain_file(
            relative_path,
            content,
            overwrite=bool(overwrite),
        )
        rel = path.relative_to(get_obsidian_vault_path()).as_posix()
        return f"Saved second-brain file: {rel}"
    except Exception as error:
        logger.warning("save_vault_file refused path=%r: %s", relative_path, error)
        return str(error)
