"""Canonical NOVA capability identity and metadata -- tool-free.

This is NOVA's single declaration of which capabilities exist and their
static metadata: name, description, permission/tag/risk classification, and
default activation. It intentionally holds no tool references, so importing
it never pulls in any ``tools/*`` module.

``nova_os.catalog.build_default_capability_manager()`` consumes this list and
attaches each capability's concrete tool objects (which does require
importing ``tools/*``); it must not redeclare capability identity or
metadata a second time -- only which tools implement each id.

Lightweight callers that only need to know which capability ids are real --
e.g. NOVA Lab feature registration -- import ``CANONICAL_CAPABILITY_IDS``
from here (or from ``nova_os.capabilities``, which re-exports it) without
importing ``nova_os.catalog`` or any tool module.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """One capability's identity and metadata, with no tool references."""

    capability_id: str
    name: str
    description: str
    permissions: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    risk: str = "read_only"
    default_active: bool = False
    locked_active: bool = False


CAPABILITY_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        capability_id="system",
        name="System Information",
        description="Time, weather, CPU, RAM, disk, and battery information.",
        permissions=("system_read", "internet_read"),
        tags=("system", "weather", "time", "computer"),
        risk="read_only",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="web",
        name="Web Research",
        description=(
            "Search, read, inspect, extract from, and safely download public "
            "web resources."
        ),
        permissions=("internet_read", "downloads_write"),
        tags=("internet", "search", "research", "browser", "download"),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="desktop",
        name="Windows Desktop",
        description="Open approved apps/sites and manage visible Windows desktop state.",
        permissions=("desktop_read", "desktop_change"),
        tags=("windows", "apps", "desktop", "window"),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="files",
        name="Files and Notes",
        description="Find, read, open, and create files in NOVA-approved locations.",
        permissions=("files_read", "files_write_approved"),
        tags=("files", "folders", "notes", "documents"),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="media",
        name="Media Control",
        description="Spotify, YouTube, media keys, volume, and current-song controls.",
        permissions=("media_control",),
        tags=("music", "spotify", "youtube", "volume", "media"),
        risk="reversible",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="class_intelligence",
        name="Class Intelligence",
        description=(
            "Record lectures in the background, inspect the active transcript, "
            "mark important moments, and gracefully finalize class sessions while "
            "the same NOVA agent remains conversational."
        ),
        permissions=("microphone_capture", "class_notes_write"),
        tags=(
            "class",
            "lecture",
            "record",
            "transcript",
            "notes",
            "school",
            "questions",
            "multitasking",
        ),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="development",
        name="NOVA Lab Development",
        description=(
            "Inspect and register existing isolated NOVA Lab experiments, run "
            "their approved test profile as a background job, inspect durable "
            "test evidence, and prepare an exact passing commit as a CANDIDATE. "
            "Cannot promote to ACTIVE, retire, restart, roll back, delete, run "
            "shell commands, edit production, or run anything but a named "
            "approved test profile."
        ),
        permissions=(
            "lab_read",
            "lab_registry_write",
            "lab_test_execute",
            "lab_candidate_prepare",
        ),
        tags=(
            "nova lab",
            "lab feature",
            "experiment registry",
            "feature lifecycle",
            "candidate preparation",
            "background jobs",
            "test evidence",
        ),
        risk="mixed",
        default_active=False,
    ),
    CapabilityDefinition(
        capability_id="specialist",
        name="Specialist Models",
        description=(
            "Route substantial coding, architecture, analysis, or private local "
            "work to a specialist model."
        ),
        permissions=("model_routing",),
        tags=("coding", "reasoning", "specialist", "ollama", "openai", "groq"),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="memory",
        name="Memory and Conversation History",
        description=(
            "NOVA Vault second brain: search, read, organize, and safely save "
            "persistent knowledge and text files."
        ),
        permissions=("memory_read", "memory_write"),
        tags=(
            "memory",
            "obsidian",
            "second brain",
            "vault",
            "history",
            "notes",
            "projects",
            "decisions",
        ),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="email_calendar",
        name="Email and Calendar",
        description=(
            "Read-only connected email/calendar synchronization, search, agenda, "
            "and briefing tools."
        ),
        permissions=("account_metadata_read", "private_content_read"),
        tags=("gmail", "outlook", "email", "calendar", "agenda"),
        risk="sensitive_read",
        default_active=False,
    ),
    CapabilityDefinition(
        capability_id="guardian",
        name="Guardian Security",
        description="Read NOVA Guardian status and security alerts without screenshot capture.",
        permissions=("security_read",),
        tags=("security", "guardian", "alerts"),
        risk="read_only",
        default_active=False,
    ),
    CapabilityDefinition(
        capability_id="skills",
        name="Skills Engine",
        description=(
            "Load reusable workflows and explicitly save/update user-authored "
            "declarative skills."
        ),
        permissions=("skills_read", "skills_write_user"),
        tags=("skills", "learn", "workflow", "reuse", "research"),
        risk="mixed",
        default_active=True,
    ),
    CapabilityDefinition(
        capability_id="permissions",
        name="Permission Controls",
        description="List/deny pending actions and enable Safe Mode. Approval is never model-callable.",
        permissions=("permission_read", "permission_restrict"),
        tags=("permissions", "safe mode", "security", "approval"),
        risk="restrictive_only",
        default_active=True,
        locked_active=True,
    ),
)


CANONICAL_CAPABILITY_IDS: frozenset[str] = frozenset(
    definition.capability_id for definition in CAPABILITY_DEFINITIONS
)
