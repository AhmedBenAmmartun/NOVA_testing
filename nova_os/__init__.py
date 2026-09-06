"""NOVA OS capability kernel."""

from .capabilities import (
    CANONICAL_CAPABILITY_IDS,
    CapabilityManager,
    CapabilityRegistry,
    CapabilitySpec,
)
from .skills import SkillRegistry, SkillSpec, build_default_skill_registry

__all__ = [
    "CANONICAL_CAPABILITY_IDS",
    "CapabilityManager",
    "CapabilityRegistry",
    "CapabilitySpec",
    "build_default_capability_manager",
    "SkillRegistry",
    "SkillSpec",
    "build_default_skill_registry",
]


def __getattr__(name: str):
    # nova_os.catalog imports every tools/* module (and, through
    # tools.development, nova_lab.service) to wire concrete tool objects
    # into each CapabilitySpec. Importing it eagerly here would make merely
    # importing nova_os -- e.g. to read CANONICAL_CAPABILITY_IDS -- circular
    # for nova_lab.service, and would force every tool module to load just
    # to validate a capability id. Deferred to first access instead.
    if name == "build_default_capability_manager":
        from .catalog import build_default_capability_manager

        return build_default_capability_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
