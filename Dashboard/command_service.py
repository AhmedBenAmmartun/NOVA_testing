"""Safe, deterministic commands exposed by the desktop command bar."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from dotenv import load_dotenv

from .status_service import PROJECT_ROOT


load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    message: str
    action: str = "none"
    sensitivity: str = "safe"


BLOCKED_PREFIXES = (
    "close ",
    "restart ",
    "shutdown",
    "turn off",
    "minimize ",
    "maximize ",
    "snap ",
    "volume ",
    "mute",
    "new virtual desktop",
    "switch desktop",
    "screen capture",
    "take a screenshot",
)


def _run(coro: Awaitable[str]) -> str:
    return asyncio.run(coro)


def _trim(message: str, limit: int = 2_400) -> str:
    clean = message.strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "\n[Output shortened for the desktop skin.]"


class SafeCommandService:
    """Run only read, search, open, and guarded note operations from the skin."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[..., str]] = {
            "time": self._time,
            "system": self._system,
            "find": self._find,
            "open": self._open,
            "read": self._read,
            "list": self._list,
            "memory": self._memory,
            "conversation": self._conversation,
            "save memory": self._save_memory,
            "help": self._help,
        }

    def execute(self, text: str) -> CommandResult:
        """Parse a small safe command vocabulary without giving the UI raw tools."""
        cleaned = " ".join(text.strip().split())
        lowered = cleaned.casefold()
        if not cleaned:
            return CommandResult(False, "Type a command or press Escape to close.")

        if lowered.startswith(BLOCKED_PREFIXES):
            return CommandResult(
                False,
                "That action is not available from the desktop command bar. Use voice NOVA so it can request confirmation.",
                action="confirmation_required",
                sensitivity="sensitive",
            )

        if lowered in {"help", "?", "commands"}:
            return CommandResult(True, self._help())

        handler_name = next(
            (name for name in self._handlers if lowered == name or lowered.startswith(name + " ")),
            None,
        )
        if handler_name is None:
            return CommandResult(
                False,
                "I can safely handle: time, system, find, open, read, list, memory, conversation, and save memory.",
            )

        try:
            message = self._handlers[handler_name](cleaned[len(handler_name):].strip())
            return CommandResult(True, _trim(message))
        except Exception:
            return CommandResult(False, "I could not complete that safe desktop command.")

    @staticmethod
    def _help(_argument: str = "") -> str:
        return (
            "Safe commands:\n"
            "time\n"
            "system status\n"
            "find <file or folder> in <desktop|documents|downloads|all>\n"
            "open <approved file, folder, app, or website>\n"
            "read <approved text file>\n"
            "list <approved folder>\n"
            "memory <search text>\n"
            "conversation <search text>\n"
            "save memory <title> :: <content>"
        )

    @staticmethod
    def _time(_argument: str = "") -> str:
        from tools.information import get_time

        return _run(get_time(None))

    @staticmethod
    def _system(_argument: str = "") -> str:
        from tools.information import get_system_info

        return _run(get_system_info(None))

    @staticmethod
    def _find(argument: str) -> str:
        from tools.files import find_user_file

        query, folder = _split_folder(argument)
        return _run(find_user_file(None, query, folder))

    @staticmethod
    def _open(argument: str) -> str:
        from tools.desktop import open_app, open_website
        from tools.files import open_file_or_folder

        lowered = argument.casefold()
        if lowered.startswith("app "):
            return _run(open_app(None, argument[4:].strip()))
        if lowered.startswith("website "):
            return _run(open_website(None, argument[8:].strip()))
        return _run(open_file_or_folder(None, argument))

    @staticmethod
    def _read(argument: str) -> str:
        from tools.files import read_file

        return _run(read_file(None, argument))

    @staticmethod
    def _list(argument: str) -> str:
        from tools.files import list_files

        return _run(list_files(None, argument or "."))

    @staticmethod
    def _memory(argument: str) -> str:
        from tools.obsidian import search_memory

        return _run(search_memory(None, argument))

    @staticmethod
    def _conversation(argument: str) -> str:
        from tools.conversations import search_conversation_history

        return _run(search_conversation_history(None, argument))

    @staticmethod
    def _save_memory(argument: str) -> str:
        from tools.obsidian import save_memory_note

        if "::" not in argument:
            return "Use: save memory <title> :: <content>"
        title, content = argument.split("::", 1)
        return _run(save_memory_note(None, title.strip(), content.strip()))


def _split_folder(argument: str) -> tuple[str, str]:
    lowered = argument.casefold()
    marker = " in "
    if marker in lowered:
        index = lowered.rfind(marker)
        query = argument[:index].strip()
        folder = argument[index + len(marker):].strip() or "all"
        return query, folder
    return argument.strip(), "all"
