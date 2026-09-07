"""NOVA Core Intelligence A1.

Read-only awareness primitives: ProjectState, provenance/freshness, conservative
project resolution, failed-approach awareness, context brokering, and shadow
evaluation. A1 does not add release, Git-write, production, or approval authority.
"""

from .context_broker import ContextBroker
from .models import ContextPacket, Fact, FactStatus, ProjectState, ProvenanceRef
from .project_state import ProjectStateBuilder
from .resolver import ProjectCandidate, ProjectResolver, ResolutionDecision, ResolutionStatus
from .shadow_eval import (
    ShadowEvaluationRecord,
    ShadowEvaluationStore,
    ShadowMetrics,
    compute_shadow_metrics,
)

__all__ = [
    "ContextBroker",
    "ContextPacket",
    "Fact",
    "FactStatus",
    "ProjectCandidate",
    "ProjectResolver",
    "ProjectState",
    "ProjectStateBuilder",
    "ProvenanceRef",
    "ResolutionDecision",
    "ResolutionStatus",
    "ShadowEvaluationRecord",
    "ShadowEvaluationStore",
    "ShadowMetrics",
    "compute_shadow_metrics",
]
