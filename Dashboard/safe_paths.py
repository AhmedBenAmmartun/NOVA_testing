"""Shared denylist for sensitive files the dashboard must never surface.

Both the recent-files feed scanner (``feeds.py``) and the backend open action
(``actions.py``) call into here, so a credential-bearing file can never be
listed, previewed, opened, or logged from the dashboard — frontend filtering
alone is not sufficient. Windows ``.lnk`` shortcuts are resolved to their real
targets before a safety decision is made. Nothing here logs or returns the
sensitive path itself.
"""

from __future__ import annotations

# Filename prefixes (case-insensitive), checked against the name and its stem.
_SENSITIVE_NAME_PREFIXES = (
    ".env",
    "credentials",
    "secrets",
    "secret",
    "token",
    "password",
)

# Exact filenames (case-insensitive), checked against the name and its stem.
_SENSITIVE_NAMES = {
    "id_rsa",
    "id_ed25519",
}

# Directory segments that make everything beneath them sensitive.
_SENSITIVE_DIRS = {".ssh", ".gnupg", ".aws", ".azure"}

# Sensitive file extensions.
_SENSITIVE_EXTS = (".pem", ".key", ".pfx", ".p12", ".kdbx")


def is_sensitive_path(path_or_name: str | None) -> bool:
    """Return True for a path/name that names a credential-bearing file.

    Matches the requested denylist: ``.env`` / ``.env.*``, ``credentials*``,
    ``secrets*``, ``token*``, ``password*``, ``id_rsa``, ``id_ed25519``, the
    ``.ssh`` / ``.gnupg`` / ``.aws`` / ``.azure`` directories, and the
    ``.pem`` / ``.key`` / ``.pfx`` / ``.p12`` / ``.kdbx`` extensions.
    """
    if not path_or_name:
        return False
    text = str(path_or_name).strip().replace("/", "\\")
    if not text:
        return False

    segments = [seg.lower() for seg in text.split("\\") if seg]
    if any(seg in _SENSITIVE_DIRS for seg in segments):
        return True

    name = segments[-1] if segments else text.lower()
    # A recent-item .lnk hides the real name under a shortcut suffix.
    stem = name[:-4] if name.endswith(".lnk") else name

    for candidate in {name, stem}:
        if not candidate:
            continue
        if candidate.endswith(_SENSITIVE_EXTS):
            return True
        base = candidate.split(".", 1)[0]
        if candidate in _SENSITIVE_NAMES or base in _SENSITIVE_NAMES:
            return True
        for prefix in _SENSITIVE_NAME_PREFIXES:
            if candidate.startswith(prefix) or base.startswith(prefix):
                return True
    return False


def resolve_shortcut(lnk_path: str) -> str | None:
    """Resolve a Windows ``.lnk`` to its target path, or None on any failure."""
    try:
        import pythoncom
        import win32com.client
    except Exception:
        return None

    initialized = False
    try:
        pythoncom.CoInitialize()
        initialized = True
    except Exception:
        initialized = False
    shell = None
    shortcut = None
    result: str | None = None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(lnk_path))
        target = shortcut.TargetPath
        result = str(target) if target else None
    except Exception:
        result = None
    finally:
        # Release the COM objects before uninitializing so their final
        # IUnknown release does not race CoUninitialize (avoids stderr noise).
        shortcut = None
        shell = None
        if initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
    return result


def is_safe_to_surface(display_name: str | None, path: str | None) -> bool:
    """True only if a candidate item is safe to list or open.

    Rejects when the display name, the path, or (for a ``.lnk``) the resolved
    target is sensitive. Resolving the shortcut first is what stops an
    innocent-looking recent entry that actually points at a secret.
    """
    if is_sensitive_path(display_name) or is_sensitive_path(path):
        return False
    if path and str(path).lower().endswith(".lnk"):
        target = resolve_shortcut(path)
        if target and is_sensitive_path(target):
            return False
    return True
