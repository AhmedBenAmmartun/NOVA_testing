from .desktop import (
    close_app,
    is_app_running,
    open_app,
    open_website,
    restart_app,
)

from .files import (
    create_file,
    list_files,
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

from .vision import capture_screen


__all__ = [
    "get_weather",
    "search_web",
    "open_website",
    "open_app",
    "is_app_running",
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
    "read_file",
    "create_file",
    "capture_screen",
    "close_app",
    "restart_app",
]