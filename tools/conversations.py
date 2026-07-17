from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re

from livekit.agents import RunContext, function_tool

from .common import (
    CONVERSATION_LOGS_DENIED,
    CONVERSATION_LOGS_PATH,
    logger,
    resolve_conversation_log_path,
)
from .obsidian import (
    ObsidianConfigurationError,
    resolve_nova_memory_folder,
)


MAX_CONVERSATION_READ_CHARS = 20_000
MAX_SEARCH_FILES = 200
MAX_SEARCH_RESULTS = 10
MAX_TITLE_CHARS = 72
MAX_TURN_CHARS = 6_000


@dataclass(slots=True)
class ConversationTurn:
    """A persisted user or assistant message from a live NOVA session."""

    role: str
    text: str
    created_at: datetime = field(default_factory=datetime.now)


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _trim_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    return text[:limit].rstrip() + "\n\n[Trimmed for storage.]"


def _title_from_text(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return "Untitled conversation"

    title = cleaned[:MAX_TITLE_CHARS].strip(" .,:;!?-_")
    return title or "Untitled conversation"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")
    return slug[:48].strip("-") or "session"


def _extract_item_text(item: object) -> str:
    text = getattr(item, "text_content", None)
    if isinstance(text, str):
        return text.strip()

    content = getattr(item, "content", None)
    if isinstance(content, list):
        parts = [part for part in content if isinstance(part, str)]
        return "\n".join(parts).strip()

    return ""


def _conversation_files() -> list[Path]:
    root = CONVERSATION_LOGS_PATH
    if not root.exists():
        return []

    files = [
        path
        for path in root.rglob("*.md")
        if path.is_file()
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:MAX_SEARCH_FILES]


def _read_title(path: Path, fallback: str | None = None) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or fallback or path.stem
    except OSError:
        pass

    return fallback or path.stem


def _find_named_log(conversation_file: str) -> Path | None:
    if conversation_file.strip().lower() == "latest":
        files = _conversation_files()
        return files[0] if files else None

    resolved = resolve_conversation_log_path(conversation_file)
    if resolved and resolved.exists():
        return resolved

    requested = Path(conversation_file).name.lower()
    for path in _conversation_files():
        if path.name.lower() == requested:
            return path

    return resolved


class SessionConversationRecorder:
    """Persist one voice session as a local Markdown conversation log."""

    def __init__(self) -> None:
        self.started_at = datetime.now()
        self.ended_at: datetime | None = None
        self.title: str | None = None
        self.file_path: Path | None = None
        self.vault_file_path: Path | None = None
        self.turns: list[ConversationTurn] = []

    def attach(self, session) -> None:
        """Attach this recorder to a LiveKit AgentSession."""

        @session.on("conversation_item_added")
        def _record_conversation_item(event) -> None:
            self.record_item(event.item)

        @session.on("close")
        def _finish_conversation(_event) -> None:
            self.finish()

    def record_item(self, item: object) -> None:
        role = getattr(item, "role", "")
        if role not in {"user", "assistant"}:
            return

        text = _extract_item_text(item)
        if not text:
            return

        if role == "user" and self.title is None:
            self.title = _title_from_text(text)

        self.turns.append(
            ConversationTurn(
                role=role,
                text=_trim_text(text, MAX_TURN_CHARS),
            )
        )

        if self._has_user_turn():
            self.write()

    def finish(self) -> None:
        self.ended_at = datetime.now()
        if self._has_user_turn():
            self.write()

    def write(self) -> Path | None:
        try:
            rendered = self._render()
            path = self._ensure_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            logger.info(
                "conversation log saved: %s turns=%s",
                path.name,
                len(self.turns),
            )
            self._write_vault_copy(rendered)
            return path

        except Exception:
            logger.exception("conversation log save failed")
            return None

    def _has_user_turn(self) -> bool:
        return any(turn.role == "user" for turn in self.turns)

    def _ensure_file_path(self) -> Path:
        if self.file_path is not None:
            return self.file_path

        title = self.title or "Untitled conversation"
        day_folder = CONVERSATION_LOGS_PATH / self.started_at.strftime("%Y") / self.started_at.strftime("%m")
        filename = f"{self.started_at:%Y-%m-%d_%H%M%S}_{_slugify(title)}.md"
        self.file_path = day_folder / filename
        return self.file_path

    def _ensure_vault_file_path(self) -> Path:
        if self.vault_file_path is not None:
            return self.vault_file_path

        title = self.title or "Untitled conversation"
        conversations_root = resolve_nova_memory_folder("Conversations")
        day_folder = conversations_root / self.started_at.strftime("%Y") / self.started_at.strftime("%m")
        filename = f"{self.started_at:%Y-%m-%d_%H%M%S}_{_slugify(title)}.md"
        self.vault_file_path = day_folder / filename
        return self.vault_file_path

    def _write_vault_copy(self, rendered: str) -> None:
        try:
            path = self._ensure_vault_file_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
            logger.info(
                "conversation log mirrored to Obsidian: %s turns=%s",
                path.name,
                len(self.turns),
            )

        except ObsidianConfigurationError as error:
            logger.info("conversation vault mirror skipped: %s", error)

        except Exception:
            logger.exception("conversation vault mirror failed")

    def _summary(self) -> str:
        first_user = next(
            (turn.text for turn in self.turns if turn.role == "user"),
            "",
        )
        if not first_user:
            return "No user request was recorded."

        return f"Started with: {_clean_text(first_user)[:220]}"

    def _render(self) -> str:
        title = self.title or "Untitled conversation"
        ended = self.ended_at.strftime("%Y-%m-%d %H:%M:%S") if self.ended_at else "in progress"
        lines = [
            f"# {title}",
            "",
            f"- Started: {self.started_at:%Y-%m-%d %H:%M:%S}",
            f"- Ended: {ended}",
            f"- Turns: {len(self.turns)}",
            "",
            "## Summary",
            "",
            self._summary(),
            "",
            "## Transcript",
            "",
        ]

        for turn in self.turns:
            speaker = "Ahmed" if turn.role == "user" else "NOVA"
            lines.extend(
                [
                    f"### {speaker} - {turn.created_at:%H:%M:%S}",
                    "",
                    turn.text.strip(),
                    "",
                ]
            )

        return "\n".join(lines).rstrip() + "\n"


@function_tool()
async def search_conversation_history(
    context: RunContext,
    query: str = "",
    limit: int = 5,
) -> str:
    """Search saved NOVA conversation logs, or list recent sessions."""
    try:
        limit = max(1, min(limit, MAX_SEARCH_RESULTS))
        query_clean = _clean_text(query).lower()
        results: list[str] = []

        for path in _conversation_files():
            text = path.read_text(encoding="utf-8", errors="replace")
            text_lower = text.lower()
            if query_clean and query_clean not in text_lower and query_clean not in path.name.lower():
                continue

            title = _read_title(path)
            relative = path.relative_to(CONVERSATION_LOGS_PATH)
            preview = ""
            for line in text.splitlines():
                clean_line = line.strip()
                if not clean_line or clean_line.startswith("#") or clean_line.startswith("- "):
                    continue
                if not query_clean or query_clean in clean_line.lower():
                    preview = clean_line[:180]
                    break

            if not preview:
                preview = "Saved conversation log."

            results.append(
                f"- {title} ({relative})\n  {preview}"
            )

            if len(results) >= limit:
                break

        if not results:
            if query_clean:
                return "I could not find any saved conversations matching that."
            return "There are no saved conversation logs yet."

        logger.info(
            "search_conversation_history query=%r results=%s",
            query,
            len(results),
        )

        heading = "Recent saved conversations" if not query_clean else "Matching saved conversations"
        return f"{heading}:\n" + "\n".join(results)

    except Exception:
        logger.exception("search_conversation_history failed")
        return "I could not search the saved conversation history."


@function_tool()
async def read_conversation_history(
    context: RunContext,
    conversation_file: str = "latest",
) -> str:
    """Read a saved NOVA conversation log. Use 'latest' for the newest session."""
    path = _find_named_log(conversation_file)

    if path is None:
        return "There are no saved conversation logs yet."

    try:
        if not path.exists():
            return "That conversation log does not exist."

        resolved = resolve_conversation_log_path(str(path))
        if resolved is None:
            logger.warning(
                "read_conversation_history denied: %r",
                conversation_file,
            )
            return CONVERSATION_LOGS_DENIED

        text = resolved.read_text(encoding="utf-8", errors="replace")
        was_trimmed = len(text) > MAX_CONVERSATION_READ_CHARS
        if was_trimmed:
            text = text[:MAX_CONVERSATION_READ_CHARS].rstrip()

        relative = resolved.relative_to(CONVERSATION_LOGS_PATH)
        suffix = ""
        if was_trimmed:
            suffix = "\n\n[Output capped. Ask for a more specific search if you need more.]"

        logger.info(
            "read_conversation_history: %s",
            relative,
        )

        return f"Saved conversation {relative}:\n\n{text}{suffix}"

    except Exception:
        logger.exception("read_conversation_history failed")
        return "I could not read that conversation log."
