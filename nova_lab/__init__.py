"""NOVA Lab: controlled feature-development lifecycle primitives."""

from .evidence import TestEvidenceRecord, TestEvidenceStore
from .history import LifecycleJournal
from .models import FeatureRecord, FeatureState, InvalidTransitionError
from .registry import FeatureRegistry, RegistryConflictError
from .service import DevelopmentService, default_labs_root
from .testing import ApprovedTestRunner, TestRunResult
from .workspace import GitWorkspace, WorkspaceSafetyError

__all__ = [
    "ApprovedTestRunner",
    "FeatureRecord",
    "FeatureRegistry",
    "FeatureState",
    "DevelopmentService",
    "GitWorkspace",
    "InvalidTransitionError",
    "LifecycleJournal",
    "RegistryConflictError",
    "TestEvidenceRecord",
    "TestEvidenceStore",
    "TestRunResult",
    "WorkspaceSafetyError",
    "default_labs_root",
]
