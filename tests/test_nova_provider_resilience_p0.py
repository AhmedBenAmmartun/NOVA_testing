from __future__ import annotations

from pathlib import Path

import pytest

from nova_core import realtime
from nova_core.configuration import ProviderName


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_realtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NOVA_REALTIME_PROVIDER",
        "NOVA_REALTIME_MODEL",
        "NOVA_VOICE",
        "NOVA_TEMPERATURE",
        "NOVA_ENABLE_GEMINI",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    # Unit tests never send this value over the network. It only proves that
    # configuration detection does not require reading or exposing a real key.
    monkeypatch.setenv("GOOGLE_API_KEY", "unit-test-placeholder-secret")
    monkeypatch.setenv("NOVA_ENABLE_GEMINI", "true")


def test_default_native_realtime_selection_remains_gemini() -> None:
    selection = realtime.load_realtime_selection()

    assert selection.provider is ProviderName.GEMINI
    assert selection.route == "gemini_realtime"
    assert selection.model == (
        "gemini-2.5-flash-native-audio-preview-12-2025"
    )
    assert selection.voice == "Puck"
    assert selection.temperature == 0.5


def test_realtime_environment_overrides_are_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_REALTIME_MODEL", "gemini-test-model")
    monkeypatch.setenv("NOVA_VOICE", "TestVoice")
    monkeypatch.setenv("NOVA_TEMPERATURE", "0.25")

    selection = realtime.load_realtime_selection()

    assert selection.model == "gemini-test-model"
    assert selection.voice == "TestVoice"
    assert selection.temperature == 0.25


def test_unsupported_text_provider_cannot_masquerade_as_native_realtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_REALTIME_PROVIDER", "groq")

    with pytest.raises(realtime.RealtimeProviderUnsupportedError):
        realtime.load_realtime_selection()


def test_unknown_realtime_provider_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVA_REALTIME_PROVIDER", "made-up-provider")

    with pytest.raises(realtime.RealtimeProviderUnsupportedError):
        realtime.load_realtime_selection()


def test_missing_gemini_key_fails_without_exposing_a_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(
        realtime.RealtimeProviderNotConfiguredError
    ) as captured:
        realtime.build_realtime_model()

    text = str(captured.value)
    assert "GOOGLE_API_KEY" in text
    assert "unit-test-placeholder-secret" not in text


def test_factory_builds_native_model_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeRealtimeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        realtime.google.realtime,
        "RealtimeModel",
        FakeRealtimeModel,
    )

    model, selection = realtime.build_realtime_model()

    assert isinstance(model, FakeRealtimeModel)
    assert selection.provider is ProviderName.GEMINI
    assert captured["model"] == selection.model
    assert captured["voice"] == selection.voice
    assert captured["temperature"] == selection.temperature
    assert "input_audio_transcription" in captured
    assert "output_audio_transcription" in captured
    assert "realtime_input_config" in captured


def test_selection_summary_never_contains_api_key_material() -> None:
    summary = realtime.load_realtime_selection().safe_summary()
    serialized = repr(summary)

    assert "unit-test-placeholder-secret" not in serialized
    assert "GOOGLE_API_KEY" not in serialized
    assert summary["provider"] == "gemini"


def test_agent_uses_realtime_factory_instead_of_direct_provider_constructor() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    assert "build_realtime_model()" in agent
    assert "llm=realtime_model" in agent
    assert "google.realtime.RealtimeModel(" not in agent
    assert "from google.genai import types" not in agent


def test_learning_metadata_tracks_selected_realtime_provider() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")

    assert "route=realtime_selection.route" in agent
    assert "model=realtime_selection.model" in agent


def test_p0_keeps_livekit_video_transport_enabled() -> None:
    agent = (ROOT / "agent.py").read_text(encoding="utf-8-sig")
    realtime_source = (
        ROOT / "nova_core" / "realtime.py"
    ).read_text(encoding="utf-8-sig")

    assert "video_input=True" in agent
    assert (
        "TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO"
        in realtime_source
    )
    assert "START_OF_ACTIVITY_INTERRUPTS" in realtime_source
