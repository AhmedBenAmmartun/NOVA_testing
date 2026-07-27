import asyncio
import secrets

from dotenv import load_dotenv
from google.genai import types

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, TurnHandlingOptions, room_io
from livekit.plugins import ai_coustics, google

from prompts import SYSTEM_PROMPT
from nova_agent_bridge import AgentStatusReporter, dashboard_bridge_loop, stop_dashboard_bridge
from tools.conversations import SessionConversationRecorder
from tools.common import logger as nova_logger
from tools import (
    ask_specialist,
    list_connected_accounts,
    sync_email_calendar,
    get_unread_emails,
    read_email,
    get_calendar_agenda,
    get_next_event,
    find_calendar_conflicts,
    get_daily_briefing,
    check_guardian_security,
    get_guardian_alerts,
    get_guardian_status,
    look_at_screen_locally,
    start_guardian_vision,
    stop_guardian_vision,
    list_pending_actions,
    approve_action,
    deny_action,
    set_nova_safe_mode,
    search_memory,
    read_memory_note,
    save_memory_note,
    search_conversation_history,
    read_conversation_history,
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


def _install_conversation_mode_logging(
    session: AgentSession,
    status: AgentStatusReporter,
) -> None:
    """Record voice state transitions without storing private transcript text."""

    @session.on("agent_state_changed")
    def _log_agent_state(event) -> None:
        nova_logger.info(
            "conversation agent_state %s -> %s",
            event.old_state,
            event.new_state,
        )
        new_state = str(event.new_state).split(".")[-1].lower()
        phase = {
            "initializing": "starting",
            "idle": "idle",
            "listening": "listening",
            "thinking": "thinking",
            "speaking": "speaking",
        }.get(new_state)
        if phase:
            status.set_phase(phase)

    @session.on("user_state_changed")
    def _log_user_state(event) -> None:
        nova_logger.info(
            "conversation user_state %s -> %s",
            event.old_state,
            event.new_state,
        )
        new_state = str(event.new_state).split(".")[-1].lower()
        if new_state == "speaking":
            status.set_phase("listening")

    @session.on("function_tools_executed")
    def _log_tools_executed(event) -> None:
        tool_count = len(getattr(event, "function_calls", ()) or ())
        nova_logger.info("conversation function_tools_executed count=%s", tool_count)
        status.set_phase("thinking", detail=f"Completed {tool_count} tool call(s)")

    @session.on("error")
    def _log_session_error(event) -> None:
        error = getattr(event, "error", None)
        recoverable = bool(getattr(error, "recoverable", False))
        nova_logger.warning(
            "conversation session_error source=%s recoverable=%s error=%s",
            type(getattr(event, "source", None)).__name__,
            recoverable,
            type(error).__name__,
        )
        if not recoverable:
            status.set_phase("error", detail=f"Session error: {type(error).__name__}")

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
                check_guardian_security,
                list_connected_accounts,
                sync_email_calendar,
                get_unread_emails,
                read_email,
                get_calendar_agenda,
                get_next_event,
                find_calendar_conflicts,
                get_daily_briefing,
                get_guardian_alerts,
                get_guardian_status,
                look_at_screen_locally,
                start_guardian_vision,
                stop_guardian_vision,
                search_memory,
                read_memory_note,
                save_memory_note,
                search_conversation_history,
                read_conversation_history,
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
                list_pending_actions,
                approve_action,
                deny_action,
                set_nova_safe_mode,
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
                    # Keep start-of-speech HIGH so Ahmed can still barge in
                    # quickly when NOVA is talking. End-of-speech was HIGH
                    # with only 350ms of silence required, which read normal
                    # mid-sentence pauses as "done talking" and cut Ahmed
                    # off - lowered plus a longer silence window so NOVA
                    # waits for an actual pause before responding.
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=200,
                    silence_duration_ms=650,
                ), # <--- Closes AutomaticActivityDetection
            ), # <--- Closes RealtimeInputConfig
        ), # <--- Closes RealtimeModel
    ) # <--- Closes AgentSession

    bridge_session_id = f"job_{secrets.token_hex(8)}"
    bridge_status = AgentStatusReporter(session_id=bridge_session_id)
    _install_conversation_mode_logging(session, bridge_status)
    SessionConversationRecorder().attach(session)

    bridge_task = asyncio.create_task(
        dashboard_bridge_loop(
            session,
            bridge_session_id,
            status=bridge_status,
        ),
        name="nova_dashboard_bridge",
    )
    ctx.add_shutdown_callback(lambda: stop_dashboard_bridge(bridge_task))

    try:
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
    except Exception as error:
        bridge_status.set_phase(
            "error",
            detail=f"Agent startup failed: {type(error).__name__}",
        )
        await bridge_status.publish_now()
        raise

    bridge_status.set_phase("idle")
    await bridge_status.publish_now()

    await session.generate_reply(
        instructions="Greet Ahmed briefly and naturally. Tell him NOVA is ready.",
        allow_interruptions=True,
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
