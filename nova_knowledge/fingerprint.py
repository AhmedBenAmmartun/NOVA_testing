from __future__ import annotations

from pathlib import Path
import hashlib


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def short_material_id(sha256: str) -> str:
    cleaned = sha256.strip().lower()
    if len(cleaned) < 16:
        raise ValueError("sha256 fingerprint is too short")
    return f"mat_{cleaned[:16]}"
