"""Agent driver for the NOVA LiveKit voice agent.

Runs the agent's brain (system prompt + tools + Gemini) without needing a
microphone, speakers, or a LiveKit room, plus launch checks for the real
console/dev modes.

Usage (from the project root, with the project venv):
    venv\\Scripts\\python.exe .claude\\skills\\run-ai-agent\\driver.py tools
    venv\\Scripts\\python.exe .claude\\skills\\run-ai-agent\\driver.py chat "What time is it?"
    venv\\Scripts\\python.exe .claude\\skills\\run-ai-agent\\driver.py console-check
    venv\\Scripts\\python.exe .claude\\skills\\run-ai-agent\\driver.py dev-check

Subcommands:
    tools          Call the local function tools directly (no API keys needed).
    chat MSG       One full agent turn: Assistant + its 12 tools on the text
                   Gemini model via AgentSession.run. Prints tool calls and the
                   reply. Needs Google_API_Key in .env.
    console-check  Launch `agent.py console` (real voice pipeline, local audio),
                   wait for the session to come up, then kill it. Audio may
                   briefly play on the speakers.
    dev-check      Launch `agent.py dev`, wait until the worker registers with
                   LiveKit Cloud, then kill it. Needs LIVEKIT_* in .env.
"""

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

sys.path.insert(0, str(PROJECT_ROOT))
import os

os.chdir(PROJECT_ROOT)  # agent.py loads .env relative to CWD

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")  # tools read keys (e.g. Spotify) from env


def check_tools() -> int:
    """Directly invoke local tools plus the security guards (no LLM needed)."""
    import tools as tools_mod
    from tools import (
        control_music,
        get_current_song,
        get_system_info,
        get_time,
        is_app_running,
        list_files,
        open_app,
        play_spotify_song,
        read_file,
        read_notes,
        save_note,
    )

    async def run() -> int:
        failures = 0
        # notes.txt is project-absolute now; point it at a temp file so the
        # user's real notes are untouched.
        with tempfile.TemporaryDirectory() as tmp:
            tools_mod.NOTES_PATH = Path(tmp) / "notes.txt"
            checks = [
                ("get_time", get_time(None), lambda r: "Today is" in r),
                ("get_system_info", get_system_info(None), lambda r: "CPU usage" in r),
                ("save_note", save_note(None, "driver smoke test"), lambda r: r == "Note saved."),
                ("read_notes", read_notes(None), lambda r: "driver smoke test" in r),
                ("list_files", list_files(None, str(PROJECT_ROOT)), lambda r: "agent.py" in r),
                # security guards - these must all REFUSE
                ("sandbox blocks system paths", read_file(None, r"C:\Windows\win.ini"), lambda r: "Access denied" in r),
                ("sandbox blocks .env", read_file(None, str(PROJECT_ROOT / ".env")), lambda r: "Access denied" in r),
                ("open_app blocks non-whitelist", open_app(None, "evil.exe & del *"), lambda r: "not in the approved app list" in r),
                ("control_music rejects bad action", control_music(None, "explode"), lambda r: "Unknown action" in r),
                # graceful no-setup paths
                ("is_app_running", is_app_running(None, "spotify"), lambda r: "running" in r),
                ("get_current_song", get_current_song(None), lambda r: "Spotify" in r or "playing" in r),
            ]
            if not os.getenv("SPOTIFY_CLIENT_ID"):
                checks.append(
                    ("play_spotify_song unconfigured", play_spotify_song(None, "test"), lambda r: "not set up" in r)
                )
            total = len(checks)
            for name, coro, ok in checks:
                result = await coro
                status = "OK  " if ok(result) else "FAIL"
                if status == "FAIL":
                    failures += 1
                first_line = result.splitlines()[0] if result else "(empty)"
                print(f"[{status}] {name}: {first_line}")
        print(f"\n{'PASS' if failures == 0 else 'FAIL'}: {total - failures}/{total} checks OK")
        return failures

    return 1 if asyncio.run(run()) else 0


def chat(message: str) -> int:
    """One full agent turn through the real Assistant (text Gemini model)."""
    from livekit.agents import AgentSession
    from livekit.plugins import google

    from agent import Assistant  # noqa: E402 - also loads .env

    async def run() -> int:
        # The rtc app uses google.beta.realtime.RealtimeModel (audio); for a
        # text turn we mount the same Assistant (same prompt, same tools) on
        # the text Gemini model.
        # Must be an explicit "gemini-3*" name: the plugin's thought_signature
        # handling is keyed on the model string, so "gemini-flash-latest" 400s
        # on multi-turn tool calls; 2.5-flash is retired (404) and 2.0-flash
        # has zero free-tier quota (429 limit:0).
        async with google.LLM(model="gemini-3.5-flash") as llm, AgentSession(llm=llm) as session:
            await session.start(Assistant())
            result = await session.run(user_input=message)

            reply_parts: list[str] = []
            for ev in result.events:
                item = getattr(ev, "item", None)
                itype = getattr(item, "type", type(ev).__name__)
                if itype == "function_call":
                    print(f"[tool call]   {item.name}({item.arguments})")
                elif itype == "function_call_output":
                    out = (item.output or "").splitlines()[0]
                    print(f"[tool output] {out}")
                elif itype == "message" and getattr(item, "role", "") == "assistant":
                    reply_parts.append(item.text_content or "")
            reply = "\n".join(p for p in reply_parts if p)
            print(f"\nNOVA: {reply}")
            return 0 if reply else 1

    return asyncio.run(run())


def _launch_and_wait(mode: str, ready_markers: list[str], timeout: float) -> int:
    """Launch `agent.py <mode>` detached, poll its log for a ready marker, kill it."""
    import psutil

    log_path = Path(tempfile.gettempdir()) / f"nova_agent_{mode}_check.log"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(VENV_PYTHON), "agent.py", mode],
            cwd=PROJECT_ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
        )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = log_path.read_text(encoding="utf-8", errors="replace")
            if any(m in text for m in ready_markers):
                print(f"[OK] `agent.py {mode}` is up (marker found). Killing it.")
                return 0
            if proc.poll() is not None:
                print(f"[FAIL] `agent.py {mode}` exited early (code {proc.returncode}). Log tail:")
                print("\n".join(text.splitlines()[-15:]))
                return 1
            time.sleep(1)
        print(f"[FAIL] no ready marker within {timeout}s. Log tail:")
        print("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]))
        return 1
    finally:
        if proc.poll() is None:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "tools":
        return check_tools()
    if cmd == "chat":
        if len(sys.argv) < 3:
            print('usage: driver.py chat "message"')
            return 2
        return chat(sys.argv[2])
    if cmd == "console-check":
        # The interactive banner isn't written when stdout is redirected; the
        # first conversation_item_added debug line is the greeting - it proves
        # session start + Gemini Live connection + a generated reply. Killing
        # there keeps the audible window short.
        return _launch_and_wait("console", ["conversation_item_added"], timeout=60)
    if cmd == "dev-check":
        return _launch_and_wait("dev", ["registered worker"], timeout=45)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
