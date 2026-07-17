import ctypes
import logging
from pathlib import Path


# common.py is inside AI Agent/tools/
# .parent = tools
# .parent.parent = AI Agent
PROJECT_ROOT = Path(__file__).resolve().parent.parent

NOTES_PATH = PROJECT_ROOT / "notes.txt"
LOG_PATH = PROJECT_ROOT / "nova_tools.log"
COURSE_MATERIALS_PATH = PROJECT_ROOT / "course_materials"
CONVERSATION_LOGS_PATH = PROJECT_ROOT / "conversation_logs"


# ---------------------------------------------------------
# Logging
# ---------------------------------------------------------

logger = logging.getLogger("nova.tools")

if not logger.handlers:
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------
# Approved file locations
# ---------------------------------------------------------

_HOME = Path.home()
DEFAULT_DESKTOP_PATH = (
    _HOME / "OneDrive" / "Desktop"
    if (_HOME / "OneDrive" / "Desktop").exists()
    else _HOME / "Desktop"
)

SAFE_DIRS = [PROJECT_ROOT] + [
    base / sub
    for base in (_HOME, _HOME / "OneDrive")
    for sub in (
        "Desktop",
        "Documents",
        "Downloads",
        "Pictures",
        "Music",
        "Videos",
    )
]


SANDBOX_DENIED = (
    "Access denied: that path is outside NOVA's approved folders "
    "(Desktop, Documents, Downloads, Pictures, Music, Videos, "
    "and the NOVA project)."
)

COURSE_MATERIALS_DENIED = (
    "Access denied: course materials must be inside NOVA's "
    "course_materials folder."
)

CONVERSATION_LOGS_DENIED = (
    "Access denied: conversation logs must be inside NOVA's "
    "conversation_logs folder."
)


def resolve_safe_path(raw_path: str) -> Path | None:
    """Resolve a path only when it is inside an approved location."""
    try:
        path = Path(raw_path).expanduser().resolve()
    except (OSError, ValueError):
        return None

    # Secrets are always blocked.
    if path.name.startswith(".env"):
        return None

    if path.name == ".spotify_cache":
        return None

    for root in SAFE_DIRS:
        try:
            if path.is_relative_to(root):
                return path
        except (OSError, ValueError):
            continue

    return None


def resolve_course_material_path(raw_path: str) -> Path | None:
    """Resolve a course material path inside the project course folder."""
    try:
        raw = Path(raw_path).expanduser()
        course_root = COURSE_MATERIALS_PATH.resolve()

        if raw.is_absolute():
            path = raw.resolve()
        elif raw.parts and raw.parts[0] == COURSE_MATERIALS_PATH.name:
            path = (PROJECT_ROOT / raw).resolve()
        else:
            path = (course_root / raw).resolve()
    except (OSError, ValueError):
        return None

    # Secrets are always blocked, even if someone places one in the folder.
    if any(part.startswith(".env") for part in path.parts):
        return None

    if path.name == ".spotify_cache":
        return None

    try:
        if path.is_relative_to(course_root):
            return path
    except (OSError, ValueError):
        return None

    return None


def resolve_conversation_log_path(raw_path: str) -> Path | None:
    """Resolve a conversation log path inside the project log folder."""
    try:
        raw = Path(raw_path).expanduser()
        log_root = CONVERSATION_LOGS_PATH.resolve()

        if raw.is_absolute():
            path = raw.resolve()
        elif raw.parts and raw.parts[0] == CONVERSATION_LOGS_PATH.name:
            path = (PROJECT_ROOT / raw).resolve()
        else:
            path = (log_root / raw).resolve()
    except (OSError, ValueError):
        return None

    if any(part.startswith(".env") for part in path.parts):
        return None

    try:
        if path.is_relative_to(log_root):
            return path
    except (OSError, ValueError):
        return None

    return None


# ---------------------------------------------------------
# Windows keyboard helper
# ---------------------------------------------------------

def press_key(vk_code: int) -> None:
    """Press and release a Windows virtual key."""
    keyeventf_keyup = 0x0002

    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(
        vk_code,
        0,
        keyeventf_keyup,
        0,
    )
