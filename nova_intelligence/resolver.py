from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import re
from typing import Iterable


class ResolutionStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class ProjectCandidate:
    project_id: str
    name: str
    root: Path
    aliases: tuple[str, ...] = ()

    def normalized_aliases(self) -> frozenset[str]:
        values = {self.project_id, self.name, self.root.name, *self.aliases}
        return frozenset(_normalize(value) for value in values if _normalize(value))


@dataclass(frozen=True, slots=True)
class ResolutionDecision:
    status: ResolutionStatus
    project_id: str | None
    root: Path | None
    confidence: float
    reason: str

    @property
    def safe_for_protected_decision(self) -> bool:
        return self.status is ResolutionStatus.VERIFIED and self.root is not None


def _normalize(value: object) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


class ProjectResolver:
    """Conservative resolver over explicitly supplied projects only.

    A1 deliberately does not crawl disks, fuzzy-match neighboring projects, or
    infer a project from memory. Exact path/alias evidence or a unique cwd
    containment match is required. Otherwise the result is UNKNOWN/AMBIGUOUS.
    """

    def __init__(self, candidates: Iterable[ProjectCandidate]) -> None:
        self._candidates = tuple(candidates)

    def resolve(
        self,
        requested: str | Path | None = None,
        *,
        cwd: Path | None = None,
    ) -> ResolutionDecision:
        if not self._candidates:
            return ResolutionDecision(
                ResolutionStatus.UNKNOWN,
                None,
                None,
                0.0,
                "no explicit project candidates are configured",
            )

        if requested is not None and str(requested).strip():
            raw = str(requested).strip()
            requested_path = Path(raw).expanduser()
            path_matches = [
                item
                for item in self._candidates
                if requested_path.is_absolute() and requested_path.resolve() == item.root.resolve()
            ]
            if len(path_matches) == 1:
                item = path_matches[0]
                return ResolutionDecision(
                    ResolutionStatus.VERIFIED,
                    item.project_id,
                    item.root.resolve(),
                    1.0,
                    "exact project root path match",
                )
            if len(path_matches) > 1:
                return ResolutionDecision(
                    ResolutionStatus.AMBIGUOUS,
                    None,
                    None,
                    0.0,
                    "multiple candidates share the requested root",
                )

            normalized = _normalize(raw)
            alias_matches = [
                item for item in self._candidates if normalized in item.normalized_aliases()
            ]
            if len(alias_matches) == 1:
                item = alias_matches[0]
                return ResolutionDecision(
                    ResolutionStatus.VERIFIED,
                    item.project_id,
                    item.root.resolve(),
                    1.0,
                    "exact configured project alias match",
                )
            if len(alias_matches) > 1:
                return ResolutionDecision(
                    ResolutionStatus.AMBIGUOUS,
                    None,
                    None,
                    0.0,
                    "requested alias maps to multiple configured projects",
                )
            return ResolutionDecision(
                ResolutionStatus.UNKNOWN,
                None,
                None,
                0.0,
                "requested project did not exactly match a configured project",
            )

        if cwd is not None:
            matches = [item for item in self._candidates if _is_inside(cwd, item.root)]
            if len(matches) == 1:
                item = matches[0]
                return ResolutionDecision(
                    ResolutionStatus.VERIFIED,
                    item.project_id,
                    item.root.resolve(),
                    1.0,
                    "cwd is contained by exactly one configured project root",
                )
            if len(matches) > 1:
                return ResolutionDecision(
                    ResolutionStatus.AMBIGUOUS,
                    None,
                    None,
                    0.0,
                    "cwd is contained by more than one configured project root",
                )

        if len(self._candidates) == 1:
            item = self._candidates[0]
            return ResolutionDecision(
                ResolutionStatus.VERIFIED,
                item.project_id,
                item.root.resolve(),
                0.95,
                "only one explicitly configured project candidate exists",
            )

        return ResolutionDecision(
            ResolutionStatus.UNKNOWN,
            None,
            None,
            0.0,
            "multiple projects are configured and none has exact resolving evidence",
        )
