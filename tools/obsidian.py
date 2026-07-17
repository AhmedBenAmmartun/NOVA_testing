import os
from pathlib import Path
import re
from datetime import datetime

from .common import logger
from livekit.agents import RunContext, function_tool


MAX_NOTE_SIZE = 100_000
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


def read_obsidian_note(note_path: str) -> str:
    """Read a reasonably sized Markdown note from the vault."""
    path = resolve_obsidian_note(note_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Obsidian note not found: {note_path}"
        )

    if path.stat().st_size > MAX_NOTE_SIZE:
        raise ValueError(
            "That Obsidian note is too large to read safely."
        )

    content = path.read_text(encoding="utf-8")

    logger.info("read_obsidian_note: %s", path)

    return content


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
            if path.stat().st_size > MAX_NOTE_SIZE:
                continue

            content = path.read_text(
                encoding="utf-8"
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
) -> str:
    """Read one memory note that search_memory found (vault-relative path)."""
    try:
        return read_obsidian_note(note_path)

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
