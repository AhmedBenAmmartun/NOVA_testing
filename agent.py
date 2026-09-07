import asyncio
import json
import secrets
import time

from dotenv import load_dotenv
from livekit import rtc
from livekit import agents
from livekit.agents import AgentServer, AgentSession, Agent, TurnHandlingOptions, room_io
from livekit.plugins import ai_coustics

from prompts import SYSTEM_PROMPT
from tools.conversations import SessionConversationRecorder
from tools.common import logger as nova_logger
from tools.specialist import ask_specialist
from nova_core import build_realtime_model
from nova_intelligence.context_broker import ContextBroker
from nova_lab.service import DevelopmentService
from nova_policy import permission_engine
from nova_os import build_default_capability_manager, build_default_skill_registry
from nova_learning.runtime import LearningSessionRecorder
from nova_runtime import NovaRuntime
from nova_runtime.store import TaskStore

load_dotenv(".env.local")
load_dotenv(".env")


CONVERSATION_MODE_TURN_HANDLING: TurnHandlingOptions = {
    "turn_detection": "realtime_llm",
    "interruption": {
        "enabled": True,
        "discard_audio_if_uninterruptible": True,
        "min_duration": 0.20,
        "min_words": 0,
        "resume_false_interruption": True,
        "false_interruption_timeout": 0.80,
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
CONVERSATION_MODE_AEC_WARMUP_SECONDS = 0.40


def _install_conversation_mode_logging(
    session: AgentSession,
) -> None:
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

    @session.on("conversation_item_added")
    def _log_turn_latency(event) -> None:
        """Log per-turn response latency without storing transcript content."""
        item = getattr(event, "item", None)
        if item is None or getattr(item, "role", None) != "assistant":
            return

        metrics = getattr(item, "metrics", None)
        if not metrics:
            return

        if hasattr(metrics, "get"):
            latency = metrics.get("e2e_latency")
        else:
            latency = getattr(metrics, "e2e_latency", None)

        if latency is None:
            return

        try:
            latency_ms = round(float(latency) * 1000)
        except (TypeError, ValueError):
            return

        nova_logger.info("conversation e2e_latency_ms=%d", latency_ms)

    @session.on("function_tools_executed")
    def _log_tools_executed(event) -> None:
        tool_count = len(getattr(event, "function_calls", ()) or ())
        nova_logger.info("conversation function_tools_executed count=%s", tool_count)

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
            nova_logger.error("conversation unrecoverable_session_error=%s", type(error).__name__)

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
        if not event.is_final:
            return

        transcript = (event.transcript or "").strip()

        nova_logger.info(
            "conversation user_transcript final length=%s speaker_id=%s",
            len(transcript),
            event.speaker_id,
        )

        normalized = transcript.lower().strip()

        obvious_noise = {
            "",
            ".",
            "..",
            "...",
            "<noise>",
            "[noise]",
            "<silence>",
            "[silence]",
        }

        if normalized in obvious_noise:
            nova_logger.info(
                "conversation ignored_noise_transcript text=%r",
                transcript,
            )
            return

        # Very short fragments are commonly music/noise hallucinations.
        # Keep real short commands such as "stop", "pause", "yes", etc.
        allowed_short_commands = {
            "yes",
            "no",
            "stop",
            "pause",
            "play",
            "next",
            "back",
            "mute",
            "unmute",
            "nova",
            "hey nova",
        }

        if len(normalized) <= 3 and normalized not in allowed_short_commands:
            nova_logger.info(
                "conversation ignored_short_transcript text=%r",
                transcript,
            )
            return


# === NOVA LIVE PERSONALITY V3 BEGIN ===

_PERSONALITY_DEFAULTS = {
    "mode": "best_friend",
    "profanity": "natural",
    "humor": 72,
    "sarcasm": 38,
    "teasing": True,
    "emoji": True,
    "serious_tone_down": True,
}

_PERSONALITY_MODES = {
    "best_friend": (
        "Talk like a highly capable close friend: relaxed, warm, funny when it fits, "
        "comfortable with light teasing, and willing to disagree honestly."
    ),
    "chill": (
        "Be calm, laid-back, friendly, and low-pressure. Keep jokes and sarcasm lighter."
    ),
    "focus": (
        "Be direct, concise, task-oriented, and friendly. Minimize jokes and side comments."
    ),
    "professional": (
        "Be polished, neutral, precise, and professional. Avoid slang unless the user asks for it."
    ),
    "unfiltered": (
        "Be candid, energetic, playful, and blunt when useful. Keep judgment and accuracy intact."
    ),
}

_PROFANITY_LEVELS = {
    "off": "Do not use profanity.",
    "light": "Occasional mild profanity is allowed when it fits naturally.",
    "natural": (
        "Natural conversational profanity is allowed when it genuinely fits. "
        "Do not force it or put it in every response."
    ),
    "unfiltered": (
        "Stronger casual profanity is allowed more freely when appropriate, "
        "but never hateful slurs, threats, abusive harassment, or unsafe language."
    ),
}


def _normalize_personality(raw: object) -> dict:
    settings = dict(_PERSONALITY_DEFAULTS)
    if not isinstance(raw, dict):
        return settings

    mode = str(raw.get("mode", settings["mode"])).strip().lower()
    if mode in _PERSONALITY_MODES:
        settings["mode"] = mode

    profanity = str(raw.get("profanity", settings["profanity"])).strip().lower()
    if profanity in _PROFANITY_LEVELS:
        settings["profanity"] = profanity

    for key in ("humor", "sarcasm"):
        try:
            settings[key] = max(0, min(100, int(raw.get(key, settings[key]))))
        except (TypeError, ValueError):
            pass

    for key in ("teasing", "emoji", "serious_tone_down"):
        value = raw.get(key, settings[key])
        if isinstance(value, bool):
            settings[key] = value

    return settings


def _build_personality_instructions(raw: object = None) -> str:
    p = _normalize_personality(raw)
    humor_hint = (
        "Use humor often when appropriate."
        if p["humor"] >= 65
        else "Use humor sometimes when appropriate."
        if p["humor"] >= 30
        else "Use very little humor."
    )
    sarcasm_hint = (
        "Sarcasm can be fairly noticeable but still friendly."
        if p["sarcasm"] >= 65
        else "Use occasional light sarcasm."
        if p["sarcasm"] >= 30
        else "Avoid most sarcasm."
    )

    return (
        SYSTEM_PROMPT
        + "\n\n==================================================\n"
        + "LIVE PERSONALITY PROFILE\n"
        + "==================================================\n\n"
        + "This profile changes conversational style only. It NEVER overrides safety, privacy, permissions, tool rules, trusted approval requirements, or factual accuracy.\n\n"
        + f"Mode: {p['mode']}\n"
        + f"{_PERSONALITY_MODES[p['mode']]}\n\n"
        + f"Profanity: {p['profanity']}\n"
        + f"{_PROFANITY_LEVELS[p['profanity']]}\n\n"
        + f"Humor level: {p['humor']}/100. {humor_hint}\n"
        + f"Sarcasm level: {p['sarcasm']}/100. {sarcasm_hint}\n"
        + (
            "Light friendly teasing and banter are allowed.\n"
            if p["teasing"]
            else "Do not tease the user.\n"
        )
        + (
            "Occasional emoji are okay when natural.\n"
            if p["emoji"]
            else "Do not use emoji.\n"
        )
        + (
            "Automatically reduce jokes, sarcasm, teasing, emoji, and profanity "
            "during serious, sensitive, emergency, security, medical, legal, financial, "
            "or destructive/high-risk situations.\n"
            if p["serious_tone_down"]
            else ""
        )
        + "\n\nLIVE VISION BEHAVIOR\n"
        + "When live camera/video frames are available in the session, use them directly. "
          "Do not claim you are limited to voice and text if visual context is present. "
          "If no usable visual frame is available, say that clearly instead of guessing.\n"
        + "\nMaintain a friend-like conversational vibe without pretending to be human. "
          "Do not invent human memories, physical experiences, or a human life.\n"
    )


def _install_personality_stream(
    ctx: agents.JobContext,
    assistant: "Assistant",
) -> set:
    active_tasks: set = set()

    async def _apply(reader, participant_identity: str) -> None:
        try:
            raw_text = await reader.read_all()
            payload = json.loads(raw_text)
            settings = _normalize_personality(payload)
            await assistant.update_instructions(
                _build_personality_instructions(settings)
            )
            nova_logger.info(
                "personality updated mode=%s profanity=%s humor=%s sarcasm=%s",
                settings["mode"],
                settings["profanity"],
                settings["humor"],
                settings["sarcasm"],
            )
        except Exception as error:
            nova_logger.warning(
                "personality update rejected participant=%s error=%s",
                participant_identity,
                type(error).__name__,
            )

    def _handler(reader, participant_identity: str) -> None:
        task = asyncio.create_task(_apply(reader, participant_identity))
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

    ctx.room.register_text_stream_handler("nova.personality", _handler)
    return active_tasks

# === NOVA LIVE PERSONALITY V3 END ===

# === NOVA VISION TRANSPORT V3.2 BEGIN ===

async def _send_vision_status(
    ctx: agents.JobContext,
    state: str,
    *,
    detail: str = "",
    source: str = "camera",
) -> None:
    payload = {
        "state": state,
        "detail": detail[:180],
        "source": source,
    }
    try:
        await ctx.room.local_participant.send_text(
            json.dumps(payload),
            topic="nova.vision-status",
        )
    except Exception as error:
        nova_logger.debug(
            "vision status send skipped state=%s error=%s",
            state,
            type(error).__name__,
        )


def _install_vision_transport_monitor(ctx: agents.JobContext) -> set:
    active_tasks: set = set()

    def spawn(coro) -> None:
        task = asyncio.create_task(coro)
        active_tasks.add(task)
        task.add_done_callback(active_tasks.discard)

    @ctx.room.on("participant_connected")
    def _participant_connected(participant) -> None:
        nova_logger.info(
            "vision participant connected identity=%s",
            getattr(participant, "identity", "unknown"),
        )

    @ctx.room.on("track_published")
    def _track_published(publication, participant) -> None:
        kind = getattr(publication, "kind", None)
        source = getattr(publication, "source", None)
        nova_logger.info(
            "vision track published participant=%s kind=%s source=%s sid=%s",
            getattr(participant, "identity", "unknown"),
            kind,
            source,
            getattr(publication, "sid", "unknown"),
        )
        if kind == rtc.TrackKind.KIND_VIDEO:
            spawn(_send_vision_status(
                ctx,
                "CAMERA_PUBLISHED",
                detail="Video track published in the LiveKit room.",
                source=str(source),
            ))

    @ctx.room.on("track_subscribed")
    def _track_subscribed(track, publication, participant) -> None:
        nova_logger.info(
            "vision track subscribed participant=%s kind=%s source=%s sid=%s",
            getattr(participant, "identity", "unknown"),
            getattr(track, "kind", None),
            getattr(publication, "source", None),
            getattr(publication, "sid", "unknown"),
        )
        if getattr(track, "kind", None) == rtc.TrackKind.KIND_VIDEO:
            spawn(_send_vision_status(
                ctx,
                "AGENT_RECEIVING_VIDEO",
                detail="Agent subscribed to the remote video track.",
                source=str(getattr(publication, "source", "camera")),
            ))

    @ctx.room.on("track_unsubscribed")
    def _track_unsubscribed(track, publication, participant) -> None:
        if getattr(track, "kind", None) == rtc.TrackKind.KIND_VIDEO:
            nova_logger.info(
                "vision track unsubscribed participant=%s source=%s",
                getattr(participant, "identity", "unknown"),
                getattr(publication, "source", None),
            )
            spawn(_send_vision_status(
                ctx,
                "VIDEO_NOT_RECEIVING",
                detail="Agent is no longer subscribed to the video track.",
            ))

    @ctx.room.on("track_subscription_failed")
    def _track_subscription_failed(participant, track_sid, error) -> None:
        nova_logger.warning(
            "vision track subscription failed participant=%s sid=%s error=%s",
            getattr(participant, "identity", "unknown"),
            track_sid,
            error,
        )
        spawn(_send_vision_status(
            ctx,
            "VIDEO_SUBSCRIPTION_FAILED",
            detail=str(error),
        ))

    return active_tasks

# === NOVA VISION TRANSPORT V3.2 END ===



class Assistant(Agent):
    """NOVA realtime agent backed by the NOVA OS capability kernel."""

    def __init__(self, *, runtime: NovaRuntime | None = None) -> None:
        manager = build_default_capability_manager(specialist_tool=ask_specialist)
        skills = build_default_skill_registry()
        super().__init__(
            instructions=_build_personality_instructions(),
            tools=manager.build_tool_context(),
        )
        self.capability_manager = manager
        self.skill_registry = skills
        self.core_intelligence = ContextBroker()
        # Per-session, injected by trusted code -- never a process-global
        # singleton that could mix background jobs across sessions. `runtime`
        # is the same NovaRuntime this LiveKit job already constructed; V1C's
        # NOVA Lab background test jobs run through it, not a second job
        # system. None (e.g. the text-chat driver) still works: the
        # inspection/registration tools need no runtime, and the job/candidate
        # tools raise a clear error instead of touching a missing one.
        self.nova_lab_service = DevelopmentService(runtime=runtime)


server = AgentServer()


@server.rtc_session(agent_name="my-agent")
async def my_agent(ctx: agents.JobContext):
    realtime_model, realtime_selection = build_realtime_model()
    nova_logger.info(
        "realtime provider selected provider=%s model=%s route=%s",
        realtime_selection.provider.value,
        realtime_selection.model,
        realtime_selection.route,
    )

    session = AgentSession(
        turn_handling=CONVERSATION_MODE_TURN_HANDLING,
        aec_warmup_duration=CONVERSATION_MODE_AEC_WARMUP_SECONDS,
        llm=realtime_model,
    )

    # Historical variable name retained only for the existing Phase 0/1
    # security contract. This is now just a per-session permission ID;
    # the legacy Dashboard bridge itself is removed.
    bridge_session_id = f"job_{secrets.token_hex(8)}"
    _install_conversation_mode_logging(session)
    SessionConversationRecorder().attach(session)
    LearningSessionRecorder(
        route=realtime_selection.route,
        model=realtime_selection.model,
        strategy_versions={
            "learning_runtime": "v1.1",
            "capability_kernel": "nova_os",
        },
    ).attach(session)
    # The one NOVA task runtime. `nova_school` has consumed it for a while; the
    # agent Ahmed actually talks to had no task layer at all until now.
    runtime = NovaRuntime()

    # Recover durable task state before anything new is dispatched. This is
    # also what reinterprets a task left RUNNING by a process that died -- the
    # same reader-verifies-liveness rule the postprocess status file follows.
    #
    # Task state is valuable; being able to talk to NOVA is more valuable. A
    # corrupt or unreadable store degrades to "no recovered tasks", never to an
    # agent that refuses to start.
    try:
        recovered = TaskStore().recover()
        if recovered:
            nova_logger.info(
                "runtime recovered %s task(s) from durable state", len(recovered)
            )
    except Exception:
        nova_logger.exception("durable task recovery failed; starting with none")

    async def _shutdown_runtime() -> None:
        await runtime.shutdown()

    ctx.add_shutdown_callback(_shutdown_runtime)

    async def _clear_job_permissions() -> None:
        permission_engine.clear_session(bridge_session_id)

    async def _clear_voice_permissions() -> None:
        permission_engine.clear_session("voice")

    ctx.add_shutdown_callback(_clear_job_permissions)

    # Legacy desktop tools still use the compatibility "voice" bucket.
    # Clear it once when this LiveKit job ends so temporary grants cannot
    # survive into a later session.
    ctx.add_shutdown_callback(_clear_voice_permissions)

    assistant = Assistant(runtime=runtime)
    _personality_tasks = _install_personality_stream(ctx, assistant)

    _vision_transport_tasks = _install_vision_transport_monitor(ctx)
    await _send_vision_status(
        ctx,
        "WAITING_FOR_CAMERA",
        detail="Agent vision transport monitor is ready.",
    )

    try:
        await session.start(
            room=ctx.room,
            agent=assistant,
            room_options=room_io.RoomOptions(
                text_input=True,
                text_output=room_io.TextOutputOptions(
                    sync_transcription=False,
                ),
                video_input=True,
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=ai_coustics.audio_enhancement(
                        model=ai_coustics.EnhancerModel.QUAIL_VF_S
                    ),
                ),
            ),
        )
    except Exception as error:
        nova_logger.exception("agent startup failed: %s", type(error).__name__)
        raise

    await ctx.connect()
    nova_logger.info("vision transport: job context connected")
    await _send_vision_status(
        ctx,
        "AGENT_CONNECTED",
        detail="NOVA agent joined the LiveKit room with video input enabled.",
    )

    from datetime import datetime

    hour = datetime.now().hour

    if hour < 12:
        greeting = "Good morning"
    elif hour < 18:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    await session.generate_reply(
        instructions=(
            f"Say exactly: {greeting}, Ahmed. NOVA is ready."
        ),
        allow_interruptions=True,
    )


if __name__ == "__main__":
    agents.cli.run_app(server)

# === NOVA VISION TYPED CAMERA V3.4 ===

