from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import ai_coustics, google
from prompts import SYSTEM_PROMPT
from tools import (
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
)
load_dotenv(".env.local")
load_dotenv(".env")  # actual credentials file; .env.local (above) wins if both exist


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            tools=[
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
                create_file
            ],
        )


server = AgentServer()


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            voice="Achird",
            temperature=0.8,
        )
    )

    await session.start(
    room=ctx.room,
    agent=Assistant(),
    room_options=room_io.RoomOptions(
        video_input=True,
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=ai_coustics.audio_enhancement(
                model=ai_coustics.EnhancerModel.QUAIL_VF_S
            ),
        ),
    ),
)

    await session.generate_reply(
        instructions="Greet Ahmed as NOVA. Keep it short and natural."
    )


if __name__ == "__main__":
    agents.cli.run_app(server)