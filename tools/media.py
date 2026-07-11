import ctypes
import os
import webbrowser

import psutil
from livekit.agents import RunContext, function_tool

from .common import PROJECT_ROOT, logger, press_key


def spotify_window_title() -> str | None:
    """Return the title of the main Spotify window."""
    from ctypes import wintypes

    spotify_pids = {
        process.pid
        for process in psutil.process_iter(["name"])
        if (process.info["name"] or "").lower() == "spotify.exe"
    }

    if not spotify_pids:
        return None

    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    def enum_window(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            process_id = wintypes.DWORD()

            user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(process_id),
            )

            if process_id.value in spotify_pids:
                length = user32.GetWindowTextLengthW(hwnd)

                if length:
                    buffer = ctypes.create_unicode_buffer(
                        length + 1
                    )

                    user32.GetWindowTextW(
                        hwnd,
                        buffer,
                        length + 1,
                    )

                    titles.append(buffer.value)

        return True

    user32.EnumWindows(enum_window, 0)

    for title in titles:
        if " - " in title:
            return title

    if titles:
        return titles[0]

    return "Spotify"


spotify_client_cache = None


def get_spotify_client():
    """Create or return the cached Spotify API client."""
    global spotify_client_cache

    if spotify_client_cache is not None:
        return spotify_client_cache

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        return None

    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    spotify_client_cache = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=os.getenv(
                "SPOTIFY_REDIRECT_URI",
                "http://127.0.0.1:8888/callback",
            ),
            scope=(
                "user-modify-playback-state "
                "user-read-playback-state"
            ),
            cache_path=str(
                PROJECT_ROOT / ".spotify_cache"
            ),
        )
    )

    return spotify_client_cache


SPOTIFY_NOT_CONFIGURED = (
    "The Spotify API is not configured. Add "
    "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
    "to the environment file."
)


@function_tool()
async def play_youtube_song(
    context: RunContext,
    song_name: str,
) -> str:
    """Open a YouTube search for a song."""
    try:
        query = song_name.replace(" ", "+")
        url = (
            "https://www.youtube.com/results"
            f"?search_query={query}"
        )

        webbrowser.open(url)

        logger.info(
            "play_youtube_song: %s",
            song_name,
        )

        return f"Opened YouTube results for {song_name}."

    except Exception:
        logger.exception("play_youtube_song failed")
        return "I could not open the YouTube search."


@function_tool()
async def control_music(
    context: RunContext,
    action: str,
) -> str:
    """Control music using Windows media keys."""
    media_keys = {
        "play_pause": 0xB3,
        "next": 0xB0,
        "previous": 0xB1,
    }

    cleaned_action = action.lower().strip()
    virtual_key = media_keys.get(cleaned_action)

    if virtual_key is None:
        return (
            "Unknown music action. Use play_pause, "
            "next, or previous."
        )

    try:
        press_key(virtual_key)

        logger.info(
            "control_music: %s",
            cleaned_action,
        )

        return (
            f"Sent {cleaned_action.replace('_', '/')} "
            "to the music player."
        )

    except Exception:
        logger.exception("control_music failed")
        return "I could not control the music player."


@function_tool()
async def change_volume(
    context: RunContext,
    action: str,
    steps: int = 5,
) -> str:
    """Change the Windows system volume."""
    volume_keys = {
        "up": 0xAF,
        "down": 0xAE,
        "mute": 0xAD,
    }

    cleaned_action = action.lower().strip()
    virtual_key = volume_keys.get(cleaned_action)

    if virtual_key is None:
        return "Unknown volume action. Use up, down, or mute."

    try:
        if cleaned_action == "mute":
            presses = 1
        else:
            presses = max(
                1,
                min(int(steps), 20),
            )

        for _ in range(presses):
            press_key(virtual_key)

        logger.info(
            "change_volume: %s x%d",
            cleaned_action,
            presses,
        )

        if cleaned_action == "mute":
            return "Toggled mute."

        return (
            f"Changed volume {cleaned_action} "
            f"by {presses} steps."
        )

    except Exception:
        logger.exception("change_volume failed")
        return "I could not change the system volume."


@function_tool()
async def get_current_song(context: RunContext) -> str:
    """Get the currently playing Spotify song."""
    try:
        title = spotify_window_title()

        if title is None:
            return "Spotify is not running."

        if " - " in title:
            return f"Now playing: {title}"

        return (
            "Spotify is open, but nothing appears "
            "to be playing."
        )

    except Exception:
        logger.exception("get_current_song failed")
        return "I could not determine the current song."


@function_tool()
async def play_spotify_song(
    context: RunContext,
    song_name: str,
) -> str:
    """Search for and play a Spotify track."""
    client = get_spotify_client()

    if client is None:
        return SPOTIFY_NOT_CONFIGURED

    try:
        results = client.search(
            q=song_name,
            type="track",
            limit=1,
        ) or {}

        tracks = results.get("tracks", {})
        items = tracks.get("items", [])

        if not items:
            return f"I could not find {song_name} on Spotify."

        track = items[0]

        device_response = client.devices() or {}
        devices = device_response.get("devices", [])

        if not devices:
            return (
                "No active Spotify device was found. "
                "Open Spotify and try again."
            )

        device_id = devices[0]["id"]

        client.start_playback(
            device_id=device_id,
            uris=[track["uri"]],
        )

        artists = track.get("artists", [])

        if artists:
            artist = artists[0]["name"]
        else:
            artist = "an unknown artist"

        track_name = track["name"]

        logger.info(
            "play_spotify_song: %s - %s",
            artist,
            track_name,
        )

        return (
            f"Playing {track_name} by {artist} "
            "on Spotify."
        )

    except Exception:
        logger.exception("play_spotify_song failed")
        return (
            "I could not play that song. Spotify playback "
            "control may require Spotify Premium."
        )