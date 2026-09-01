"""Static regression contract for NOVA Vision Phase 1.

These checks require only the standard library and validate the privacy/security
shape without opening a camera, microphone, network connection, or paid model.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def active_python_sources() -> list[pathlib.Path]:
    # ".claude" holds git worktrees of *other* branches checked out inside the
    # project (Claude Code creates them under .claude/worktrees/). A sibling
    # checkout of an older commit is not active NOVA source, and scanning it
    # made this contract fail on retired code that the live tree no longer has.
    blocked = {
        "tests",
        "venv",
        ".venv",
        "Dashboard",
        ".nova-backups",
        "NOVA-Agent-pending",
        ".claude",
    }
    paths: list[pathlib.Path] = []
    for path in ROOT.rglob("*.py"):
        if any(part in blocked for part in path.parts):
            continue
        paths.append(path)
    return paths


def test_agent_live_video_enabled() -> None:
    agent = text("agent.py")
    assert "video_input=True" in agent
    assert "video_input=False" not in agent
    assert agent.count("permission_engine.clear_session(bridge_session_id)") == 1
    assert agent.count('permission_engine.clear_session("voice")') == 1


def test_no_active_screenshot_capture_backend() -> None:
    bad: list[str] = []
    for path in active_python_sources():
        source = path.read_text(encoding="utf-8-sig")
        if "ImageGrab" in source or "ImageGrab.grab" in source:
            bad.append(str(path.relative_to(ROOT)))
    assert bad == []


def test_old_guardian_vision_not_public() -> None:
    init = text("tools/__init__.py")
    for name in ("look_at_screen_locally", "start_guardian_vision", "stop_guardian_vision"):
        assert name not in init
    guardian = text("tools/guardian.py")
    for name in ("look_at_screen_locally", "start_guardian_vision", "stop_guardian_vision"):
        match = re.search(rf"(?:@function_tool\(\)\s*)?async def {name}\b", guardian)
        assert match is not None
        assert not guardian[max(0, match.start()-30):match.start()].strip().endswith("@function_tool()")


def test_only_unified_specialist_is_public() -> None:
    init = text("tools/__init__.py")
    assert "ask_specialist" in init
    for legacy in ("ask_gpt56", "ask_groq", "ask_ollama"):
        assert legacy not in init


def test_token_helper_is_short_lived_and_source_restricted() -> None:
    helper = text("vision_token.py")
    assert 'TOKEN_TTL = dt.timedelta(minutes=15)' in helper
    assert 'can_publish_sources=["camera", "microphone"]' in helper
    assert 'can_publish_data=True' in helper
    assert 'RoomAgentDispatch(' in helper
    assert 'agent_name=AGENT_NAME' in helper
    assert 'AGENT_NAME = "my-agent"' in helper
    assert not re.search(r'(?m)^\s*LIVEKIT_API_SECRET\s*=', helper)
    assert not re.search(r'(?m)^\s*LIVEKIT_API_KEY\s*=', helper)


def test_client_defaults_media_off_and_preview_is_published_track() -> None:
    client = text("vision-client/src/main.js")
    assert "cameraEnabled: false" in client
    assert "micEnabled: false" in client
    assert "getTrackPublication(Track.Source.Camera)" in client
    assert "track.attach(el.cameraPreview)" in client
    assert "setCameraEnabled(true)" in client
    assert "setMicrophoneEnabled(true)" in client
    assert "unpublishTrack(track, true)" in client
    assert "stopAndUnpublish(Track.Source.Camera" in client
    assert "stopAndUnpublish(Track.Source.Microphone" in client
    css = text("vision-client/src/styles.css")
    # Local selfie-style mirroring is allowed, but it must stay CSS-only on
    # #cameraPreview so the LiveKit publication itself remains unmodified.
    mirror_count = css.count("scaleX(-1)")
    assert mirror_count in (0, 1)
    if mirror_count == 1:
        preview_rule = re.search(r"#cameraPreview\s*\{[^}]*\}", css, re.S)
        assert preview_rule is not None
        assert "scaleX(-1)" in preview_rule.group(0)


def test_close_path_releases_media_and_disconnects() -> None:
    client = text("vision-client/src/main.js")
    assert "stopAndUnpublish(Track.Source.Camera" in client
    assert "stopAndUnpublish(Track.Source.Microphone" in client
    assert "unpublishTrack(track, true)" in client
    assert "room.disconnect()" in client
    assert "shutdownAndDestroy" in client


def test_client_has_no_screen_capture_or_recording_api() -> None:
    combined = "\n".join(
        text(path)
        for path in (
            "vision-client/src/main.js",
            "vision-client/index.html",
        )
    ).lower()
    for forbidden in (
        "getdisplaymedia",
        "mediastreamrecorder",
        "mediarecorder(",
        "html2canvas",
        "screenshareenabled",
        "setscreenshareenabled",
    ):
        assert forbidden not in combined


def test_window_permissions_are_minimal() -> None:
    capability = text("vision-client/src-tauri/capabilities/default.json")
    for required in (
        "core:window:allow-set-always-on-top",
        "core:window:allow-minimize",
        "core:window:allow-destroy",
        "core:window:allow-set-size",
        "core:window:allow-start-dragging",
    ):
        assert required in capability
    assert "shell:" not in capability
    assert "fs:" not in capability


def test_tauri_dev_server_and_rust_bridge_contract() -> None:
    package = text("vision-client/package.json")
    config = text("vision-client/src-tauri/tauri.conf.json")
    rust = text("vision-client/src-tauri/src/lib.rs")
    assert "--port 1428 --strictPort" in package
    assert '"devUrl": "http://127.0.0.1:1428"' in config
    assert "Deserialize, Serialize" in rust
    assert "serde_json::from_slice::<VisionConnection>" in rust


def test_launcher_uses_relative_agent_argument() -> None:
    launcher = text("Start-NOVA-Vision.ps1")
    assert '-ArgumentList @("agent.py", "dev")' in launcher
    assert '-ArgumentList @($Agent, "dev")' not in launcher


if __name__ == "__main__":
    checks = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for check in checks:
        check()
    print(f"Phase 1 vision contract: {len(checks)} checks passed.")
