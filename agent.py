from dotenv import load_dotenv
from google.genai import types

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import ai_coustics, google

from prompts import SYSTEM_PROMPT
from tools import (
    restart_app,
    close_app,
    get_weather,
    search_web,
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
    list_files,
    read_file,
    create_file,
    capture_screen,
)

load_dotenv(".env.local")
load_dotenv(".env")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[
                close_app,
                restart_app,
                get_weather,
                search_web,
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
                list_files,
                read_file,
                create_file,
                capture_screen,
            ],
        )


server = AgentServer()


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        llm=google.realtime.RealtimeModel(
             model="gemini-2.5-flash-native-audio-preview-12-2025", 
            # 2. Changed voice here (Try Puck, Charon, Kore, Aoede, or Fenrir)
            voice="Puck", 
            temperature=0.5,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=
                        types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=
                        types.EndSensitivity.END_SENSITIVITY_HIGH,
                    # 3. Tightened timing thresholds for faster responses
                    prefix_padding_ms=100,
                    silence_duration_ms=250, 
                ),
            ),
        )
    )

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
        instructions="Say only: Hello Ahmed. NOVA is ready."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)