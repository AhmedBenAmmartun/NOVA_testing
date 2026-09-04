"""Class Intelligence is cloud-first: it defers, it never quietly goes local.

Real sessions showed the failure this file exists to prevent. On 2026-08-28 a
lecture hit the class cloud cap and the router logged 215 budget skips for groq
*and* openai, after which Class Intelligence selected ollama 86 times and failed
130 of those calls -- a whole lecture of heavy local inference on the PC. On
2026-09-01 the cap was not even reached: both cloud providers were simply
unreachable, and Class Intelligence still selected ollama 42 times.

Both paths ended at a local model because ``_route`` carried its own hardcoded
provider chain that terminated in ollama, and a local provider bypasses the
cloud budget gate entirely (``nova_core/router.py`` only meters providers whose
``is_local`` is false). Cloud exhaustion therefore became heavy local inference
instead of deferred work.

The rule this pins: when cloud capacity is gone, class intelligence returns
None, the evidence stays in the durable queue, the status tells the truth, and
no local model is started.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from nova_capture import intelligence
from nova_capture.class_budget import ClassCloudUsageBudget
from nova_capture.live_notes import LiveNotesWorker, NoteBatch
from nova_capture.models import SpeakerRole, TranscriptSegment
from nova_capture.supervisor import ClassSessionSupervisor, WorkerStatus
from nova_capture.transcript import TranscriptJournal
from nova_core import (
    ModelRouter,
    ProviderName,
    ProviderRegistry,
    load_configuration,
)
from providers import ProviderResponse, ProviderUnavailableError
from providers.base import ModelProvider


class RecordingProvider(ModelProvider):
    """A stub provider that records every generate() call it receives."""

    def __init__(
        self,
        name: str,
        *,
        is_local: bool = False,
        reply: str | None = "cloud answer",
        error: Exception | None = None,
    ) -> None:
        super().__init__(model=f"{name}-test-model")
        self.name = name
        self.is_local = is_local
        self.reply = reply
        self.error = error
        self.calls: list[str] = []

    @property
    def configured(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        self.calls.append(prompt)
        if self.error is not None:
            raise self.error
        return ProviderResponse(
            text=self.reply or "",
            provider=self.name,
            model=self.model,
            metadata={},
        )


def _budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, limit: int
) -> ClassCloudUsageBudget:
    """A class cloud budget isolated to tmp_path, never the real capture root."""
    monkeypatch.setenv(
        "NOVA_CLASS_CLOUD_USAGE_FILE", str(tmp_path / "class-budget.json")
    )
    monkeypatch.setenv("NOVA_CLASS_CLOUD_DAILY_REQUEST_LIMIT", str(limit))
    return ClassCloudUsageBudget()


def _router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    limit: int = 100,
    openai: RecordingProvider | None = None,
    groq: RecordingProvider | None = None,
    ollama: RecordingProvider | None = None,
) -> tuple[ModelRouter, dict[str, RecordingProvider]]:
    configuration = load_configuration()
    registry = ProviderRegistry(configuration)
    providers = {
        "openai": openai or RecordingProvider("openai"),
        "groq": groq or RecordingProvider("groq"),
        "ollama": ollama
        or RecordingProvider("ollama", is_local=True, reply="local answer"),
    }
    registry.register(ProviderName.OPENAI, providers["openai"])
    registry.register(ProviderName.GROQ, providers["groq"])
    registry.register(ProviderName.OLLAMA, providers["ollama"])
    router = ModelRouter(
        configuration=configuration,
        registry=registry,
        cloud_budget=_budget(tmp_path, monkeypatch, limit=limit),
    )
    return router, providers


@pytest.fixture(autouse=True)
def _reset_class_router(monkeypatch: pytest.MonkeyPatch):
    """_get_class_router() memoises into a module global with no reset hook."""
    monkeypatch.setattr(intelligence, "_class_router", None, raising=False)
    monkeypatch.delenv("NOVA_CLASS_ALLOW_LOCAL_FALLBACK", raising=False)
    monkeypatch.delenv("NOVA_CLASS_CLOUD_PROVIDER_ORDER", raising=False)
    yield
    monkeypatch.setattr(intelligence, "_class_router", None, raising=False)


def _install(monkeypatch: pytest.MonkeyPatch, router: ModelRouter) -> None:
    monkeypatch.setattr(intelligence, "_get_class_router", lambda: router)


# --- the core rule ---------------------------------------------------------


def test_an_exhausted_cloud_budget_never_starts_a_local_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, providers = _router(tmp_path, monkeypatch, limit=0)
    _install(monkeypatch, router)

    answer = asyncio.run(intelligence._route("summarise this lecture window"))

    assert answer is None, "an exhausted cloud budget must defer, not answer"
    assert providers["ollama"].calls == [], (
        "a class with no cloud capacity must never run heavy local inference"
    )


def test_unreachable_cloud_providers_defer_instead_of_going_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outage = ProviderUnavailableError("connection refused")
    router, providers = _router(
        tmp_path,
        monkeypatch,
        openai=RecordingProvider("openai", error=outage),
        groq=RecordingProvider("groq", error=outage),
    )
    _install(monkeypatch, router)

    answer = asyncio.run(intelligence._route("summarise this lecture window"))

    assert answer is None
    assert providers["openai"].calls, "the cloud tier must still be attempted"
    assert providers["groq"].calls, "the secondary cloud provider must be tried"
    assert providers["ollama"].calls == [], (
        "a cloud outage is deferred work, not a reason to run a local model"
    )


def test_a_local_provider_can_never_be_configured_into_the_class_cloud_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOVA_CLASS_CLOUD_PROVIDER_ORDER", "groq,ollama,openai")
    outage = ProviderUnavailableError("connection refused")
    router, providers = _router(
        tmp_path,
        monkeypatch,
        openai=RecordingProvider("openai", error=outage),
        groq=RecordingProvider("groq", error=outage),
    )
    _install(monkeypatch, router)

    assert asyncio.run(intelligence._route("window")) is None
    assert providers["ollama"].calls == [], (
        "the cloud tier is defined by is_local, so configuration cannot "
        "smuggle a local model back into the automatic class path"
    )


def test_a_healthy_cloud_provider_still_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, providers = _router(tmp_path, monkeypatch)
    _install(monkeypatch, router)

    assert asyncio.run(intelligence._route("window")) == "cloud answer"
    assert providers["ollama"].calls == []


# --- truthful status -------------------------------------------------------


def test_a_deferral_reports_budget_exhaustion_as_its_own_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, _providers = _router(tmp_path, monkeypatch, limit=0)
    _install(monkeypatch, router)

    asyncio.run(intelligence._route("window"))
    outcome = intelligence.last_class_route_outcome()

    assert outcome is not None
    assert outcome.deferred, "an unanswered class request is deferred work"
    assert outcome.reason == "class_cloud_budget_exhausted"
    assert "budget" in outcome.detail.lower()


def test_a_deferral_distinguishes_an_outage_from_an_exhausted_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outage = ProviderUnavailableError("connection refused")
    router, _providers = _router(
        tmp_path,
        monkeypatch,
        openai=RecordingProvider("openai", error=outage),
        groq=RecordingProvider("groq", error=outage),
    )
    _install(monkeypatch, router)

    asyncio.run(intelligence._route("window"))
    outcome = intelligence.last_class_route_outcome()

    assert outcome is not None
    assert outcome.deferred
    assert outcome.reason == "cloud_providers_unavailable", (
        "status must not blame the budget for a network outage"
    )


def test_a_disabled_budget_is_never_blamed_for_an_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A switched-off budget blocks nothing, but its counter still climbs."""
    outage = ProviderUnavailableError("connection refused")
    router, _providers = _router(
        tmp_path,
        monkeypatch,
        limit=0,
        openai=RecordingProvider("openai", error=outage),
        groq=RecordingProvider("groq", error=outage),
    )
    monkeypatch.setenv("NOVA_CLASS_CLOUD_BUDGET_ENABLED", "false")
    router.cloud_budget = ClassCloudUsageBudget()
    _install(monkeypatch, router)

    asyncio.run(intelligence._route("window"))
    outcome = intelligence.last_class_route_outcome()

    assert outcome is not None
    assert outcome.reason == "cloud_providers_unavailable"


def test_a_successful_answer_clears_the_deferred_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, _providers = _router(tmp_path, monkeypatch)
    _install(monkeypatch, router)

    asyncio.run(intelligence._route("window"))
    outcome = intelligence.last_class_route_outcome()

    assert outcome is not None
    assert not outcome.deferred
    assert outcome.provider == "openai"


# --- the class keeps running ----------------------------------------------


def test_live_notes_keep_the_evidence_queued_when_intelligence_defers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, providers = _router(tmp_path, monkeypatch, limit=0)
    _install(monkeypatch, router)

    worker = LiveNotesWorker(
        session_path=tmp_path,
        course="COP3710",
        title="Deferred lecture",
        generate=intelligence.route_class_prompt,
        max_attempts_per_batch=1,
    )
    lines = [f"[professor] concept {index} explained at length" for index in range(5)]
    batch = NoteBatch(
        index=1,
        start_seconds=0.0,
        end_seconds=25.0,
        words=sum(len(line.split()) for line in lines),
        lines=lines,
        reason="interval",
    )
    worker.queue.enqueue(batch)

    assert asyncio.run(worker.process_one(batch)) is False
    assert worker.status == "degraded", "the session must admit reduced intelligence"
    assert [item.index for item in worker.queue.pending()] == [1], (
        "deferred work must survive in the durable queue"
    )
    assert providers["ollama"].calls == [], (
        "a deferred lecture must not drag the PC into local inference"
    )
    assert "degraded" in (tmp_path / "live_notes.md").read_text(encoding="utf-8")


def test_a_deferred_lecture_keeps_recording_and_transcribing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The required failure case: no cloud capacity, class carries on anyway."""
    router, providers = _router(tmp_path, monkeypatch, limit=0)
    _install(monkeypatch, router)

    supervisor = ClassSessionSupervisor(
        session_id="deferred-session",
        course="COP3710",
        session_path=tmp_path,
    )
    supervisor.set_worker("audio", WorkerStatus.RECORDING)
    transcript = TranscriptJournal(tmp_path / "transcript.jsonl")

    for index in range(5):
        transcript.append(
            TranscriptSegment(
                start_seconds=float(index * 5),
                end_seconds=float(index * 5 + 5),
                text=f"lecture segment {index}",
                speaker=SpeakerRole.PROFESSOR,
                speaker_id="0",
            )
        )
        supervisor.audio_progress(
            recorded_seconds=float(index * 5 + 5),
            chunks=index + 1,
            last_chunk=index,
            last_write_age_seconds=0.2,
        )
        assert asyncio.run(intelligence._route(f"window {index}")) is None

    outcome = intelligence.last_class_route_outcome()
    assert outcome is not None and outcome.deferred

    assert supervisor.worker_status("audio") is WorkerStatus.RECORDING, (
        "losing every cloud provider must never stop the recording"
    )
    assert providers["ollama"].calls == [], (
        "a full cloud outage must not put heavy inference on the class PC"
    )

    written = (tmp_path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(written) == 5, "the transcript is evidence and survives independently"

    health = supervisor.health_snapshot()
    assert health["workers"]["audio"]["status"] == "recording"


# --- the explicit escape hatch --------------------------------------------


def test_the_local_model_runs_only_when_it_is_explicitly_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    router, providers = _router(tmp_path, monkeypatch, limit=0)
    _install(monkeypatch, router)
    monkeypatch.setenv("NOVA_CLASS_ALLOW_LOCAL_FALLBACK", "1")

    answer = asyncio.run(intelligence._route("window"))

    assert answer == "local answer"
    assert providers["ollama"].calls, (
        "the emergency local path stays available, but only on request"
    )


# --- normal NOVA is untouched ---------------------------------------------


def test_normal_nova_routing_still_falls_back_to_the_local_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """nova_core keeps its own fallback policy; only class routing changed."""
    router, providers = _router(tmp_path, monkeypatch, limit=0)

    response = asyncio.run(
        router.route("a normal NOVA specialist request", role="reasoning")
    )

    assert response.provider == "ollama"
    assert providers["ollama"].calls, (
        "general NOVA assistant routing must keep its local fallback"
    )
