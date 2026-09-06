"""NOVA OS capability registry and dynamic tool manager.

This module is intentionally independent from individual tool implementations.
It groups LiveKit function tools into named capabilities and lets the active
Agent replace its tool context at runtime with ``Agent.update_tools()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from livekit.agents.llm import Toolset

from .capability_definitions import CANONICAL_CAPABILITY_IDS


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    """One named NOVA capability and its tool surface."""

    capability_id: str
    name: str
    description: str
    tools: tuple[object, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    risk: str = "read_only"
    default_active: bool = False
    locked_active: bool = False

    @property
    def tool_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for tool in self.tools:
            tool_id = getattr(tool, "id", None)
            if tool_id:
                names.append(str(tool_id))
                continue
            name = getattr(tool, "__name__", None)
            if name:
                names.append(str(name))
        return tuple(names)


# CANONICAL_CAPABILITY_IDS is re-exported (imported above) from
# nova_os.capability_definitions, the single tool-free source of capability
# identity. It is not redeclared here.


class CapabilityRegistry:
    """In-memory catalog of all capabilities known to this NOVA runtime."""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        capability_id = self.normalize_id(spec.capability_id)
        if not capability_id:
            raise ValueError("Capability id cannot be empty")
        if capability_id in self._specs:
            raise ValueError(f"Duplicate capability id: {capability_id}")

        normalized = CapabilitySpec(
            capability_id=capability_id,
            name=spec.name.strip(),
            description=spec.description.strip(),
            tools=tuple(spec.tools),
            permissions=tuple(spec.permissions),
            tags=tuple(spec.tags),
            risk=spec.risk.strip().lower() or "read_only",
            default_active=bool(spec.default_active),
            locked_active=bool(spec.locked_active),
        )
        self._specs[capability_id] = normalized

    @staticmethod
    def normalize_id(value: str) -> str:
        return value.strip().lower().replace("-", "_").replace(" ", "_")

    def get(self, capability_id: str) -> CapabilitySpec | None:
        return self._specs.get(self.normalize_id(capability_id))

    def all(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs[key] for key in sorted(self._specs))

    def search(self, query: str) -> tuple[CapabilitySpec, ...]:
        cleaned = query.strip().lower()
        if not cleaned:
            return self.all()

        tokens = [token for token in cleaned.replace("-", " ").split() if token]
        scored: list[tuple[int, CapabilitySpec]] = []

        for spec in self._specs.values():
            haystack = " ".join(
                (
                    spec.capability_id,
                    spec.name,
                    spec.description,
                    " ".join(spec.tags),
                    " ".join(spec.tool_names),
                )
            ).lower()
            score = sum(1 for token in tokens if token in haystack)
            if score:
                scored.append((score, spec))

        scored.sort(key=lambda item: (-item[0], item[1].capability_id))
        return tuple(spec for _, spec in scored)


class CapabilityManager:
    """Track active capabilities and produce LiveKit tool/toolset contexts."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        control_tools: Sequence[object],
    ) -> None:
        self.registry = registry
        self._control_tools = tuple(control_tools)
        self._active: set[str] = {
            spec.capability_id
            for spec in registry.all()
            if spec.default_active or spec.locked_active
        }

    @property
    def active_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._active))

    def is_active(self, capability_id: str) -> bool:
        normalized = self.registry.normalize_id(capability_id)
        return normalized in self._active

    def activate(self, capability_id: str) -> str:
        spec = self.registry.get(capability_id)
        if spec is None:
            return (
                f"Unknown capability '{capability_id}'. Use search_capabilities "
                "or list_capabilities to find the correct capability."
            )
        if spec.capability_id in self._active:
            return f"Capability '{spec.capability_id}' is already active."
        self._active.add(spec.capability_id)
        return f"Activated capability '{spec.capability_id}' ({spec.name})."

    def deactivate(self, capability_id: str) -> str:
        spec = self.registry.get(capability_id)
        if spec is None:
            return (
                f"Unknown capability '{capability_id}'. Use search_capabilities "
                "or list_capabilities to find the correct capability."
            )
        if spec.locked_active:
            return f"Capability '{spec.capability_id}' is required and cannot be deactivated."
        if spec.capability_id not in self._active:
            return f"Capability '{spec.capability_id}' is already inactive."
        self._active.remove(spec.capability_id)
        return f"Deactivated capability '{spec.capability_id}'."

    def build_tool_context(self) -> list[object]:
        """Return capability-control tools plus active LiveKit toolsets."""

        tools: list[object] = list(self._control_tools)
        for capability_id in self.active_ids:
            spec = self.registry.get(capability_id)
            if spec is None or not spec.tools:
                continue
            tools.append(
                Toolset(
                    id=f"nova_{spec.capability_id}",
                    tools=list(spec.tools),
                )
            )
        return tools

    def list_text(self) -> str:
        lines = ["NOVA capabilities:"]
        for spec in self.registry.all():
            state = "active" if spec.capability_id in self._active else "inactive"
            lock = ", required" if spec.locked_active else ""
            lines.append(
                f"- {spec.capability_id}: {spec.name} [{state}{lock}; risk={spec.risk}] - "
                f"{spec.description}"
            )
        return "\n".join(lines)

    def active_text(self) -> str:
        if not self._active:
            return "No optional NOVA capabilities are currently active."
        lines = ["Active NOVA capabilities:"]
        for capability_id in self.active_ids:
            spec = self.registry.get(capability_id)
            if spec:
                lines.append(f"- {spec.capability_id}: {spec.name}")
        return "\n".join(lines)

    def search_text(self, query: str) -> str:
        matches = self.registry.search(query)
        if not matches:
            return f"No NOVA capability matched '{query}'."
        lines = [f"Capabilities matching '{query}':"]
        for spec in matches[:8]:
            state = "active" if spec.capability_id in self._active else "inactive"
            lines.append(
                f"- {spec.capability_id}: {spec.name} [{state}] - {spec.description}"
            )
        return "\n".join(lines)

    def info_text(self, capability_id: str) -> str:
        spec = self.registry.get(capability_id)
        if spec is None:
            return f"Unknown capability '{capability_id}'."
        state = "active" if spec.capability_id in self._active else "inactive"
        tools = ", ".join(spec.tool_names) if spec.tool_names else "none"
        permissions = ", ".join(spec.permissions) if spec.permissions else "none"
        tags = ", ".join(spec.tags) if spec.tags else "none"
        return (
            f"Capability: {spec.capability_id}\n"
            f"Name: {spec.name}\n"
            f"State: {state}\n"
            f"Risk: {spec.risk}\n"
            f"Description: {spec.description}\n"
            f"Permissions: {permissions}\n"
            f"Tags: {tags}\n"
            f"Tools: {tools}"
        )
