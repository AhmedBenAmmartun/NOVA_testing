from dotenv import load_dotenv
from google.genai import types

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, TurnHandlingOptions, room_io
from livekit.plugins import ai_coustics, google

from prompts import SYSTEM_PROMPT
from tools.conversations import SessionConversationRecorder
from tools.common import logger as nova_logger
from tools import (
    search_memory,
    read_memory_note,
    save_memory_note,
    search_conversation_history,
    read_conversation_history,
    ask_gpt56,
    ask_groq,
    ask_ollama,
    restart_app,
    close_app,
    control_window,
    manage_virtual_desktop,
    get_weather,
    search_web,
    open_notifications,
    open_quick_settings,
    open_website,
    open_app,
    is_app_running,
    play_youtube_song,
    control_music,
    change_volume,
    get_current_song,
    play_spotify_song,
    get_system_info,
    get_time,
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
    capture_screen,
    analyze_screen_with_gpt56,
)

load_dotenv(".env.local")
load_dotenv(".env")


CONVERSATION_MODE_TURN_HANDLING: TurnHandlingOptions = {
    "turn_detection": "realtime_llm",
    "interruption": {
        "enabled": True,
        "discard_audio_if_uninterruptible": True,
        "min_duration": 0.35,
        "min_words": 0,
        "resume_false_interruption": True,
        "false_interruption_timeout": 1.25,
        "backchannel_boundary": (0.6, 0.6),
    },
    "preemptive_generation": {
        "enabled": True,
        "preemptive_tts": False,
        "max_speech_duration": 8.0,
        "max_retries": 2,
    },
}

# Keep a short echo guard, but do not make Ahmed wait 3 seconds before he can
# reliably barge in while NOVA is speaking.
CONVERSATION_MODE_AEC_WARMUP_SECONDS = 0.8


def _install_conversation_mode_logging(session: AgentSession) -> None:
    """Record voice state transitions without storing private transcript text."""

    @session.on("agent_state_changed")
    def _log_agent_state(event) -> None:
        nova_logger.info(
            "conversation agent_state %s -> %s",
            event.old_state,
            event.new_state,
        )

    @session.on("user_state_changed")
    def _log_user_state(event) -> None:
        nova_logger.info(
            "conversation user_state %s -> %s",
            event.old_state,
            event.new_state,
        )

    @session.on("speech_created")
    def _log_speech_created(event) -> None:
        nova_logger.info(
            "conversation speech_created id=%s source=%s user_initiated=%s "
            "allow_interruptions=%s",
            event.speech_handle.id,
            event.source,
            event.user_initiated,
            event.speech_handle.allow_interruptions,
        )

    @session.on("agent_false_interruption")
    def _log_false_interruption(event) -> None:
        nova_logger.info(
            "conversation false_interruption resumed=%s",
            event.resumed,
        )

    @session.on("overlapping_speech")
    def _log_overlapping_speech(event) -> None:
        nova_logger.info(
            "conversation overlapping_speech interruption=%s probability=%.3f "
            "delay=%.3f",
            event.is_interruption,
            event.probability,
            event.detection_delay,
        )

    @session.on("user_input_transcribed")
    def _log_user_input(event) -> None:
        if event.is_final:
            nova_logger.info(
                "conversation user_transcript final length=%s speaker_id=%s",
                len(event.transcript or ""),
                event.speaker_id,
            )


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[
                search_memory,
                read_memory_note,
                save_memory_note,
                search_conversation_history,
                read_conversation_history,
                ask_gpt56,
                ask_groq,
                ask_ollama,
                close_app,
                restart_app,
                control_window,
                manage_virtual_desktop,
                get_weather,
                search_web,
                open_notifications,
                open_quick_settings,
                open_website,
                open_app,
                is_app_running,
                play_youtube_song,
                control_music,
                change_volume,
                get_current_song,
                play_spotify_song,
                get_system_info,
                get_time,
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
                capture_screen,
                analyze_screen_with_gpt56,
            ],
        )


server = AgentServer()


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        turn_handling=CONVERSATION_MODE_TURN_HANDLING,
        aec_warmup_duration=CONVERSATION_MODE_AEC_WARMUP_SECONDS,
        llm=google.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Puck",
            temperature=0.5,

            thinking_config=types.ThinkingConfig(
                thinking_budget=0,
                include_thoughts=False,
            ),

            realtime_input_config=types.RealtimeInputConfig(
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=200,
                    silence_duration_ms=350,
                ), # <--- Closes AutomaticActivityDetection
            ), # <--- Closes RealtimeInputConfig
        ), # <--- Closes RealtimeModel
    ) # <--- Closes AgentSession

    _install_conversation_mode_logging(session)
    SessionConversationRecorder().attach(session)

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            video_input=False,
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=ai_coustics.audio_enhancement(
                    model=ai_coustics.EnhancerModel.QUAIL_VF_S
                ),
            ),
        ),
    )

    await session.generate_reply(
        instructions="Say only: Hello Ahmed. NOVA is ready.",
        allow_interruptions=True,
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
