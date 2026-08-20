from __future__ import annotations

import asyncio

from nova_runtime import EventBus, JobState, NovaRuntime, RuntimeEvent


def test_runtime_can_run_background_job() -> None:
    async def scenario() -> None:
        runtime = NovaRuntime()
        job_id = await runtime.jobs.start(
            "test-job",
            asyncio.sleep(0.01, result="done"),
        )
        snapshot = await runtime.jobs.wait(job_id)
        assert snapshot.state is JobState.COMPLETED
        assert snapshot.result == "done"
        await runtime.shutdown()
        assert runtime.closed is True

    asyncio.run(scenario())


def test_runtime_cancels_background_job_cleanly() -> None:
    async def scenario() -> None:
        runtime = NovaRuntime()
        job_id = await runtime.jobs.start(
            "long-job",
            asyncio.sleep(10),
        )
        assert await runtime.jobs.cancel(job_id) is True
        snapshot = runtime.jobs.snapshot(job_id)
        assert snapshot is not None
        assert snapshot.state is JobState.CANCELLED
        await runtime.shutdown()

    asyncio.run(scenario())


def test_event_bus_supports_sync_and_async_handlers() -> None:
    async def scenario() -> None:
        bus = EventBus()
        seen: list[str] = []

        def sync_handler(event: RuntimeEvent) -> None:
            seen.append("sync:" + event.kind)

        async def async_handler(event: RuntimeEvent) -> None:
            seen.append("async:" + event.kind)

        bus.subscribe("class.started", sync_handler)
        bus.subscribe("class.started", async_handler)
        await bus.publish(RuntimeEvent("class.started"))
        assert seen == ["sync:class.started", "async:class.started"]

    asyncio.run(scenario())


def test_runtime_context_is_ephemeral() -> None:
    runtime = NovaRuntime()
    runtime.context.recent_intent = "record this class"
    runtime.context.ephemeral["topic"] = "scheduling"
    runtime.context.clear_ephemeral()
    assert runtime.context.recent_intent is None
    assert runtime.context.ephemeral == {}
