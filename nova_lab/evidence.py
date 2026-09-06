"""Durable NOVA Lab test evidence.

Evidence is an immutable fact: "this exact commit ran this exact approved
test profile and got this exact result." It is append-only, tied to a
specific feature and commit SHA, and never becomes valid for a different
commit merely because the feature id matches -- candidate gating depends on
that guarantee (see `nova_lab.registry.FeatureRegistry.enter_candidate`).

Raw stdout/stderr are never persisted here. Only a short, sanitized, bounded
summary is kept -- enough to see what gate ran, not a dump of process output.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_MAX_SUMMARY = 400

_SENSITIVE_TERMS = (
    ".env",
    "password",
    "api key",
    "api_key",
    "secret",
    "access token",
    "refresh token",
    ".spotify_cache",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_summary(text: str) -> str:
    """Collapse whitespace, redact anything secret-shaped, and bound length."""
    cleaned = " ".join(str(text).replace("\r", " ").replace("\n", " ").split())
    if any(term in cleaned.lower() for term in _SENSITIVE_TERMS):
        return "[sensitive test output redacted]"
    return cleaned[:_MAX_SUMMARY]


def summarize_test_output(*, returncode: int, stdout: str) -> str:
    """A short, safe summary of a test run: its own final summary line only."""
    lines = [line for line in (stdout or "").splitlines() if line.strip()]
    tail = lines[-1] if lines else "(no output)"
    return safe_summary(f"returncode={returncode}: {tail}")


@dataclass(frozen=True, slots=True)
class TestEvidenceRecord:
    """One immutable fact about one approved test run against one commit."""

    evidence_id: str
    feature_id: str
    capability_id: str
    commit_sha: str
    branch: str
    test_profile: str
    passed: bool
    returncode: int
    started_at: str
    completed_at: str
    summary: str = ""
    job_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TestEvidenceRecord":
        return cls(**dict(data))


class TestEvidenceStore:
    """Append-only durable evidence log. Records are never mutated in place."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def record(self, evidence: TestEvidenceRecord) -> TestEvidenceRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(evidence.to_dict(), ensure_ascii=False) + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        return evidence

    def get(self, evidence_id: str) -> TestEvidenceRecord | None:
        for record in self._read_all():
            if record.evidence_id == evidence_id:
                return record
        return None

    def list_for_feature(self, feature_id: str) -> tuple[TestEvidenceRecord, ...]:
        return tuple(
            record for record in self._read_all() if record.feature_id == feature_id
        )

    def _read_all(self) -> list[TestEvidenceRecord]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []

        records: list[TestEvidenceRecord] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            try:
                records.append(TestEvidenceRecord.from_dict(data))
            except TypeError:
                continue
        return records
