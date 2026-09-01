from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PureWindowsPath
from typing import Any
import re


_SECRET_KEY_PARTS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "token",
    "password",
    "passwd",
    "authorization",
    "cookie",
    "client_secret",
}

_CONTENT_KEY_PARTS = {
    "content",
    "file_content",
    "file_contents",
    "screen_text",
    "screenshot_text",
    "transcript",
    "class_transcript",
    "raw_audio",
    "audio_bytes",
    "image_bytes",
}

_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|client[_-]?secret|password|token)\s*[:=]\s*([^\s,;]+)"
)


def _normalized_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_")


def _redact_string(value: str, *, max_chars: int) -> str:
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    value = _SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}=<redacted>", value)
    if len(value) > max_chars:
        return value[:max_chars] + "…<truncated>"
    return value


def redact(value: Any, *, max_string_chars: int = 500) -> Any:
    """Return a JSON-safe, privacy-reduced representation before persistence.

    The function intentionally removes secret-bearing fields and high-volume raw
    content such as transcripts, screen text, file bodies, audio, and images.
    Paths are reduced to filenames where practical so routing/file-operation
    patterns remain useful without retaining full local paths.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, Path):
        return f"file:{value.name}"

    if isinstance(value, bytes):
        return f"<bytes:{len(value)} redacted>"

    if isinstance(value, str):
        return _redact_string(value, max_chars=max_string_chars)

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            normalized = _normalized_key(raw_key)
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                out[key] = "<redacted>"
                continue
            if any(part in normalized for part in _CONTENT_KEY_PARTS):
                if normalized in {"transcript", "class_transcript"}:
                    out[key] = "<transcript redacted>"
                else:
                    out[key] = "<content redacted>"
                continue
            if normalized.endswith("path") or normalized.endswith("file"):
                if isinstance(raw_value, (str, Path)):
                    raw_path = str(raw_value)
                    if raw_path.startswith("file:"):
                        out[key] = raw_path
                        continue
                    name = (
                        PureWindowsPath(raw_path).name
                        if "\\" in raw_path
                        else Path(raw_path).name
                    )
                    out[key] = f"file:{name}"
                    continue
            out[key] = redact(raw_value, max_string_chars=max_string_chars)
        return out

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact(item, max_string_chars=max_string_chars) for item in value]

    # Avoid arbitrary object serialization or reprs that may expose internals.
    return f"<{type(value).__name__}>"
