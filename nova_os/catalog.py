"""Default NOVA OS capability catalog built from the project's current tools."""

from __future__ import annotations

from nova_os.capabilities import CapabilityManager, CapabilityRegistry, CapabilitySpec
from tools.capabilities import CAPABILITY_CONTROL_TOOLS
from tools.conversations import read_conversation_history, search_conversation_history
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
    registry = CapabilityRegistry()

    specs = (
        CapabilitySpec(
            capability_id="system",
            name="System Information",
            description="Time, weather, CPU, RAM, disk, and battery information.",
            tools=(get_weather, get_system_info, get_time),
            permissions=("system_read", "internet_read"),
            tags=("system", "weather", "time", "computer"),
            risk="read_only",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="web",
            name="Web Research",
            description="Search, read, inspect, extract from, and safely download public web resources.",
            tools=tuple(WEB_RESEARCH_TOOLS),
            permissions=("internet_read", "downloads_write"),
            tags=("internet", "search", "research", "browser", "download"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="desktop",
            name="Windows Desktop",
            description="Open approved apps/sites and manage visible Windows desktop state.",
            tools=(
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
            permissions=("desktop_read", "desktop_change"),
            tags=("windows", "apps", "desktop", "window"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="files",
            name="Files and Notes",
            description="Find, read, open, and create files in NOVA-approved locations.",
            tools=(
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
            permissions=("files_read", "files_write_approved"),
            tags=("files", "folders", "notes", "documents"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="media",
            name="Media Control",
            description="Spotify, YouTube, media keys, volume, and current-song controls.",
            tools=(
                play_youtube_song,
                control_music,
                change_volume,
                get_current_song,
                play_spotify_song,
            ),
            permissions=("media_control",),
            tags=("music", "spotify", "youtube", "volume", "media"),
            risk="reversible",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="specialist",
            name="Specialist Models",
            description="Route substantial coding, architecture, analysis, or private local work to a specialist model.",
            tools=(specialist_tool,),
            permissions=("model_routing",),
            tags=("coding", "reasoning", "specialist", "ollama", "openai", "groq"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="memory",
            name="Memory and Conversation History",
            description="NOVA Vault second brain: search, read, organize, and safely save persistent knowledge and text files.",
            tools=(
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
            permissions=("memory_read", "memory_write"),
            tags=("memory", "obsidian", "second brain", "vault", "history", "notes", "projects", "decisions"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="email_calendar",
            name="Email and Calendar",
            description="Read-only connected email/calendar synchronization, search, agenda, and briefing tools.",
            tools=(
                list_connected_accounts,
                sync_email_calendar,
                get_unread_emails,
                read_email,
                get_calendar_agenda,
                get_next_event,
                find_calendar_conflicts,
                get_daily_briefing,
            ),
            permissions=("account_metadata_read", "private_content_read"),
            tags=("gmail", "outlook", "email", "calendar", "agenda"),
            risk="sensitive_read",
            default_active=False,
        ),
        CapabilitySpec(
            capability_id="guardian",
            name="Guardian Security",
            description="Read NOVA Guardian status and security alerts without screenshot capture.",
            tools=(check_guardian_security, get_guardian_alerts, get_guardian_status),
            permissions=("security_read",),
            tags=("security", "guardian", "alerts"),
            risk="read_only",
            default_active=False,
        ),
        CapabilitySpec(
            capability_id="skills",
            name="Skills Engine",
            description="Load reusable workflows and explicitly save/update user-authored declarative skills.",
            tools=tuple(SKILL_CONTROL_TOOLS),
            permissions=("skills_read", "skills_write_user"),
            tags=("skills", "learn", "workflow", "reuse", "research"),
            risk="mixed",
            default_active=True,
        ),
        CapabilitySpec(
            capability_id="permissions",
            name="Permission Controls",
            description="List/deny pending actions and enable Safe Mode. Approval is never model-callable.",
            tools=(list_pending_actions, enable_nova_safe_mode, deny_action),
            permissions=("permission_read", "permission_restrict"),
            tags=("permissions", "safe mode", "security", "approval"),
            risk="restrictive_only",
            default_active=True,
            locked_active=True,
        ),
    )

    for spec in specs:
        registry.register(spec)

    return CapabilityManager(
        registry,
        control_tools=CAPABILITY_CONTROL_TOOLS,
    )
