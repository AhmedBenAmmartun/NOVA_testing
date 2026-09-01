"""Pipeline selection, and the Pipecat pilot's honesty about what it needs."""

from __future__ import annotations

import asyncio

import pytest

from nova_capture import pipeline as pipeline_module
from nova_capture.pipeline import (
    LIVEKIT,
    PIPECAT,
    PipecatTranscriptionEngine,
    TranscriptionEngineUnavailable,
    describe_pipecat_support,
    resolve_class_pipeline,
)


def test_default_pipeline_is_the_verified_livekit_path(monkeypatch) -> None:
    monkeypatch.delenv("NOVA_CLASS_PIPELINE", raising=False)
    selection = resolve_class_pipeline()
    assert selection.engine == LIVEKIT
    assert selection.available
    assert not selection.fell_back
    assert "LiveKit Inference" in selection.reason


def test_unknown_pipeline_value_falls_back_loudly(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_CLASS_PIPELINE", "whisper-on-a-toaster")
    selection = resolve_class_pipeline()
    assert selection.engine == LIVEKIT
    assert selection.fell_back
    assert "unknown NOVA_CLASS_PIPELINE" in selection.reason


def test_requesting_pipecat_without_pipecat_falls_back_with_reasons(monkeypatch) -> None:
    monkeypatch.setenv("NOVA_CLASS_PIPELINE", "pipecat")
    selection = resolve_class_pipeline()

    assert selection.requested == PIPECAT
    assert selection.engine == LIVEKIT, "a class must never fail to record over a pilot"
    assert not selection.available
    assert "Pipecat unavailable" in selection.reason
    assert selection.details["blockers"]


def test_pipecat_support_probe_reports_specific_blockers() -> None:
    support = describe_pipecat_support()
    assert set(support) == {
        "modules",
        "deepgram_api_key_configured",
        "blockers",
        "usable",
    }
    assert "pipecat" in support["modules"]
    assert "pyaudio" in support["modules"]
    # This machine does not have pipecat installed; the probe must say so
    # rather than assume.
    assert support["usable"] is False
    assert any("missing modules" in item for item in support["blockers"])


def test_support_probe_never_reveals_a_credential(monkeypatch) -> None:
    monkeypatch.setenv("DEEPGRAM_API_KEY", "super-secret-value")
    support = describe_pipecat_support()
    assert support["deepgram_api_key_configured"] is True
    assert "super-secret-value" not in repr(support)


def test_pipecat_engine_refuses_to_pretend_it_can_run() -> None:
    engine = PipecatTranscriptionEngine(keyterms=["aggregation", "composition"])
    described = engine.describe()
    assert described["verified"] is False
    assert described["keyterms"] == 2

    with pytest.raises(TranscriptionEngineUnavailable) as error:
        asyncio.run(engine.start(on_transcript=lambda _event: None))
    assert "cannot start" in str(error.value)


def test_pipecat_selection_when_everything_is_present(monkeypatch) -> None:
    """The selection logic itself works; only this machine lacks the deps."""
    monkeypatch.setattr(pipeline_module, "_module_present", lambda _name: True)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "present")
    monkeypatch.setenv("NOVA_CLASS_PIPELINE", "pipecat")

    selection = resolve_class_pipeline()
    assert selection.engine == PIPECAT
    assert selection.available
    assert not selection.fell_back


def test_stop_is_safe_before_start() -> None:
    engine = PipecatTranscriptionEngine()
    asyncio.run(engine.stop())  # must not raise
