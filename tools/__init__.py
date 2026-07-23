from .vision import analyze_screen_with_gpt56, capture_screen
from .models import ask_gpt56, ask_groq, ask_ollama
from .obsidian import read_memory_note, save_memory_note, search_memory
from .conversations import read_conversation_history, search_conversation_history
from .specialist import ask_specialist

from .email_calendar import (
    list_connected_accounts,
    sync_email_calendar,
    get_unread_emails,
    read_email,
    get_calendar_agenda,
    get_next_event,
    find_calendar_conflicts,
    get_daily_briefing,
)

from .permissions import (
    approve_action,
    deny_action,
    list_pending_actions,
    set_nova_safe_mode,
)

from .desktop import (
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

from .files import (
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

from .information import (
    get_system_info,
    get_time,
    get_weather,
    search_web,
)

from .media import (
    change_volume,
    control_music,
    get_current_song,
    play_spotify_song,
    play_youtube_song,
)

from .guardian import (
    check_guardian_security,
    get_guardian_alerts,
    get_guardian_status,
    look_at_screen_locally,
    start_guardian_vision,
    stop_guardian_vision,
)



__all__ = [
    "ask_specialist",
    "get_weather",
    "search_web",
    "open_website",
    "open_app",
    "is_app_running",
    "control_window",
    "open_notifications",
    "open_quick_settings",
    "manage_virtual_desktop",
    "play_youtube_song",
    "control_music",
    "change_volume",
    "get_current_song",
    "play_spotify_song",
    "get_system_info",
    "get_time",
    "save_note",
    "read_notes",
    "list_files",
    "find_user_file",
    "open_file_or_folder",
    "create_desktop_file",
    "create_desktop_folder",
    "read_course_material",
    "read_file",
    "create_file",
    "capture_screen",
    "analyze_screen_with_gpt56",
    "close_app",
    "restart_app",
    "ask_groq",
    "ask_ollama",
    "ask_gpt56",
    "search_memory",
    "read_memory_note",
    "save_memory_note",
    "search_conversation_history",
    "read_conversation_history",
    "list_pending_actions",
    "approve_action",
    "deny_action",
    "set_nova_safe_mode",
    "check_guardian_security",
    "get_guardian_alerts",
    "get_guardian_status",
    "look_at_screen_locally",
    "start_guardian_vision",
    "stop_guardian_vision",
    "list_connected_accounts",
    "sync_email_calendar",
    "get_unread_emails",
    "read_email",
    "get_calendar_agenda",
    "get_next_event",
    "find_calendar_conflicts",
    "get_daily_briefing",
]

