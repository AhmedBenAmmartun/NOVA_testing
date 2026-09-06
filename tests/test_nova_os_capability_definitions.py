"""Capability identity must have exactly one canonical, tool-free source.

nova_os.capability_definitions.CAPABILITY_DEFINITIONS is that source. This
file pins that nothing else re-declares capability identity, and that the
tool-wired catalog and the canonical id set can never silently diverge.
"""

from __future__ import annotations

from nova_os.capabilities import CANONICAL_CAPABILITY_IDS
from nova_os.capability_definitions import CAPABILITY_DEFINITIONS
from nova_os.catalog import build_default_capability_manager


def test_canonical_ids_have_no_duplicates() -> None:
    ids = [definition.capability_id for definition in CAPABILITY_DEFINITIONS]
    assert len(ids) == len(set(ids))


def test_canonical_capability_ids_is_derived_from_definitions() -> None:
    assert CANONICAL_CAPABILITY_IDS == frozenset(
        definition.capability_id for definition in CAPABILITY_DEFINITIONS
    )


def test_capabilities_module_reexports_the_same_object() -> None:
    """nova_os.capabilities must re-export, never redeclare, the canonical set."""
    from nova_os import capability_definitions, capabilities

    assert capabilities.CANONICAL_CAPABILITY_IDS is capability_definitions.CANONICAL_CAPABILITY_IDS


def test_catalog_tool_wiring_matches_every_canonical_id_exactly() -> None:
    """A capability defined without tool wiring (or wired without being
    defined) must fail loudly at manager construction, not silently."""
    manager = build_default_capability_manager()
    wired_ids = frozenset(spec.capability_id for spec in manager.registry.all())
    assert wired_ids == CANONICAL_CAPABILITY_IDS


def test_definitions_do_not_reference_tool_objects() -> None:
    """Identity/metadata definitions must stay tool-free -- tool wiring is
    nova_os.catalog's job alone, so a capability can never be declared twice."""
    for definition in CAPABILITY_DEFINITIONS:
        assert not hasattr(definition, "tools")


def test_locked_permissions_capability_is_still_locked_and_required() -> None:
    permissions = next(
        definition
        for definition in CAPABILITY_DEFINITIONS
        if definition.capability_id == "permissions"
    )
    assert permissions.locked_active is True
    assert permissions.default_active is True


def test_development_capability_is_inactive_by_default_in_the_canonical_source() -> None:
    development = next(
        definition
        for definition in CAPABILITY_DEFINITIONS
        if definition.capability_id == "development"
    )
    assert development.default_active is False
