from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
import time
import uuid


Modality = Literal["voice", "text", "screen"]
Outcome = Literal["success", "failure", "partial", "unknown"]


@dataclass(slots=True)
class ToolCall:
    """Observed execution of one NOVA tool/capability call."""

    name: str
    args: dict[str, Any]
    ok: bool
    latency_ms: int
    error: str | None = None
    retries: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Experience:
    """One meaningful NOVA user turn and the evidence needed to evaluate it."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    # What came in.
    intent: str = ""
    utterance_redacted: str = ""
    modality: Modality = "voice"

    # How NOVA handled it.
    route: str = ""
    model: str = ""
    tools: list[ToolCall] = field(default_factory=list)

    # What happened.
    outcome: Outcome = "unknown"
    outcome_source: str = ""
    outcome_score: float = 0.0
    latency_ms: int = 0

    # Learning signals.
    user_correction: str | None = None
    correction_ts: float | None = None
    self_confidence: float = 0.0
    strategy_versions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["schema_version"] = 1
        return payload
