"""Several jobs at once must become a graph, not a flat list.

`BackgroundJobManager.start(name, awaitable)` dispatches immediately: it takes a
one-shot coroutine and calls `asyncio.create_task` on the spot. That is correct
for a single fire-and-forget job and cannot express what an orchestrator needs
-- "research this, then fix the bug, then test it, and meanwhile organize my
notes" is a dependency graph with parallel branches.

Two things block that today, and both are structural rather than missing
features:

* a *consumed coroutine* cannot be re-awaited, so retry and deferred dispatch
  are impossible to express;
* there is no gate between accepting a job and running it.

So `submit()` is added beside `start()`, taking a FACTORY rather than a
coroutine. `start()` stays exactly as it is -- `nova_school/automation.py` and
the school CLI depend on its current behavior, including its infinite-loop
watcher job and its over-limit RuntimeError.
"""

from __future__ import annotations

import asyncio

import pytest

from nova_runtime import NovaRuntime
from nova_runtime.jobs import BackgroundJobManager, JobSpec
from nova_runtime.task_state import JobState


def _run(coro):
    return asyncio.run(coro)


# --- the existing contract, which several live consumers depend on ----------


def test_start_still_takes_a_coroutine_and_completes() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def work():
            return "done"

        job_id = await manager.start("legacy", work())
        return await manager.wait(job_id)

    snapshot = _run(scenario())

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.result == "done"


def test_start_still_raises_over_the_job_limit() -> None:
    """`nova_school` relies on this refusing rather than queueing."""

    async def scenario():
        manager = BackgroundJobManager(max_jobs=1)

        async def forever():
            await asyncio.sleep(60)

        await manager.start("first", forever())
        try:
            await manager.start("second", forever())
        except RuntimeError:
            return "refused"
        finally:
            await manager.shutdown()
        return "queued"

    assert _run(scenario()) == "refused"


def test_a_snapshot_exists_immediately_after_start_returns() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def work():
            await asyncio.sleep(0.01)

        job_id = await manager.start("probe", work())
        snapshot = manager.snapshot(job_id)
        await manager.shutdown()
        return snapshot

    assert _run(scenario()) is not None


# --- submit(): a factory, so a job can be deferred or retried ---------------


def test_submit_runs_a_job_from_a_factory() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def work():
            return "from factory"

        job_id = await manager.submit(JobSpec(name="factory", factory=work))
        return await manager.wait(job_id)

    snapshot = _run(scenario())

    assert snapshot.state is JobState.COMPLETED
    assert snapshot.result == "from factory"


def test_a_dependent_job_waits_for_its_dependency() -> None:
    """The whole point: order is declared, not hoped for."""
    order: list[str] = []

    async def scenario():
        manager = BackgroundJobManager()

        async def first():
            await asyncio.sleep(0.02)
            order.append("first")
            return 1

        async def second():
            order.append("second")
            return 2

        a = await manager.submit(JobSpec(name="a", factory=first))
        b = await manager.submit(JobSpec(name="b", factory=second, depends_on=(a,)))
        await manager.wait(a)
        await manager.wait(b)

    _run(scenario())

    assert order == ["first", "second"]


def test_a_waiting_job_reports_that_it_is_waiting() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def slow():
            await asyncio.sleep(0.05)

        async def dependent():
            return "ran"

        a = await manager.submit(JobSpec(name="a", factory=slow))
        b = await manager.submit(
            JobSpec(name="b", factory=dependent, depends_on=(a,))
        )
        state = manager.snapshot(b).state
        await manager.wait(a)
        await manager.wait(b)
        return state

    assert _run(scenario()) is JobState.WAITING_DEPENDENCY


def test_independent_jobs_still_run_concurrently() -> None:
    """Dependencies must not accidentally serialize unrelated work."""

    async def scenario():
        manager = BackgroundJobManager()
        running = {"peak": 0, "now": 0}

        async def work():
            running["now"] += 1
            running["peak"] = max(running["peak"], running["now"])
            await asyncio.sleep(0.02)
            running["now"] -= 1

        ids = [
            await manager.submit(JobSpec(name=f"j{i}", factory=work))
            for i in range(3)
        ]
        for job_id in ids:
            await manager.wait(job_id)
        return running["peak"]

    assert _run(scenario()) > 1


def test_a_dependency_that_fails_blocks_its_dependent() -> None:
    """A dependent must not silently run on a broken prerequisite."""

    async def scenario():
        manager = BackgroundJobManager()

        async def boom():
            raise ValueError("nope")

        async def after():
            return "should not run"

        a = await manager.submit(JobSpec(name="a", factory=boom))
        b = await manager.submit(JobSpec(name="b", factory=after, depends_on=(a,)))
        await manager.wait(a)
        await manager.wait(b)
        return manager.snapshot(b)

    snapshot = _run(scenario())

    assert snapshot.state is JobState.BLOCKED
    assert snapshot.result != "should not run"


def test_a_cancelled_dependency_also_blocks_its_dependent() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def forever():
            await asyncio.sleep(60)

        async def after():
            return "should not run"

        a = await manager.submit(JobSpec(name="a", factory=forever))
        b = await manager.submit(JobSpec(name="b", factory=after, depends_on=(a,)))
        await manager.cancel(a)
        await manager.wait(b)
        return manager.snapshot(b).state

    assert _run(scenario()) is JobState.BLOCKED


def test_a_dependency_on_an_unknown_job_blocks_rather_than_hangs() -> None:
    """A typo in a graph must fail loudly, never wedge the runtime forever."""

    async def scenario():
        manager = BackgroundJobManager()

        async def work():
            return "ran"

        job_id = await manager.submit(
            JobSpec(name="orphan", factory=work, depends_on=("does-not-exist",))
        )
        await manager.wait(job_id)
        return manager.snapshot(job_id).state

    assert _run(scenario()) is JobState.BLOCKED


def test_the_graph_metadata_reaches_the_snapshot() -> None:
    async def scenario():
        manager = BackgroundJobManager()

        async def work():
            return None

        a = await manager.submit(JobSpec(name="a", factory=work))
        b = await manager.submit(
            JobSpec(
                name="b",
                factory=work,
                depends_on=(a,),
                parent_id=a,
                priority=7,
                owner="research-worker",
                required_permissions=("internet_read",),
            )
        )
        await manager.wait(a)
        await manager.wait(b)
        return manager.snapshot(b)

    snapshot = _run(scenario())

    assert snapshot.priority == 7
    assert snapshot.owner == "research-worker"
    assert snapshot.required_permissions == ("internet_read",)


def test_the_runtime_exposes_the_scheduler() -> None:
    runtime = NovaRuntime()

    assert hasattr(runtime.jobs, "submit")


def test_shutdown_does_not_hang_on_a_waiting_job() -> None:
    """A job still waiting on a dependency must not block a clean shutdown."""

    async def scenario():
        manager = BackgroundJobManager()

        async def forever():
            await asyncio.sleep(60)

        async def after():
            return "never"

        a = await manager.submit(JobSpec(name="a", factory=forever))
        await manager.submit(JobSpec(name="b", factory=after, depends_on=(a,)))
        await asyncio.wait_for(manager.shutdown(), timeout=5)
        return True

    assert _run(scenario()) is True
