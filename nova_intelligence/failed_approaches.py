from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from .provenance import file_provenance


_SIGNAL = re.compile(
    r"\b(failed|failure|root cause|superseded|did not work|does not work|"
    r"blocked|regression|rejected|do not use|do not assume|broken)\b",
    re.IGNORECASE,
)

_DEFAULT_ROOT_DOCS = (
    "AGENTS.md",
    "DEVELOPMENT.md",
    "ROADMAP.md",
    "AGENT_COORDINATION.md",
)


_SECRET_PATTERNS = (
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{16,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "[REDACTED_TOKEN]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED_TOKEN]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|api[_-]?secret|client[_-]?secret|"
            r"access[_-]?token|refresh[_-]?token)\s*[:=]\s*\S+"
        ),
        r"\1=[REDACTED]",
    ),
)


def _redact_sensitive(text: str) -> str:
    value = text
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _clean_markdown(text: str) -> str:
    value = text.strip()
    value = re.sub(r"^[#>*+\-\d.\s]+", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


@dataclass(frozen=True, slots=True)
class FailedApproach:
    text: str
    source: str
    line: int
    category: str
    provenance: dict[str, str]

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "source": self.source,
            "line": self.line,
            "category": self.category,
            "provenance": dict(self.provenance),
        }


class FailedApproachIndex:
    """Read-only bounded extraction of explicitly failure-marked documentation."""

    def __init__(
        self,
        project_root: Path | str,
        *,
        max_files: int = 80,
        max_file_bytes: int = 250_000,
        max_items: int = 24,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.max_files = max(1, int(max_files))
        self.max_file_bytes = max(1_000, int(max_file_bytes))
        self.max_items = max(1, int(max_items))

    def _candidate_paths(self, extra_paths: Iterable[Path | str] = ()) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for name in _DEFAULT_ROOT_DOCS:
            path = self.project_root / name
            if path.is_file():
                candidates.append(path)

        docs = self.project_root / "docs"
        if docs.is_dir():
            candidates.extend(sorted(docs.rglob("*.md")))

        for raw in extra_paths:
            path = Path(raw)
            if not path.is_absolute():
                path = self.project_root / path
            if path.is_file():
                candidates.append(path.resolve())

        unique: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(path.resolve())
            if len(unique) >= self.max_files:
                break
        return tuple(unique)

    @staticmethod
    def _category(text: str) -> str:
        lowered = text.casefold()
        if "root cause" in lowered:
            return "root_cause"
        if "superseded" in lowered:
            return "superseded"
        if "blocked" in lowered:
            return "blocked"
        if "regression" in lowered or "broken" in lowered:
            return "regression"
        if "do not" in lowered:
            return "avoid"
        return "failed"

    def scan(self, extra_paths: Iterable[Path | str] = ()) -> tuple[FailedApproach, ...]:
        items: list[FailedApproach] = []
        seen: set[str] = set()

        for path in self._candidate_paths(extra_paths):
            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                continue

            in_fence = False
            provenance = file_provenance(
                path,
                root=self.project_root,
                source_kind="documentation",
                note="explicit failure-signal extraction",
            )
            prov_dict = provenance.as_dict()

            for index, raw in enumerate(lines, start=1):
                stripped = raw.strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    continue
                if in_fence or not _SIGNAL.search(raw):
                    continue

                cleaned = _redact_sensitive(_clean_markdown(raw))
                if len(cleaned) < 12:
                    continue
                cleaned = cleaned[:320]
                key = _norm(cleaned)
                if not key or key in seen:
                    continue
                seen.add(key)

                items.append(
                    FailedApproach(
                        text=cleaned,
                        source=provenance.source,
                        line=index,
                        category=self._category(cleaned),
                        provenance=prov_dict,
                    )
                )
                if len(items) >= self.max_items:
                    return tuple(items)

        return tuple(items)
