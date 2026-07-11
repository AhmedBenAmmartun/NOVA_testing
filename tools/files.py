from datetime import datetime

from livekit.agents import RunContext, function_tool

from .common import (
    NOTES_PATH,
    SANDBOX_DENIED,
    logger,
    resolve_safe_path,
)


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