"""Security filters for dashboard-visible files and backend file actions.

The dashboard is allowed to show ordinary recent documents, but it must never
surface secrets or follow a Windows shortcut into a sensitive target.  All
checks live on the trusted Python side; frontend filtering is only cosmetic.
"""
from __future__ import annotations

import json
import ntpath
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Iterable

_SECRET_EXACT = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credential",
    "secrets",
    "secret",
    "token",
    "tokens",
    "password",
    "passwords",
}
_SECRET_PREFIXES = (".env.", "credentials", "secrets", "token", "password")
_SECRET_EXTENSIONS = {".pem", ".key", ".pfx", ".p12", ".kdbx"}
_SECRET_DIRS = {".ssh", ".gnupg", ".aws", ".azure"}
_SAFE_DISPLAY = re.compile(r"^[^\x00-\x1f]{1,220}$")

ShortcutResolver = Callable[[Path], str | None]


def _normalized_parts(path: str | os.PathLike[str]) -> tuple[str, ...]:
    """Split a path consistently even when tests run on another platform.

    Windows drive components such as ``C:`` must remain ordinary components.
    ``pathlib.Path('C:').name`` is empty on Windows, which previously caused
    every absolute Windows path to be treated as sensitive.
    """
    raw = os.path.expandvars(os.path.expanduser(str(path))).strip()
    return tuple(
        part.strip().casefold()
        for part in re.split(r"[\\/]+", raw)
        if part.strip()
    )


def _portable_basename(value: str) -> str:
    """Return a basename without interpreting a bare Windows drive as empty."""
    raw = str(value).strip().replace("/", "\\").rstrip("\\")
    if not raw:
        return ""
    return (ntpath.basename(raw) or raw).casefold()


def is_sensitive_name(name: str) -> bool:
    """Return True when a basename resembles a secret or credential file."""
    cleaned = _portable_basename(name)
    if not cleaned:
        return True
    if cleaned in _SECRET_EXACT:
        return True
    if cleaned.startswith(_SECRET_PREFIXES):
        return True
    return ntpath.splitext(cleaned)[1] in _SECRET_EXTENSIONS


def is_sensitive_path(path: str | os.PathLike[str]) -> bool:
    """Check every path component, not only the final basename."""
    parts = _normalized_parts(path)
    if not parts:
        return True
    if any(part in _SECRET_DIRS for part in parts):
        return True
    return any(is_sensitive_name(part) for part in parts)


def _resolve_with_pywin32(shortcut: Path) -> str | None:
    try:  # pragma: no cover - Windows/pywin32 dependent
        import pythoncom
        from win32com.shell import shell

        initialized = False
        try:
            pythoncom.CoInitialize()
            initialized = True
            link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(shortcut))
            target = link.GetPath(shell.SLGP_RAWPATH)[0] or ""
            return os.path.expandvars(target).strip() or None
        finally:
            if initialized:
                pythoncom.CoUninitialize()
    except Exception:
        return None


def _resolve_with_powershell(shortcut: Path) -> str | None:
    if os.name != "nt":
        return None
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]);"
        "@{target=$s.TargetPath;arguments=$s.Arguments}|ConvertTo-Json -Compress"
    )
    try:  # pragma: no cover - Windows dependent
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(shortcut)],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        payload = json.loads(result.stdout.strip())
        target = os.path.expandvars(str(payload.get("target", ""))).strip()
        return target or None
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None



def _resolve_many_with_powershell(shortcuts: list[Path]) -> dict[Path, str]:
    if os.name != "nt" or not shortcuts:
        return {}
    script = (
        "$w=New-Object -ComObject WScript.Shell;$o=@();"
        "foreach($p in $args){try{$s=$w.CreateShortcut($p);"
        "$o+=[pscustomobject]@{path=$p;target=$s.TargetPath}}catch{}};"
        "$o|ConvertTo-Json -Compress"
    )
    resolved: dict[Path, str] = {}
    # Keep the Windows command line comfortably below its length limit.
    for offset in range(0, len(shortcuts), 40):
        chunk = shortcuts[offset : offset + 40]
        try:  # pragma: no cover - Windows dependent
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, *map(str, chunk)],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            payload = json.loads(result.stdout.strip())
            rows = [payload] if isinstance(payload, dict) else payload
            for row in rows if isinstance(rows, list) else []:
                source = Path(str(row.get("path", "")))
                target = os.path.expandvars(str(row.get("target", ""))).strip()
                if source and target:
                    resolved[source] = target
        except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
            continue
    return resolved


def resolve_shortcut_targets(shortcuts: Iterable[Path]) -> dict[Path, str]:
    """Resolve many shortcuts efficiently and fail closed for unresolved items."""
    items = [Path(item) for item in shortcuts if Path(item).suffix.casefold() == ".lnk"]
    resolved: dict[Path, str] = {}
    unresolved: list[Path] = []
    for shortcut in items:
        target = _resolve_with_pywin32(shortcut)
        if target:
            resolved[shortcut] = target
        else:
            unresolved.append(shortcut)
    resolved.update(_resolve_many_with_powershell(unresolved))
    return resolved

def resolve_shortcut_target(shortcut: Path) -> str | None:
    """Resolve a .lnk target without exposing it to the browser or logs."""
    if shortcut.suffix.casefold() != ".lnk":
        return str(shortcut)
    return resolve_shortcut_targets([shortcut]).get(shortcut)


def safe_recent_target(
    shortcut: Path,
    resolver: ShortcutResolver | None = None,
) -> tuple[str, str] | None:
    """Return (safe display name, trusted launch target) or None.

    A .lnk is rejected when it cannot be resolved.  This fail-closed behavior
    prevents a harmless-looking shortcut from pointing to an .env, key file,
    credential store, or secret directory.
    """
    display_name = shortcut.stem.strip()
    if not _SAFE_DISPLAY.match(display_name) or is_sensitive_name(display_name):
        return None
    resolver = resolver or resolve_shortcut_target
    target = resolver(shortcut)
    if not target or is_sensitive_path(target):
        return None
    target_name = _portable_basename(target)
    if is_sensitive_name(target_name):
        return None
    return display_name, target


def can_open_recent_target(target: str) -> bool:
    """Final backend guard immediately before opening a recent item."""
    return bool(target) and not is_sensitive_path(target)
