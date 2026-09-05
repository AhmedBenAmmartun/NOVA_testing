"""NOVA Lab: controlled feature-development lifecycle primitives."""

from .history import LifecycleJournal
from .models import FeatureRecord, FeatureState, InvalidTransitionError
from .registry import FeatureRegistry, RegistryConflictError
from .testing import ApprovedTestRunner, TestRunResult
from .workspace import GitWorkspace, WorkspaceSafetyError

__all__ = [
    "ApprovedTestRunner",
    "FeatureRecord",
    "FeatureRegistry",
    "FeatureState",
    "GitWorkspace",
    "InvalidTransitionError",
    "LifecycleJournal",
    "RegistryConflictError",
    "TestRunResult",
    "WorkspaceSafetyError",
]
