"""Default NOVA OS capability catalog built from the project's current tools."""

from __future__ import annotations

from nova_os.capabilities import CapabilityManager, CapabilityRegistry, CapabilitySpec
from nova_os.capability_definitions import CAPABILITY_DEFINITIONS
from tools.capabilities import CAPABILITY_CONTROL_TOOLS
from tools.core_intelligence import CORE_INTELLIGENCE_TOOLS
from tools.class_capture import CLASS_CAPTURE_TOOLS
from tools.conversations import read_conversation_history, search_conversation_history
from tools.development import DEVELOPMENT_TOOLS
from tools.desktop import (
    close_app,
    control_window,
    is_app_running,
    manage_virtual_desktop,
    open_app,
    open_notifications,
    open_quick_settings,
    open_website,
    restart_app,
)
from tools.email_calendar import (
    find_calendar_conflicts,
    get_calendar_agenda,
    get_daily_briefing,
    get_next_event,
    get_unread_emails,
    list_connected_accounts,
    read_email,
    sync_email_calendar,
)
from tools.files import (
    create_desktop_file,
    create_desktop_folder,
    create_file,
    find_user_file,
    list_files,
    open_file_or_folder,
    read_course_material,
    read_file,
    read_notes,
    save_note,
)
from tools.guardian import check_guardian_security, get_guardian_alerts, get_guardian_status
from tools.information import get_system_info, get_time, get_weather
from tools.media import (
    change_volume,
    control_music,
    get_current_song,
    play_spotify_song,
    play_youtube_song,
)
from tools.obsidian import (
    list_vault_files,
    read_memory_note,
    read_vault_file,
    save_memory_note,
    save_vault_file,
    search_memory,
    second_brain_status,
)
from tools.permissions import deny_action, enable_nova_safe_mode, list_pending_actions
from tools.specialist import ask_specialist
from tools.skills import SKILL_CONTROL_TOOLS
from tools.web import WEB_RESEARCH_TOOLS


def build_default_capability_manager(*, specialist_tool=ask_specialist) -> CapabilityManager:
    """Wire NOVA's canonical capability identity to its concrete tool objects.

    Capability identity/metadata (name, description, permissions, tags, risk,
    default activation) lives in ``nova_os.capability_definitions`` and is not
    repeated here. This function's only job is mapping each capability id to
    the tool objects that implement it -- the one piece that genuinely
    requires importing every ``tools/*`` module.
    """
    registry = CapabilityRegistry()

    tools_by_id: dict[str, tuple[object, ...]] = {
        "system": (get_weather, get_system_info, get_time),
        "web": tuple(WEB_RESEARCH_TOOLS),
        "desktop": (
            open_website,
            open_app,
            is_app_running,
            control_window,
            open_notifications,
            open_quick_settings,
            manage_virtual_desktop,
            close_app,
            restart_app,
        ),
        "files": (
            save_note,
            read_notes,
            find_user_file,
            list_files,
            open_file_or_folder,
            create_desktop_file,
            create_desktop_folder,
            read_course_material,
            read_file,
            create_file,
        ),
        "media": (
            play_youtube_song,
            control_music,
            change_volume,
            get_current_song,
            play_spotify_song,
        ),
        "class_intelligence": tuple(CLASS_CAPTURE_TOOLS),
        "development": tuple(DEVELOPMENT_TOOLS),
        "specialist": (specialist_tool,),
        "memory": (
            second_brain_status,
            list_vault_files,
            read_vault_file,
            save_vault_file,
            search_memory,
            read_memory_note,
            save_memory_note,
            search_conversation_history,
            read_conversation_history,
        ),
        "email_calendar": (
            list_connected_accounts,
            sync_email_calendar,
            get_unread_emails,
            read_email,
            get_calendar_agenda,
            get_next_event,
            find_calendar_conflicts,
            get_daily_briefing,
        ),
        "guardian": (check_guardian_security, get_guardian_alerts, get_guardian_status),
        "skills": tuple(SKILL_CONTROL_TOOLS),
        "permissions": (list_pending_actions, enable_nova_safe_mode, deny_action),
    }

    defined_ids = frozenset(definition.capability_id for definition in CAPABILITY_DEFINITIONS)
    if frozenset(tools_by_id) != defined_ids:
        raise RuntimeError(
            "nova_os.catalog's tool wiring does not match "
            "nova_os.capability_definitions.CAPABILITY_DEFINITIONS. Every "
            "canonical capability id must have exactly one tool-wiring entry, "
            "and vice versa -- update both together."
        )

    for definition in CAPABILITY_DEFINITIONS:
        registry.register(
            CapabilitySpec(
                capability_id=definition.capability_id,
                name=definition.name,
                description=definition.description,
                tools=tools_by_id[definition.capability_id],
                permissions=definition.permissions,
                tags=definition.tags,
                risk=definition.risk,
                default_active=definition.default_active,
                locked_active=definition.locked_active,
            )
        )

    return CapabilityManager(
        registry,
        control_tools=(*CAPABILITY_CONTROL_TOOLS, *CORE_INTELLIGENCE_TOOLS),
    )
