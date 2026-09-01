"""Agent driver for the NOVA LiveKit voice agent.

Runs the agent's brain (system prompt + tools + Gemini) without needing a
microphone, speakers, or a LiveKit room, plus launch checks for the real
console/dev modes.

Usage (from the project root, with the project venv):
    venv\\Scripts\\python.exe .development assistant\\skills\\run-ai-agent\\driver.py tools
    venv\\Scripts\\python.exe .development assistant\\skills\\run-ai-agent\\driver.py chat "What time is it?"
    venv\\Scripts\\python.exe .development assistant\\skills\\run-ai-agent\\driver.py console-check
    venv\\Scripts\\python.exe .development assistant\\skills\\run-ai-agent\\driver.py dev-check

Subcommands:
    tools          Call the local function tools directly (no API keys needed).
    chat MSG       One full agent turn: Assistant + all its tools on the text
                   Gemini model via AgentSession.run. Prints tool calls and the
                   reply. Needs GOOGLE_API_KEY in .env.
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
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

sys.path.insert(0, str(PROJECT_ROOT))
import os

os.chdir(PROJECT_ROOT)  # agent.py loads .env relative to CWD

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")  # tools read keys (e.g. Spotify) from env


def _write_sample_pdf(path: Path, text: str) -> None:
    """Write a tiny text PDF for the course-material smoke test."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    stream = f"BT /F1 14 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> "
            b"/Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
    ]
    parts = [b"%PDF-1.4\n"]
    offsets = [0]

    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f"{index} 0 obj\n".encode("ascii"))
        parts.append(obj)
        parts.append(b"\nendobj\n")

    xref_offset = sum(len(part) for part in parts)
    parts.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    parts.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        parts.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    parts.append(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(b"".join(parts))


def check_tools() -> int:
    """Directly invoke local tools plus the security guards (no LLM needed)."""
    from tools import common as common_mod
    from tools import conversations as conversations_mod
    from tools import files as files_mod
    from tools import (
        ask_specialist,
        control_music,
        control_window,
        create_desktop_file,
        create_desktop_folder,
        find_user_file,
        get_current_song,
        get_system_info,
        get_time,
        is_app_running,
        list_files,
        manage_virtual_desktop,
        open_app,
        open_file_or_folder,
        play_spotify_song,
        read_course_material,
        read_conversation_history,
        read_file,
        read_memory_note,
        read_notes,
        save_memory_note,
        save_note,
        search_conversation_history,
        search_memory,
    )
    from livekit.agents import RunContext

    # The checks below call the tools directly, outside a live session. None of
    # the tools read their RunContext, so a typed None stands in for it.
    no_ctx = cast(RunContext, None)

    async def run() -> int:
        failures = 0
        # notes.txt is project-absolute now; point it at a temp file so the
        # user's real notes are untouched. save_note reads the copy bound in
        # tools.files, so that's the module to patch.
        with tempfile.TemporaryDirectory() as tmp:
            files_mod.NOTES_PATH = Path(tmp) / "notes.txt"
            # Isolated Obsidian vault so the checks never touch the real one.
            # The obsidian tools re-read OBSIDIAN_VAULT_PATH on every call.
            vault = Path(tmp) / "vault"
            (vault / "Classes").mkdir(parents=True)
            (vault / "Classes" / "physics.md").write_text(
                "Newton's laws of motion", encoding="utf-8"
            )
            large_chat = vault / "Conversations" / "ChatGPT" / "chats" / "large-chat.md"
            large_chat.parent.mkdir(parents=True)
            large_chat.write_text(
                "# Large Chat Export\n\n"
                + ("ordinary exported conversation text\n" * 4500)
                + "Hidden large chat marker: NOVA can find this late in a long note.\n",
                encoding="utf-8",
            )
            course_root = Path(tmp) / "course_materials"
            course_root.mkdir()
            (course_root / "biology.txt").write_text(
                "Cell theory says cells are the basic unit of life.",
                encoding="utf-8",
            )
            _write_sample_pdf(
                course_root / "photosynthesis.pdf",
                "Photosynthesis converts light into chemical energy.",
            )
            real_vault = os.environ.get("OBSIDIAN_VAULT_PATH")
            real_course_root = common_mod.COURSE_MATERIALS_PATH
            real_conversation_root = common_mod.CONVERSATION_LOGS_PATH
            real_conversations_module_root = conversations_mod.CONVERSATION_LOGS_PATH
            real_desktop_root = files_mod.DEFAULT_DESKTOP_PATH
            real_file_safe_dirs = files_mod.SAFE_DIRS
            os.environ["OBSIDIAN_VAULT_PATH"] = str(vault)
            common_mod.COURSE_MATERIALS_PATH = course_root
            conversation_root = Path(tmp) / "conversation_logs"
            common_mod.CONVERSATION_LOGS_PATH = conversation_root
            conversations_mod.CONVERSATION_LOGS_PATH = conversation_root
            desktop_root = Path(tmp) / "Desktop"
            desktop_root.mkdir()
            (desktop_root / "schedule.pdf").write_text("fake schedule", encoding="utf-8")
            files_mod.DEFAULT_DESKTOP_PATH = desktop_root
            files_mod.SAFE_DIRS = [desktop_root, PROJECT_ROOT]

            class FakeChatItem:
                def __init__(self, role: str, text: str) -> None:
                    self.role = role
                    self.text_content = text

            # The recorder is privacy-gated off by default on this branch
            # (NOVA_SAVE_TRANSCRIPTS / NOVA_MIRROR_TRANSCRIPTS_TO_OBSIDIAN both
            # default to false), so a bare recorder writes nothing. Enable both
            # explicitly so the checks below exercise the real persist + mirror
            # path instead of depending on ambient env; the writes land in the
            # temp conversation root and temp vault patched above.
            recorder = conversations_mod.SessionConversationRecorder(
                enabled=True,
                mirror_to_obsidian=True,
            )
            recorder.record_item(FakeChatItem("assistant", "Hello Ahmed. NOVA is ready."))
            recorder.record_item(FakeChatItem("user", "Help me remember our biology quiz plan."))
            recorder.record_item(FakeChatItem("assistant", "We planned a biology quiz mode."))
            recorder.finish()

            checks = [
                ("get_time", get_time(no_ctx), lambda r: "Today is" in r),
                ("get_system_info", get_system_info(no_ctx), lambda r: "CPU usage" in r),
                ("save_note", save_note(no_ctx, "driver smoke test"), lambda r: r == "Note saved."),
                ("read_notes", read_notes(no_ctx), lambda r: "driver smoke test" in r),
                ("list_files", list_files(no_ctx, str(PROJECT_ROOT)), lambda r: "agent.py" in r),
                ("find_user_file finds temp file", find_user_file(no_ctx, "schedule", "all"), lambda r: "schedule.pdf" in r),
                ("find_user_file desktop alias", find_user_file(no_ctx, "schedule", "desktop"), lambda r: "schedule.pdf" in r),
                ("create_desktop_file", create_desktop_file(no_ctx, "nova-test-note", "hello"), lambda r: "Created Desktop file" in r),
                ("create_desktop_file no overwrite", create_desktop_file(no_ctx, "nova-test-note", "hello again"), lambda r: "already exists" in r),
                ("create_desktop_folder", create_desktop_folder(no_ctx, "NOVA Test Folder"), lambda r: "Created Desktop folder" in r),
                ("search_conversation_history", search_conversation_history(no_ctx, "biology"), lambda r: "biology quiz plan" in r),
                ("read_conversation_history latest", read_conversation_history(no_ctx, "latest"), lambda r: "biology quiz mode" in r),
                ("conversation mirrored to vault", search_memory(no_ctx, "biology quiz mode"), lambda r: "NOVA/Conversations" in r),
                ("save_memory_note writes vault", save_memory_note(no_ctx, "Driver memory", "Ahmed prefers isolated safe memory tests.", "NOVA/Driver"), lambda r: "NOVA/Driver" in r),
                ("search_memory finds saved memory", search_memory(no_ctx, "isolated safe memory tests"), lambda r: "NOVA/Driver" in r),
                ("save_memory_note rejects secrets", save_memory_note(no_ctx, "Secret", "my API key is sk-test", "NOVA"), lambda r: "will not save passwords" in r),
                ("read_course_material text", read_course_material(no_ctx, "biology.txt"), lambda r: "Cell theory" in r),
                ("read_course_material pdf", read_course_material(no_ctx, "photosynthesis.pdf", 1, 1), lambda r: "Photosynthesis converts light" in r),
                ("course sandbox blocks escape", read_course_material(no_ctx, "../README.md"), lambda r: "course_materials folder" in r),
                # security guards - these must all REFUSE
                ("sandbox blocks system paths", read_file(no_ctx, r"C:\Windows\win.ini"), lambda r: "Access denied" in r),
                ("sandbox blocks .env", read_file(no_ctx, str(PROJECT_ROOT / ".env")), lambda r: "Access denied" in r),
                ("open_file_or_folder blocks system paths", open_file_or_folder(no_ctx, r"C:\Windows\win.ini"), lambda r: "Access denied" in r),
                ("open_app blocks non-whitelist", open_app(no_ctx, "evil.exe & del *"), lambda r: "not in the approved application list" in r),
                ("control_music rejects bad action", control_music(no_ctx, "explode"), lambda r: "Unknown music action" in r),
                ("control_window rejects bad action", control_window(no_ctx, "current", "teleport"), lambda r: "Unknown window action" in r),
                ("manage_virtual_desktop rejects bad action", manage_virtual_desktop(no_ctx, "explode"), lambda r: "Unknown virtual desktop action" in r),
                ("ask_specialist rejects empty task", ask_specialist(no_ctx, "   "), lambda r: "specialist request was empty" in r),
                # graceful no-setup paths
                ("is_app_running", is_app_running(no_ctx, "spotify"), lambda r: "running" in r),
                ("get_current_song", get_current_song(no_ctx), lambda r: "Spotify" in r or "playing" in r),
                # obsidian memory (isolated temp vault set up above)
                ("search_memory finds note", search_memory(no_ctx, "newton"), lambda r: "physics.md" in r),
                ("read_memory_note reads note", read_memory_note(no_ctx, "Classes/physics"), lambda r: "Newton" in r),
                ("search_memory finds large note", search_memory(no_ctx, "Hidden large chat marker"), lambda r: "large-chat.md" in r),
                ("read_memory_note large query excerpt", read_memory_note(no_ctx, "Conversations/ChatGPT/chats/large-chat.md", "Hidden large chat marker"), lambda r: "NOVA can find this late" in r),
                ("read_memory_note blocks escape", read_memory_note(no_ctx, "../outside"), lambda r: "outside the Obsidian vault" in r),
            ]
            if not os.getenv("SPOTIFY_CLIENT_ID"):
                checks.append(
                    ("play_spotify_song unconfigured", play_spotify_song(no_ctx, "test"), lambda r: "not configured" in r)
                )
            total = len(checks)
            try:
                for name, coro, ok in checks:
                    result = await coro
                    status = "OK  " if ok(result) else "FAIL"
                    if status == "FAIL":
                        failures += 1
                    first_line = result.splitlines()[0] if result else "(empty)"
                    print(f"[{status}] {name}: {first_line}")
            finally:
                if real_vault is None:
                    os.environ.pop("OBSIDIAN_VAULT_PATH", None)
                else:
                    os.environ["OBSIDIAN_VAULT_PATH"] = real_vault
                common_mod.COURSE_MATERIALS_PATH = real_course_root
                common_mod.CONVERSATION_LOGS_PATH = real_conversation_root
                conversations_mod.CONVERSATION_LOGS_PATH = real_conversations_module_root
                files_mod.DEFAULT_DESKTOP_PATH = real_desktop_root
                files_mod.SAFE_DIRS = real_file_safe_dirs
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
                # Events carry heterogeneous item types (function calls,
                # outputs, messages); duck-type them rather than narrowing.
                item: Any = getattr(ev, "item", None)
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
