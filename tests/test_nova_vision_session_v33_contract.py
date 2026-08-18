from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_start_nova_uses_real_connect_session() -> None:
    js = read("vision-client/src/main.js")
    assert "await connectSession();" in js
    assert "await connect();" not in js
    assert "const _novaOriginalConnectV32 = connect;" not in js


def test_vision_status_handler_is_installed_on_connected_room() -> None:
    js = read("vision-client/src/main.js")
    assert "state.room = room;" in js
    assert "state.connected = true;" in js
    assert "installVisionStatusHandler(room);" in js


def test_camera_does_not_implicitly_start_audio() -> None:
    js = read("vision-client/src/main.js")
    assert "speakerEnabled: false," in js
    connect_block = js.split("async function connectSession()", 1)[1].split(
        "async function stopAndUnpublish", 1
    )[0]
    assert "room.startAudio()" not in connect_block
    assert "window.addEventListener('pointerdown'" not in js


def test_sound_button_is_explicit_audio_gate() -> None:
    js = read("vision-client/src/main.js")
    speaker_block = js.split(
        "el.speakerButton.addEventListener('click', async () => {", 1
    )[1].split("el.pinButton.addEventListener", 1)[0]
    assert "state.room.startAudio()" in speaker_block
    assert "state.speakerEnabled = !state.speakerEnabled;" in speaker_block


def test_camera_and_microphone_remain_separate_controls() -> None:
    js = read("vision-client/src/main.js")
    camera_block = js.split("async function toggleCameraInput()", 1)[1].split(
        "async function toggleMicrophoneInput()", 1
    )[0]
    assert "setCamera(next)" in camera_block
    assert "setMicrophone" not in camera_block
