"""Static contract for captions rendered over NOVA Vision.

This test opens no camera/microphone/network connection and writes no transcript.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def test_gemini_transcription_requested() -> None:
    realtime = text("nova_core/realtime.py")
    assert "input_audio_transcription=types.AudioTranscriptionConfig()" in realtime
    assert "output_audio_transcription=types.AudioTranscriptionConfig()" in realtime


def test_captions_are_inside_preview_ui() -> None:
    html = text("vision-client/index.html")
    video = html.index('id="cameraPreview"')
    captions = html.index('id="captionOverlay"')
    card_end = html.index('</section>', captions)
    assert video < captions < card_end
    assert 'id="captionSpeaker"' in html
    assert 'id="captionText"' in html


def test_frontend_uses_livekit_text_streams() -> None:
    client = text("vision-client/src/main.js")
    assert "registerTextStreamHandler('lk.transcription'" in client
    assert "lk.transcribed_track_id" in client
    assert "lk.transcription_final" in client
    assert "participantIdentity === state.localIdentity" in client
    assert "el.captionSpeaker.textContent = isUser ? 'YOU' : 'NOVA'" in client


def test_caption_history_is_not_persisted() -> None:
    client = text("vision-client/src/main.js")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in client


def test_caption_overlay_is_not_mirrored_with_camera() -> None:
    css = text("vision-client/src/styles.css")
    match = re.search(r"\.caption-overlay\s*\{(?P<body>.*?)\}", css, re.S)
    assert match is not None
    assert "scaleX(-1)" not in match.group("body")
    assert "position: absolute" in match.group("body")


if __name__ == "__main__":
    checks = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for check in checks:
        check()
    print(f"NOVA Vision captions contract: {len(checks)} checks passed.")
