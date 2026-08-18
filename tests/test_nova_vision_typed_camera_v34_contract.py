from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_gemini_turn_includes_all_live_video() -> None:
    agent = read("agent.py")
    assert (
        "types.TurnCoverage."
        "TURN_INCLUDES_AUDIO_ACTIVITY_AND_ALL_VIDEO"
        in agent
    )


def test_live_video_remains_enabled() -> None:
    agent = read("agent.py")
    assert "video_input=True" in agent


def test_temporary_frame_diagnostic_removed() -> None:
    agent = read("agent.py")
    assert "_vision_diagnostic_sampler" not in agent
    assert "NOVA VISION FRAME DIAGNOSTIC V1" not in agent


def test_start_nova_uses_connect_session() -> None:
    js = read("vision-client/src/main.js")
    assert "await connectSession();" in js
    assert "await connect();" not in js
    assert "const _novaOriginalConnectV32 = connect;" not in js


def test_camera_and_mic_stay_independent() -> None:
    js = read("vision-client/src/main.js")
    camera = js.split("async function toggleCameraInput()", 1)[1].split(
        "async function toggleMicrophoneInput()", 1
    )[0]
    assert "setCamera(next)" in camera
    assert "setMicrophone" not in camera


def test_sound_defaults_off_and_is_explicit() -> None:
    js = read("vision-client/src/main.js")
    assert "speakerEnabled: false," in js

    connect_block = js.split("async function connectSession()", 1)[1].split(
        "async function stopAndUnpublish", 1
    )[0]
    assert "room.startAudio()" not in connect_block

    sound = js.split(
        "el.speakerButton.addEventListener('click', async () => {", 1
    )[1].split("el.pinButton.addEventListener", 1)[0]
    assert "state.room.startAudio()" in sound


def test_vision_status_handler_attaches_to_real_room() -> None:
    js = read("vision-client/src/main.js")
    assert "installVisionStatusHandler(room);" in js
