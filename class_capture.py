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
    LocalWaveRecorder,
    QuestionAssembler,
    QuestionDeduplicator,
    SpeakerRole,
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
from nova_capture.intelligence import LiveQAManager
from nova_capture.postprocess import launch_postprocess
from nova_capture.question_detection import looks_like_question, should_answer_question
from nova_capture.speakers import SpeakerRoleTracker
from nova_capture.terminology import TerminologyInterpreter
from nova_school import CourseRegistry, course_stt_keyterms, resolve_current_course
from nova_school.context import CourseContextLibrary, organize_recent_downloads_for_course
from nova_school.resolver import resolve_course_override


load_dotenv(".env.local")
load_dotenv(".env")

CAPTURE_VERSION = "1.3.6"
logger = logging.getLogger("nova.class_capture")
server = AgentServer()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() not in {"0", "false", "no", "off"}


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
    auto_organize_downloads = _env_bool("NOVA_CLASS_AUTO_ORGANIZE_DOWNLOADS", False)

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
    microphone: LocalMicrophoneCapture | None = None
    live_session: AgentSession | None = None
    heartbeat_task: asyncio.Task | None = None
    finalized = False
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

    async def heartbeat_loop() -> None:
        while True:
            heartbeat_active_session(capture.session_id)
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

    async def finalize(status: str = "completed") -> None:
        nonlocal finalized, heartbeat_task, turn_flush_task, turn_flush_kind
        if finalized:
            return
        finalized = True

        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            heartbeat_task = None

        if microphone is not None:
            try:
                microphone.stop()
            except Exception:
                logger.exception("local microphone shutdown failed")

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
        except Exception:
            logger.exception("turn-aware question flush failed")

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

        # Automatic classroom roles are finalized only after the full
        # multi-speaker evidence is available. During live capture, raw
        # diarized IDs remain authoritative unless a manual teacher ID exists.
        speaker_tracker.finalize_roles()
        speaker_snapshot = speaker_tracker.snapshot()
        speaker_role_map = speaker_snapshot.get("speakers", {})
        try:
            if capture.questions is not None:
                capture.questions.apply_speaker_roles(speaker_tracker.resolve)
        except Exception:
            logger.exception("question speaker-role finalization failed")
        try:
            if qa_manager is not None:
                qa_manager.rebuild_log(speaker_tracker.resolve)
        except Exception:
            logger.exception("live Q&A speaker-role finalization failed")

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
        except Exception:
            logger.exception("speaker-role finalization failed")

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
                )
            if capture.state.value == "active":
                capture.stop(status=status)
        except Exception:
            logger.exception("class capture session finalization failed")

        postprocess_pid = None
        if status == "completed" and postprocess_enabled and session_path is not None:
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
        print("Class Capture saved.")
        print("Course:", course.code)
        if session_path is not None:
            print("Raw session:", session_path)
        if postprocess_pid:
            print("Post-class notes/presentation: STARTED")
        elif postprocess_enabled:
            print("Post-class notes/presentation: COULD NOT START (raw data is safe)")
        else:
            print("Post-class notes/presentation: DISABLED")
        print()

    async def shutdown() -> None:
        await finalize("completed")

    ctx.add_shutdown_callback(shutdown)
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(),
        name="nova-class-heartbeat",
    )

    try:
        session_path = capture.start()

        recorder = LocalWaveRecorder(
            session_path / "audio.wav",
            sample_rate=16_000,
            channels=1,
            sample_width=2,
        )
        microphone = LocalMicrophoneCapture(recorder)

        audio_error = None
        try:
            microphone.start()
        except Exception as error:
            audio_error = f"{type(error).__name__}: {error}"
            logger.exception("local class audio backup could not start")

        capture.update_metadata(
            audio_enabled=bool(microphone.active),
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
        terminology_interpreter = TerminologyInterpreter(seed_keyterms)
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

        stt = inference.STT(
            model="deepgram/nova-3-general",
            extra_kwargs={
                # This is the currently documented LiveKit Inference streaming
                # option and is already verified in the user's real runtime.
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
        print(
            "LOCAL AUDIO:        "
            + (
                str(session_path / "audio.wav")
                if microphone.active
                else "UNAVAILABLE (transcription continues)"
            )
        )
        if audio_error:
            print("AUDIO ERROR:        " + audio_error)
        print(f"STT KEYTERMS:       {len(keyterms)}")
        print("SPEAKER DIARIZE:    ON")
        print(f"LIVE ANSWERS:       {'ON' if live_answers_enabled else 'OFF'}")
        print(f"POST-CLASS NOTES:   {'ON' if postprocess_enabled else 'OFF'}")
        print("STOP COMMAND:       .\\Stop-NOVA-Class.ps1")
        print("=" * 76)
        print()

        live_session = AgentSession(stt=stt)
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

            # Raw transcript is saved immediately, but Class Intelligence waits
            # for a committed human turn before deciding whether to answer.
            turn_question_buffer.feed(segment)
            schedule_turn_flush(3.5, "fallback")

            label = resolved.label
            print(f"[{end_seconds:8.1f}s] [{label}] {text}")

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
            logger.error(
                "class capture error source=%s error=%s",
                getattr(event, "source", "session"),
                type(getattr(event, "error", event)).__name__,
            )

        async def watch_for_stop_request() -> None:
            await wait_for_stop_request(capture.session_id)
            print()
            print("NOVA Class Capture stop requested.")
            print("Finishing pending transcript work and saving the session...")
            live_session.shutdown(drain=True)
            await asyncio.sleep(0.25)
            ctx.shutdown(reason="class capture stop requested")

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

        await ctx.connect()

        asyncio.create_task(
            watch_for_stop_request(),
            name="nova-class-stop-watcher",
        )

    except Exception:
        await finalize("error")
        raise


if __name__ == "__main__":
    cli.run_app(server)
