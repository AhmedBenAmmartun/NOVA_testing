from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    inference,
    room_io,
)
from livekit.plugins import ai_coustics

from nova_capture import (
    ClassCaptureSession,
    LocalMicrophoneCapture,
    QuestionAssembler,
    QuestionDeduplicator,
    TranscriptSegment,
    TurnQuestionBuffer,
)
from nova_capture.control import (
    ActiveClassCaptureError,
    claim_active_session,
    heartbeat_active_session,
    release_active_session,
    wait_for_stop_request,
)
from nova_capture.intelligence import LiveQAManager, route_class_prompt
from nova_capture.live_notes import LiveNotesBatcher, LiveNotesWorker
from nova_capture.pipeline import resolve_class_pipeline
from nova_capture.postprocess import launch_postprocess
from nova_capture.question_detection import looks_like_question, should_answer_question
from nova_capture.recorder_process import (
    create_durable_recorder,
    write_supervisor_heartbeat,
)
from nova_capture.speakers import SpeakerRoleTracker
from nova_capture.supervisor import (
    CaptureEvent,
    ClassSessionSupervisor,
    SessionOutcome,
    WorkerStatus,
)
from nova_capture.terminology import TerminologyInterpreter
from nova_school import CourseRegistry, course_stt_keyterms, resolve_current_course
from nova_school.context import CourseContextLibrary, organize_recent_downloads_for_course
from nova_school.corrections import load_course_corrections
from nova_school.resolver import resolve_course_override


load_dotenv(".env.local")
load_dotenv(".env")

CAPTURE_VERSION = "1.3.8"
logger = logging.getLogger("nova.class_capture")
server = AgentServer()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


def _configure_capture_log(session_path: Path) -> None:
    """Give Class Capture a durable log of its own.

    The 2026-08-27 lecture stopped after 38m36s and the reason is unknowable
    because everything this module logged went to a console window that was
    then closed. Every run now leaves a file behind.
    """
    try:
        handler = logging.FileHandler(
            session_path / "class_capture.log",
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)


#: Close reasons that mean a human ended the session. Everything else is a
#: fault the class should try to recover from.
_USER_STOP_CLOSE_REASONS = ("user_initiated", "task_completed")


def _close_reason_is_user_stop(reason: str) -> bool:
    lowered = str(reason).casefold()
    return any(token in lowered for token in _USER_STOP_CLOSE_REASONS)


def _resolve_course():
    registry = CourseRegistry()

    override = resolve_course_override(
        os.getenv("NOVA_CLASS_COURSE"),
        registry=registry,
    )
    if override is not None:
        return override, "explicit override"

    scheduled = resolve_current_course(registry=registry)
    if scheduled is not None:
        return scheduled, "verified schedule"

    raise RuntimeError(
        "NOVA cannot safely determine the current class. "
        "Configure a verified meeting time with "
        "`python -m nova_school.cli add-meeting ...` or launch with "
        "`Start-NOVA-Class.ps1 -Course <COURSE_CODE>`."
    )


@server.rtc_session(agent_name="nova-class-capture")
async def class_capture(ctx: JobContext):
    course, resolution = _resolve_course()
    title = os.getenv("NOVA_CLASS_TITLE", "Class Session").strip() or "Class Session"
    live_answers_enabled = _env_bool("NOVA_CLASS_LIVE_ANSWERS", True)
    postprocess_enabled = _env_bool("NOVA_CLASS_POSTPROCESS", True)
    live_notes_enabled = _env_bool("NOVA_CLASS_LIVE_NOTES", True)
    auto_organize_downloads = _env_bool("NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS", False)
    keep_audio_on_crash = _env_bool("NOVA_CLASS_KEEP_AUDIO_ON_CRASH", True)

    recorder_mode = (
        os.getenv("NOVA_CLASS_RECORDER_MODE", "process").strip().casefold() or "process"
    )
    chunk_seconds = _env_float("NOVA_CLASS_AUDIO_CHUNK_SECONDS", 20.0)
    orphan_seconds = _env_float("NOVA_CLASS_RECORDER_ORPHAN_SECONDS", 3600.0)
    max_recording_seconds = _env_float("NOVA_CLASS_MAX_RECORDING_MINUTES", 0.0) * 60.0
    max_stt_restarts = _env_int("NOVA_CLASS_STT_MAX_RESTARTS", 20)
    max_recorder_restarts = _env_int("NOVA_CLASS_RECORDER_MAX_RESTARTS", 10)

    pipeline_selection = resolve_class_pipeline()

    capture = ClassCaptureSession(
        course.code,
        title,
        keep_audio=True,
        notes_enabled=postprocess_enabled,
        capture_version=CAPTURE_VERSION,
    )

    expected_path = capture.expected_path()
    try:
        claim_active_session(
            session_id=capture.session_id,
            course=course.code,
            session_path=expected_path,
        )
    except ActiveClassCaptureError:
        logger.exception("class capture refused duplicate active session")
        raise

    session_path: Path | None = None
    supervisor: ClassSessionSupervisor | None = None
    recorder = None
    live_session: AgentSession | None = None
    heartbeat_task: asyncio.Task | None = None
    notes_task: asyncio.Task | None = None
    restart_task: asyncio.Task | None = None
    live_notes: LiveNotesWorker | None = None
    finalized = False
    stt_restarts = 0
    recorder_restarts = 0
    audio_failure_reported = False
    segment_count = 0
    speaker_ids: set[str] = set()
    answer_queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    answer_worker_task: asyncio.Task | None = None
    turn_flush_task: asyncio.Task | None = None
    turn_flush_kind: str | None = None
    question_assembler = QuestionAssembler()
    turn_question_buffer = TurnQuestionBuffer()
    question_deduplicator = QuestionDeduplicator(window_seconds=15.0)
    speaker_tracker = SpeakerRoleTracker(
        teacher_speaker_id=os.getenv("NOVA_CLASS_TEACHER_SPEAKER_ID")
    )
    qa_manager: LiveQAManager | None = None
    stt_factory = None

    def microphone_factory(sink):
        """Build NOVA's microphone adapter for whichever recorder is selected.

        The durable recorder normally opens the device in its own process; the
        inline fallback uses this same adapter in-process.
        """
        return LocalMicrophoneCapture(sink)

    def persist_live_speakers() -> None:
        """Checkpoint rolling speaker evidence so a crash cannot erase it."""
        if session_path is None:
            return
        try:
            payload = speaker_tracker.live_snapshot()
            target = session_path / "speaker_roles_live.json"
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(target)
        except Exception:
            logger.exception("live speaker checkpoint failed")

    async def restart_recorder(reason: str) -> None:
        """Bring the recording back after the capture device died.

        On 2026-08-28 a 17-second device stall ended a real CEN4934 recording
        permanently: nothing owned the job of starting it again, and 33.7
        minutes of class was transcribed with no audio behind it.
        """
        nonlocal recorder, recorder_restarts, audio_failure_reported

        if supervisor is None or session_path is None or finalized:
            return
        if supervisor.stop_requested:
            return

        if recorder_restarts >= max_recorder_restarts:
            supervisor.set_worker(
                "audio",
                WorkerStatus.OFFLINE,
                detail=f"gave up after {recorder_restarts} restart(s): {reason}",
                failed=True,
            )
            return

        recorder_restarts += 1
        logger.warning(
            "restarting durable recorder attempt=%s reason=%s",
            recorder_restarts,
            reason,
        )
        supervisor.set_worker(
            "audio",
            WorkerStatus.RECOVERING,
            detail=reason,
            restarted=True,
        )

        if recorder is not None:
            try:
                recorder.stop(reason="restarting_after_device_failure")
            except Exception:
                logger.exception("could not cleanly stop the failed recorder")

        try:
            replacement, started, fallback_reason = await asyncio.to_thread(
                create_durable_recorder,
                session_path,
                mode=recorder_mode,
                sample_rate=16_000,
                channels=1,
                chunk_seconds=chunk_seconds,
                orphan_seconds=orphan_seconds,
                max_seconds=max_recording_seconds,
                microphone_factory=microphone_factory,
            )
        except Exception as error:
            supervisor.set_worker(
                "audio",
                WorkerStatus.FAILED,
                detail=f"restart raised {type(error).__name__}: {error}",
                failed=True,
            )
            return

        recorder = replacement
        if started:
            audio_failure_reported = False
            supervisor.record_event(
                CaptureEvent.AUDIO_RESTARTED,
                attempt=recorder_restarts,
                reason=reason,
                mode=getattr(replacement, "mode", "unknown"),
                fallback_reason=fallback_reason,
            )
            supervisor.set_worker(
                "audio",
                WorkerStatus.RECORDING,
                mode=getattr(replacement, "mode", "unknown"),
                isolated=bool(getattr(replacement, "isolated", False)),
            )
            print(
                f"[audio recovered] recorder restarted (attempt {recorder_restarts}); "
                "chunk numbering continues from the manifest"
            )
        else:
            supervisor.set_worker(
                "audio",
                WorkerStatus.FAILED,
                detail=str(getattr(replacement, "error", reason)),
                failed=True,
            )

    async def heartbeat_loop() -> None:
        """Own the lifecycle lock, the recorder heartbeat, and health.json."""
        nonlocal audio_failure_reported
        ticks = 0
        while True:
            ticks += 1
            heartbeat_active_session(capture.session_id)
            if session_path is not None:
                try:
                    write_supervisor_heartbeat(session_path)
                except Exception:
                    logger.exception("supervisor heartbeat write failed")

            if supervisor is not None and recorder is not None:
                try:
                    health = recorder.health()
                    status = str(health.get("status") or "offline")
                    mapped = {
                        "recording": WorkerStatus.RECORDING,
                        "stopped": WorkerStatus.STOPPED,
                        "failed": WorkerStatus.FAILED,
                    }.get(status, WorkerStatus.DEGRADED)
                    supervisor.audio_progress(
                        recorded_seconds=float(health.get("recorded_seconds") or 0.0),
                        chunks=int(health.get("chunks") or 0),
                        last_chunk=int(health.get("last_chunk") or 0),
                        last_write_age_seconds=health.get("last_write_age_seconds"),
                        status=mapped,
                        detail=health.get("error"),
                    )
                    if mapped is WorkerStatus.RECORDING:
                        audio_failure_reported = False
                    elif mapped is WorkerStatus.FAILED and not supervisor.stop_requested:
                        detail = str(
                            health.get("error")
                            or health.get("stopped_reason")
                            or "recorder reported failure"
                        )
                        if not audio_failure_reported:
                            # Once, not once per heartbeat. The 2026-08-28
                            # session wrote 302 identical AUDIO_FAILED events.
                            audio_failure_reported = True
                            supervisor.record_event(
                                CaptureEvent.AUDIO_FAILED,
                                detail=detail,
                            )
                        await restart_recorder(detail)
                except Exception:
                    logger.exception("recorder health poll failed")

            if supervisor is not None:
                if live_notes is not None:
                    supervisor.set_worker(
                        "notes",
                        {
                            "active": WorkerStatus.ACTIVE,
                            "degraded": WorkerStatus.DEGRADED,
                        }.get(live_notes.status, WorkerStatus.DEGRADED),
                        detail=live_notes.last_error,
                        generated=live_notes.generated_count,
                        last_update_seconds=round(live_notes.last_update_seconds, 1),
                    )
                supervisor.set_worker(
                    "speakers",
                    WorkerStatus.TRACKING,
                    speakers=len(speaker_ids),
                )
                supervisor.write_health(force=True)

            if ticks % 6 == 0:
                persist_live_speakers()

            await asyncio.sleep(5.0)

    async def answer_worker() -> None:
        while True:
            question = await answer_queue.get()
            try:
                if qa_manager is None or capture.transcript is None:
                    continue
                answer = await qa_manager.answer(
                    question,
                    recent_segments=list(capture.transcript.recent(40)),
                    course_code=course.code,
                    course_name=course.name,
                    current_topic=capture.context.current_topic,
                )
                if capture.questions is not None:
                    capture.questions.update_answer(question, answer)
                if answer:
                    print(f"[answer ready] {question.question}")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("live class answer worker failed")
                if supervisor is not None:
                    supervisor.set_worker(
                        "live_qa",
                        WorkerStatus.DEGRADED,
                        detail="live answer provider failed",
                        failed=True,
                    )
            finally:
                answer_queue.task_done()

    def schedule_answer(question) -> None:
        if not live_answers_enabled or qa_manager is None or capture.transcript is None:
            return
        if not qa_manager.should_answer(question.question):
            return
        try:
            answer_queue.put_nowait(question)
        except asyncio.QueueFull:
            logger.warning(
                "live answer queue full; question remains persisted without a live answer"
            )

    def process_turn_questions(reason: str) -> None:
        for turn_segment in turn_question_buffer.flush():
            outputs = question_assembler.feed(turn_segment)
            pending = question_assembler.flush()
            if pending is not None:
                outputs.append(pending)

            for question in outputs:
                if not should_answer_question(question.question):
                    continue
                if question_deduplicator.is_duplicate(
                    question.question,
                    timestamp_seconds=question.timestamp_seconds,
                ):
                    logger.info(
                        "duplicate live question suppressed reason=%s text=%r",
                        reason,
                        question.question,
                    )
                    continue
                current_role = speaker_tracker.resolve(question.speaker_id)
                question.speaker = current_role.role
                if capture.questions is not None:
                    capture.questions.add(question)
                capture.context.add_question(question)
                print(f"[question] {question.question}")
                schedule_answer(question)

    def schedule_turn_flush(delay_seconds: float, kind: str) -> None:
        nonlocal turn_flush_task, turn_flush_kind

        if (
            kind == "fallback"
            and turn_flush_task is not None
            and not turn_flush_task.done()
            and turn_flush_kind == "turn_commit"
        ):
            return

        if turn_flush_task is not None and not turn_flush_task.done():
            turn_flush_task.cancel()

        turn_flush_kind = kind

        async def runner() -> None:
            nonlocal turn_flush_task, turn_flush_kind
            try:
                await asyncio.sleep(delay_seconds)
                process_turn_questions(kind)
            except asyncio.CancelledError:
                raise
            finally:
                if asyncio.current_task() is turn_flush_task:
                    turn_flush_task = None
                    turn_flush_kind = None

        turn_flush_task = asyncio.create_task(
            runner(),
            name=f"nova-class-turn-flush-{kind}",
        )

    # --- transcription session (restartable, never session-ending) --------

    def build_transcription_session() -> AgentSession:
        """Create and wire one AgentSession. Safe to call again after a loss.

        Losing this session used to end the class. It is now just a worker: a
        new one is built, the session id and the recording are untouched, and
        the gap is recorded in ``events.jsonl``.
        """
        nonlocal live_session

        assert stt_factory is not None
        live_session = AgentSession(stt=stt_factory())
        started = time.monotonic()
        previous_end = 0.0

        @live_session.on("user_input_transcribed")
        def on_transcript(event):
            nonlocal previous_end, segment_count

            if not event.is_final:
                return

            text = " ".join((event.transcript or "").split())
            if not text:
                return

            end_seconds = max(0.0, time.monotonic() - started)
            start_seconds = previous_end
            previous_end = end_seconds

            raw_speaker = getattr(event, "speaker_id", None)
            speaker_id = str(raw_speaker) if raw_speaker is not None else None
            if speaker_id is not None:
                speaker_ids.add(speaker_id)

            resolved = speaker_tracker.observe(
                speaker_id,
                text,
                elapsed_seconds=end_seconds,
            )
            segment = TranscriptSegment(
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=text,
                speaker=resolved.role,
                speaker_confidence=resolved.confidence,
                topic=capture.context.current_topic,
                is_question=looks_like_question(text),
                speaker_id=speaker_id,
            )

            assert capture.transcript is not None
            capture.transcript.append(segment)
            capture.context.add_transcript(segment)
            segment_count += 1

            if supervisor is not None:
                supervisor.transcription_progress(end_seconds)

            if live_notes is not None:
                try:
                    live_notes.feed(segment, speaker_label=resolved.label)
                except Exception:
                    logger.exception("live notes ingestion failed")

            # Raw transcript is saved immediately, but Class Intelligence waits
            # for a committed human turn before deciding whether to answer.
            turn_question_buffer.feed(segment)
            schedule_turn_flush(3.5, "fallback")

            live = speaker_tracker.live_assessment(speaker_id)
            print(f"[{end_seconds:8.1f}s] [{live.label} {live.confidence:.2f}] {text}")

        @live_session.on("conversation_item_added")
        def on_conversation_item(event):
            item = getattr(event, "item", None)
            if item is None or getattr(item, "role", None) != "user":
                return
            # Give slow final STT a brief grace window after LiveKit commits
            # the human turn. This prevents one spoken question from firing
            # multiple model calls across finalized transcript chunks.
            schedule_turn_flush(0.45, "turn_commit")

        @live_session.on("error")
        def on_error(event):
            detail = type(getattr(event, "error", event)).__name__
            logger.error(
                "class capture error source=%s error=%s",
                getattr(event, "source", "session"),
                detail,
            )
            if supervisor is not None:
                supervisor.record_event(
                    CaptureEvent.STT_FAILED,
                    source=str(getattr(event, "source", "session")),
                    detail=detail,
                )
                # LiveKit retries STT internally without ever emitting "close",
                # so on 2026-08-28 a real eight-minute outage left health.json
                # claiming stt_gaps: []. Open the gap here; the next finalized
                # transcript closes it.
                if "stt" in detail.casefold() and not supervisor.stop_requested:
                    supervisor.stt_gap_start(f"stt_error:{detail}")

        @live_session.on("close")
        def on_close(event):
            # THE 2026-08-27 FAILURE POINT. An unexpected close used to be the
            # end of the class. It is now the start of a recovery -- unless the
            # human asked for it.
            reason = str(getattr(event, "reason", "unknown"))
            logger.warning("class transcription session closed reason=%s", reason)
            if supervisor is None or supervisor.stop_requested or finalized:
                return

            if _close_reason_is_user_stop(reason):
                # Ctrl+C in the console reaches us here and nowhere else. On
                # 2026-08-28 it was read as a crash: the class was finalized
                # "failed", the recorder was left running, and post-class notes
                # were skipped on purpose. Ctrl+C is a stop.
                logger.info("treating %s as a user stop request", reason)
                supervisor.request_stop(f"agent_session_closed:{reason}")
                supervisor.record_event(CaptureEvent.SESSION_STOPPING, reason=reason)
                return

            supervisor.stt_gap_start(f"agent_session_closed:{reason}")
            schedule_transcription_restart(reason)

        return live_session

    async def start_transcription_session() -> None:
        assert live_session is not None
        await live_session.start(
            agent=Agent(
                instructions=(
                    "Transcribe speech only. Do not speak, call tools, summarize, "
                    "or interact with the professor or students. Live answers are "
                    "handled silently by NOVA's separate Class Intelligence layer."
                )
            ),
            room=ctx.room,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    noise_cancellation=ai_coustics.audio_enhancement(
                        model=ai_coustics.EnhancerModel.QUAIL_VF_S
                    ),
                ),
            ),
        )
        if supervisor is not None:
            supervisor.set_worker("stt", WorkerStatus.CONNECTED)
            supervisor.record_event(CaptureEvent.STT_CONNECTED)

    def schedule_transcription_restart(reason: str) -> None:
        nonlocal restart_task
        if restart_task is not None and not restart_task.done():
            return
        restart_task = asyncio.create_task(
            restart_transcription(reason),
            name="nova-class-stt-restart",
        )

    async def restart_transcription(reason: str) -> None:
        """Rebuild transcription without touching the session or the audio."""
        nonlocal stt_restarts

        while stt_restarts < max_stt_restarts:
            if supervisor is None or supervisor.stop_requested or finalized:
                return
            stt_restarts += 1
            delay = min(30.0, 2.0 * stt_restarts)
            supervisor.stt_restarted()
            logger.warning(
                "restarting class transcription attempt=%s reason=%s delay=%.1fs",
                stt_restarts,
                reason,
                delay,
            )
            await asyncio.sleep(delay)
            if supervisor.stop_requested or finalized:
                return
            try:
                build_transcription_session()
                await start_transcription_session()
            except Exception:
                logger.exception("class transcription restart failed")
                continue

            print(
                f"[transcription recovered] attempt {stt_restarts} "
                f"(audio never stopped)"
            )
            return

        supervisor.set_worker(
            "stt",
            WorkerStatus.OFFLINE,
            detail=f"gave up after {stt_restarts} restart attempts",
            failed=True,
        )
        print(
            "TRANSCRIPTION OFFLINE: audio recording continues; "
            "the transcript will be incomplete for this stretch."
        )

    # --- finalization ------------------------------------------------------

    async def finalize(status: str = "completed") -> None:
        nonlocal finalized, heartbeat_task, turn_flush_task, turn_flush_kind
        nonlocal notes_task, restart_task
        if finalized:
            return
        finalized = True

        user_requested = supervisor is not None and supervisor.stop_requested
        keep_recording = (
            keep_audio_on_crash
            and not user_requested
            and status == "completed"
            and recorder is not None
            and getattr(recorder, "isolated", False)
        )

        for task in (heartbeat_task, restart_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        heartbeat_task = None
        restart_task = None

        # 1. Stop accepting new audio and close the current chunk cleanly.
        if recorder is not None and not keep_recording:
            try:
                recorder.stop(
                    reason="user_requested" if user_requested else f"job_{status}"
                )
                if supervisor is not None:
                    supervisor.record_event(CaptureEvent.AUDIO_STOPPED)
            except Exception as error:
                logger.exception("durable recorder shutdown failed")
                if supervisor is not None:
                    supervisor.note_finalization_error("audio_stop", error)
        elif keep_recording and supervisor is not None:
            supervisor.record_event(
                CaptureEvent.WORKER_LOST,
                detail=(
                    "intelligence process is shutting down without a user stop; "
                    "the durable recorder was deliberately left running"
                ),
            )

        # 2. Drain the live-question path.
        if turn_flush_task is not None and not turn_flush_task.done():
            turn_flush_task.cancel()
            try:
                await turn_flush_task
            except asyncio.CancelledError:
                pass
            turn_flush_task = None
            turn_flush_kind = None

        try:
            process_turn_questions("finalize")
        except Exception as error:
            logger.exception("turn-aware question flush failed")
            if supervisor is not None:
                supervisor.note_finalization_error("questions", error)

        if answer_worker_task is not None:
            try:
                await asyncio.wait_for(answer_queue.join(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "live answer queue did not fully drain before finalization; "
                    "unanswered questions remain persisted for post-class review"
                )
            finally:
                answer_worker_task.cancel()
                try:
                    await answer_worker_task
                except asyncio.CancelledError:
                    pass

        # 3. Flush live notes, then let the worker fold in whatever it can.
        if live_notes is not None:
            try:
                live_notes.flush(reason="finalize")
                drained = await live_notes.drain(
                    _env_float("NOVA_CLASS_NOTES_DRAIN_SECONDS", 25.0)
                )
                if not drained:
                    logger.warning(
                        "live notes did not drain before finalization; "
                        "queued evidence is persisted for post-class refinement"
                    )
            except Exception:
                logger.exception("live notes finalization failed")
            finally:
                if notes_task is not None and not notes_task.done():
                    notes_task.cancel()
                    try:
                        await notes_task
                    except asyncio.CancelledError:
                        pass
                notes_task = None
                try:
                    live_notes.write_notes()
                except Exception:
                    logger.exception("live notes could not be written")

        # 4. Automatic classroom roles are finalized only after the full
        # multi-speaker evidence is available. During live capture, raw
        # diarized IDs remain authoritative unless a manual teacher ID exists.
        speaker_tracker.finalize_roles()
        speaker_snapshot = speaker_tracker.snapshot()
        speaker_role_map = speaker_snapshot.get("speakers", {})
        persist_live_speakers()
        try:
            if capture.questions is not None:
                capture.questions.apply_speaker_roles(speaker_tracker.resolve)
        except Exception as error:
            logger.exception("question speaker-role finalization failed")
            if supervisor is not None:
                supervisor.note_finalization_error("question_roles", error)
        try:
            if qa_manager is not None:
                qa_manager.rebuild_log(speaker_tracker.resolve)
        except Exception as error:
            logger.exception("live Q&A speaker-role finalization failed")
            if supervisor is not None:
                supervisor.note_finalization_error("live_qa_roles", error)

        try:
            if session_path is not None:
                role_path = session_path / "speaker_roles.json"
                temporary = role_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(speaker_snapshot, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                temporary.replace(role_path)
                if capture.transcript is not None:
                    capture.transcript.rebuild_readable(speaker_role_map)
        except Exception as error:
            logger.exception("speaker-role finalization failed")
            if supervisor is not None:
                supervisor.note_finalization_error("speaker_roles", error)

        # 5. Persist the session's own metadata BEFORE resolving the outcome.
        # Resolving first would let a metadata failure go unreported, which is
        # exactly what happened on 2026-08-28: the outcome was already written
        # when update_metadata() raised.
        integrity = supervisor.audio_integrity() if supervisor is not None else None

        try:
            if capture.metadata is not None:
                capture.update_metadata(
                    transcript_segment_count=segment_count,
                    question_count=(
                        len(capture.questions.items())
                        if capture.questions is not None
                        else 0
                    ),
                    speaker_ids=sorted(speaker_ids),
                    speaker_roles=speaker_role_map,
                    live_answers_enabled=live_answers_enabled,
                    postprocess_enabled=postprocess_enabled,
                    stt_restarts=stt_restarts,
                    audio_chunks=(integrity.chunk_count if integrity else 0),
                    audio_seconds=(
                        round(integrity.recorded_seconds, 2) if integrity else 0.0
                    ),
                    audio_integrity_ok=(bool(integrity.healthy) if integrity else False),
                    pipeline=pipeline_selection.engine,
                    recorder_mode=getattr(recorder, "mode", "none"),
                    recorder_isolated=bool(getattr(recorder, "isolated", False)),
                    # Last: everything above is now a real measurement, so
                    # readers may stop treating these counts as placeholders.
                    metrics_finalized=True,
                )
        except Exception as error:
            logger.exception("class capture session metadata write failed")
            if supervisor is not None:
                supervisor.note_finalization_error("session_metadata", error)

        # Now decide what actually happened -- with any metadata failure counted.
        outcome = SessionOutcome.COMPLETED
        if supervisor is not None:
            outcome = supervisor.finalize(requested=None if status == "completed" else status)
        elif status != "completed":
            outcome = SessionOutcome.FAILED

        try:
            if capture.state.value == "active":
                capture.stop(status=outcome.value)
        except Exception as error:
            logger.exception("class capture session stop failed")
            if supervisor is not None:
                supervisor.note_finalization_error("session_stop", error)

        postprocess_pid = None
        should_postprocess = (
            postprocess_enabled
            and session_path is not None
            and not keep_recording
            and outcome
            in {SessionOutcome.COMPLETED, SessionOutcome.COMPLETED_WITH_WARNINGS}
        )
        if should_postprocess:
            try:
                postprocess_pid = launch_postprocess(session_path)
                if capture.metadata is not None:
                    capture.update_metadata(postprocess_pid=postprocess_pid)
            except Exception:
                logger.exception("post-class intelligence launch failed")

        # Final lifecycle action. Stop-NOVA-Class.ps1 waits for active.json to
        # disappear before it safely closes the legacy LiveKit console process.
        release_active_session(capture.session_id)

        print()
        print(f"Class Capture finished: {outcome.value.upper()}")
        print("Course:", course.code)
        if session_path is not None:
            print("Raw session:", session_path)
        if integrity is not None:
            print(
                f"Audio: {integrity.chunk_count} chunk(s), "
                f"{integrity.recorded_seconds / 60.0:.1f} min, "
                f"integrity {'OK' if integrity.healthy else 'NEEDS REVIEW'}"
            )
        if stt_restarts:
            print(f"Transcription restarts: {stt_restarts}")
        if supervisor is not None and supervisor.unrecovered_gap_count:
            print(
                f"Transcript gaps not backfilled: {supervisor.unrecovered_gap_count} "
                "(the audio for those stretches is on disk)"
            )
        if keep_recording:
            print(
                "AUDIO STILL RECORDING: this shutdown was not a user stop, so the "
                "durable recorder was left running on purpose."
            )
            print("Stop it with: .\\Stop-NOVA-Class.ps1")
        if supervisor is not None and supervisor.health_snapshot()["finalization_errors"]:
            print("FINALIZATION PROBLEMS:")
            for detail in supervisor.health_snapshot()["finalization_errors"]:
                print("  -", detail)
        if postprocess_pid:
            print("Post-class notes/presentation: STARTED")
        elif postprocess_enabled and should_postprocess:
            print("Post-class notes/presentation: COULD NOT START (raw data is safe)")
        elif postprocess_enabled:
            print("Post-class notes/presentation: DEFERRED")
        else:
            print("Post-class notes/presentation: DISABLED")
        print()

    async def shutdown() -> None:
        await finalize("completed")

    ctx.add_shutdown_callback(shutdown)

    try:
        session_path = capture.start()
        _configure_capture_log(session_path)

        supervisor = ClassSessionSupervisor(
            session_id=capture.session_id,
            course=course.code,
            session_path=session_path,
        )
        supervisor.open()

        heartbeat_task = asyncio.create_task(
            heartbeat_loop(),
            name="nova-class-heartbeat",
        )

        # --- P0: the recording starts before anything that can fail ------
        recorder, audio_started, fallback_reason = await asyncio.to_thread(
            create_durable_recorder,
            session_path,
            mode=recorder_mode,
            sample_rate=16_000,
            channels=1,
            chunk_seconds=chunk_seconds,
            orphan_seconds=orphan_seconds,
            max_seconds=max_recording_seconds,
            microphone_factory=microphone_factory,
        )
        audio_error = None if audio_started else getattr(recorder, "error", None)
        if audio_started:
            supervisor.set_worker(
                "audio",
                WorkerStatus.RECORDING,
                mode=recorder.mode,
                isolated=bool(recorder.isolated),
            )
            supervisor.record_event(
                CaptureEvent.AUDIO_STARTED,
                mode=recorder.mode,
                isolated=bool(recorder.isolated),
                fallback_reason=fallback_reason,
            )
        else:
            supervisor.set_worker(
                "audio",
                WorkerStatus.FAILED,
                detail=str(audio_error),
                failed=True,
            )
            supervisor.record_event(CaptureEvent.AUDIO_FAILED, detail=str(audio_error))
            logger.error("durable class audio could not start: %s", audio_error)

        capture.update_metadata(
            audio_enabled=bool(audio_started),
            audio_error=audio_error,
            live_answers_enabled=live_answers_enabled,
            postprocess_enabled=postprocess_enabled,
        )

        if auto_organize_downloads:
            try:
                organized = await asyncio.to_thread(
                    organize_recent_downloads_for_course,
                    course.code,
                )
                if organized:
                    print(f"AUTO-ORGANIZED:     {len(organized)} recent course material(s)")
            except Exception:
                logger.exception("recent Downloads course-material scan failed")
        else:
            print("AUTO-ORGANIZED:     disabled by NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS")

        context_library = CourseContextLibrary(course.code, session_path=session_path)
        try:
            context_library.write_context_manifest()
        except Exception:
            logger.exception("could not write class context manifest")

        seed_keyterms = course_stt_keyterms(course)
        keyterms = await asyncio.to_thread(
            context_library.build_stt_keyterms,
            seed_keyterms,
            limit=100,
        )
        try:
            context_library.write_stt_keyterms_manifest(keyterms)
        except Exception:
            logger.exception("could not write STT keyterm manifest")

        # Use only trusted course/domain terms for deterministic correction.
        # Material-mined terms still improve Deepgram recognition, but do not
        # automatically rewrite transcript/question text.
        #
        # Ahmed's own `STT-Corrections.md` rules are layered on top: he was in
        # the room, so his corrections outrank anything NOVA could infer, and
        # they are the only way to repair spoken mathematics ("n zero" -> n_0).
        terminology_interpreter = TerminologyInterpreter(
            seed_keyterms,
            corrections=load_course_corrections(course.code),
        )
        qa_manager = LiveQAManager(
            session_path=session_path,
            material_context_provider=context_library.build_context,
            terminology_interpreter=terminology_interpreter,
        )
        if live_answers_enabled:
            answer_worker_task = asyncio.create_task(
                answer_worker(),
                name="nova-class-live-answer-worker",
            )
            supervisor.set_worker("live_qa", WorkerStatus.ACTIVE)
        else:
            supervisor.set_worker("live_qa", WorkerStatus.DISABLED)

        if live_notes_enabled:
            def _note_status(status: str, detail: str | None) -> None:
                if supervisor is None:
                    return
                supervisor.record_event(
                    CaptureEvent.NOTES_DEGRADED
                    if status == "degraded"
                    else CaptureEvent.NOTES_UPDATED,
                    detail=detail,
                )

            def _note_topic(topic: str, at_seconds: float) -> None:
                capture.context.set_topic(topic)
                if capture.topics is not None:
                    try:
                        capture.topics.update(at_seconds, topic)
                    except Exception:
                        logger.exception("topic journal update failed")

            live_notes = LiveNotesWorker(
                session_path=session_path,
                course=course.code,
                title=title,
                generate=route_class_prompt,
                batcher=LiveNotesBatcher(
                    interval_seconds=_env_float("NOVA_CLASS_NOTES_INTERVAL_SECONDS", 75.0),
                    word_trigger=_env_int("NOVA_CLASS_NOTES_WORD_TRIGGER", 800),
                ),
                material_context_provider=context_library.build_context,
                on_topic=_note_topic,
                on_status=_note_status,
            )
            live_notes.restore_pending()
            notes_task = asyncio.create_task(
                live_notes.run(),
                name="nova-class-live-notes-worker",
            )
            supervisor.set_worker("notes", WorkerStatus.ACTIVE)
        else:
            supervisor.set_worker("notes", WorkerStatus.DISABLED)

        def stt_factory():
            return inference.STT(
                model="deepgram/nova-3-general",
                extra_kwargs={
                    # This is the currently documented LiveKit Inference
                    # streaming option and is already verified in the user's
                    # real runtime.
                    "diarize": True,
                    "keyterm": keyterms,
                    "punctuate": True,
                    "smart_format": True,
                },
            )

        print()
        print("=" * 76)
        print(f"NOVA CLASS INTELLIGENCE V{CAPTURE_VERSION}")
        print(f"COURSE:             {course.code} — {course.name}")
        print(f"COURSE RESOLUTION:  {resolution}")
        print("SILENT MODE:        YES")
        print(f"RAW SESSION:        {session_path}")
        print(f"TRANSCRIPT JSONL:   {session_path / 'transcript.jsonl'}")
        print(f"READABLE TRANSCRIPT:{session_path / 'transcript.txt'}")
        print(f"LIVE NOTES:         {session_path / 'live_notes.md'}")
        print(f"HEALTH:             {session_path / 'health.json'}")
        if audio_started:
            print(f"DURABLE AUDIO:      {session_path / 'audio'} ({recorder.mode})")
            print(
                "AUDIO ISOLATION:    "
                + (
                    "SEPARATE PROCESS (survives an intelligence crash)"
                    if recorder.isolated
                    else "IN-PROCESS FALLBACK (no crash isolation)"
                )
            )
            if fallback_reason:
                print(f"AUDIO FALLBACK:     {fallback_reason}")
        else:
            print("DURABLE AUDIO:      UNAVAILABLE (transcription continues)")
        if audio_error:
            print(f"AUDIO ERROR:        {audio_error}")
        print(f"AUDIO CHUNK:        {chunk_seconds:.0f}s")
        print(f"PIPELINE:           {pipeline_selection.engine} — {pipeline_selection.reason}")
        print(f"STT KEYTERMS:       {len(keyterms)}")
        print("SPEAKER DIARIZE:    ON")
        print(f"LIVE ANSWERS:       {'ON' if live_answers_enabled else 'OFF'}")
        print(f"LIVE NOTES:         {'ON' if live_notes_enabled else 'OFF'}")
        print(f"POST-CLASS NOTES:   {'ON' if postprocess_enabled else 'OFF'}")
        print("STATUS COMMAND:     .\\Get-NOVA-Class-Status.ps1")
        print("STOP COMMAND:       .\\Stop-NOVA-Class.ps1")
        print("=" * 76)
        print()

        build_transcription_session()
        await start_transcription_session()

        await ctx.connect()

        async def watch_for_stop_request() -> None:
            await wait_for_stop_request(capture.session_id)
            print()
            print("NOVA Class Capture stop requested.")
            print("Finishing pending transcript work and saving the session...")
            if supervisor is not None:
                supervisor.request_stop("user_requested")
                supervisor.record_event(CaptureEvent.SESSION_STOPPING)
            if live_session is not None:
                live_session.shutdown(drain=True)
            await asyncio.sleep(0.25)
            ctx.shutdown(reason="class capture stop requested")

        asyncio.create_task(
            watch_for_stop_request(),
            name="nova-class-stop-watcher",
        )

    except Exception:
        await finalize("error")
        raise


if __name__ == "__main__":
    cli.run_app(server)
