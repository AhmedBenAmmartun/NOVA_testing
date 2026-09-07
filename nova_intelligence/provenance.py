from __future__ import annotations

import hashlib
from pathlib import Path

from .models import ProvenanceRef, utc_now_iso


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        # Provenance should identify the evidence class without leaking an
        # absolute user-profile path into model context.
        return f"<external>/{path.name}"


def file_provenance(
    path: Path | str,
    *,
    root: Path | str,
    source_kind: str = "file",
    max_hash_bytes: int = 2_000_000,
    note: str = "",
) -> ProvenanceRef:
    target = Path(path)
    root_path = Path(root)
    observed_at = utc_now_iso()
    digest = ""
    extra_note = note

    try:
        data = target.read_bytes()
        if len(data) <= max_hash_bytes:
            digest = sha256_bytes(data)
        else:
            digest = sha256_bytes(data[:max_hash_bytes])
            suffix = f"sha256 covers first {max_hash_bytes} of {len(data)} bytes"
            extra_note = f"{extra_note}; {suffix}".strip("; ")
    except OSError as exc:
        extra = f"unreadable:{type(exc).__name__}"
        extra_note = f"{extra_note}; {extra}".strip("; ")

    return ProvenanceRef(
        source_kind=source_kind,
        source=safe_relative(target, root_path),
        observed_at=observed_at,
        digest=digest,
        note=extra_note,
    )


def observation_provenance(
    source_kind: str,
    source: str,
    payload: str | bytes = b"",
    *,
    note: str = "",
) -> ProvenanceRef:
    raw = payload.encode("utf-8", errors="replace") if isinstance(payload, str) else bytes(payload)
    return ProvenanceRef(
        source_kind=str(source_kind),
        source=str(source),
        observed_at=utc_now_iso(),
        digest=sha256_bytes(raw) if raw else "",
        note=str(note),
    )
