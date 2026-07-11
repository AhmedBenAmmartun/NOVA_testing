import ctypes
import logging
from pathlib import Path


# common.py is inside AI Agent/tools/
# .parent = tools
# .parent.parent = AI Agent
PROJECT_ROOT = Path(__file__).resolve().parent.parent

NOTES_PATH = PROJECT_ROOT / "notes.txt"
LOG_PATH = PROJECT_ROOT / "nova_tools.log"


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