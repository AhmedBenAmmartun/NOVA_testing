"""NOVA must not be able to execute code by "opening" a file.

`open_file_or_folder` calls `os.startfile(path)` (tools/files.py), which invokes
the Windows shell's default verb. For a document that means *view*. For `.exe`,
`.bat`, `.cmd`, `.vbs`, `.js`, `.hta`, `.msi`, `.lnk`, `.scr` and friends it
means *execute*.

Combined with the write tools, that composed into unconfirmed code execution:

    web_download(...)            -> ~/Downloads/NOVA Downloads/payload.exe
      registered REVERSIBLE, so the permission engine runs it with no prompt
    open_file_or_folder(...)     -> os.startfile -> the payload runs

`~/Downloads` is in SAFE_DIRS and both `files` and `web` are default_active, so
nothing in the chain required a confirmation. The network is not even necessary:
`create_file("~/Desktop/x.bat", ...)` then opening it does the same thing.

This entirely bypassed the declared `arbitrary_shell_command: RESTRICTED`
policy, because the real execution primitive was never the shell tool -- it was
`os.startfile`.

The fix is an extension ALLOWLIST at the launch point. A denylist loses to the
next extension Windows decides to make executable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tools.files import LAUNCHABLE_SUFFIXES, is_launchable, open_file_or_folder


def _call(tool, *args, **kwargs):
    """Invoke a livekit @function_tool, supplying the unused RunContext."""
    target = getattr(tool, "_func", None) or tool
    result = target(None, *args, **kwargs)
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result


# --- the allowlist itself ----------------------------------------------------


@pytest.mark.parametrize(
    "suffix",
    [
        ".exe", ".bat", ".cmd", ".com", ".scr", ".pif",
        ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
        ".hta", ".msi", ".msp", ".lnk", ".reg", ".cpl",
        ".ps1", ".psm1", ".jar", ".application",
    ],
)
def test_executable_extensions_are_never_launchable(suffix: str) -> None:
    assert not is_launchable(Path(f"payload{suffix}"))
    assert suffix not in LAUNCHABLE_SUFFIXES


@pytest.mark.parametrize(
    "suffix",
    [".pdf", ".txt", ".md", ".docx", ".xlsx", ".pptx", ".png", ".jpg", ".mp4", ".csv"],
)
def test_ordinary_documents_stay_launchable(suffix: str) -> None:
    """The guard must not break the actual feature Ahmed uses."""
    assert is_launchable(Path(f"lecture{suffix}"))


def test_the_allowlist_is_case_insensitive() -> None:
    """Windows does not care about case, so neither may the check."""
    assert not is_launchable(Path("PAYLOAD.EXE"))
    assert not is_launchable(Path("Payload.BaT"))
    assert is_launchable(Path("Notes.PDF"))


def test_a_double_extension_is_judged_by_its_real_suffix() -> None:
    """"invoice.pdf.exe" is an executable wearing a costume."""
    assert not is_launchable(Path("invoice.pdf.exe"))


def test_an_unknown_extension_is_refused_by_default() -> None:
    """Allowlist semantics: anything unrecognized does not launch."""
    assert not is_launchable(Path("thing.weirdext"))


def test_a_file_with_no_extension_is_refused() -> None:
    assert not is_launchable(Path("payload"))


# --- the tool honors it ------------------------------------------------------


def test_opening_an_executable_in_a_safe_dir_is_refused(tmp_path, monkeypatch) -> None:
    """The payload sits in an allowed directory. It must still not launch."""
    import tools.common as common
    import tools.files as files

    payload = tmp_path / "payload.bat"
    payload.write_text("@echo pwned\n", encoding="utf-8")
    monkeypatch.setattr(common, "SAFE_DIRS", [tmp_path])
    monkeypatch.setattr(files, "SAFE_DIRS", [tmp_path], raising=False)

    launched: list = []
    monkeypatch.setattr(files.os, "startfile", lambda p: launched.append(p))

    result = _call(open_file_or_folder, str(payload))

    assert not launched, "os.startfile was reached with an executable"
    assert "exe" in result.lower() or "cannot" in result.lower() or "not" in result.lower()


def test_opening_a_document_still_works(tmp_path, monkeypatch) -> None:
    import tools.common as common
    import tools.files as files

    doc = tmp_path / "lecture.txt"
    doc.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(common, "SAFE_DIRS", [tmp_path])
    monkeypatch.setattr(files, "SAFE_DIRS", [tmp_path], raising=False)

    launched: list = []
    monkeypatch.setattr(files.os, "startfile", lambda p: launched.append(p))

    _call(open_file_or_folder, str(doc))

    assert launched == [doc]


def test_opening_a_folder_still_works(tmp_path, monkeypatch) -> None:
    """Directories have no suffix and must remain openable."""
    import tools.common as common
    import tools.files as files

    folder = tmp_path / "Slides"
    folder.mkdir()
    monkeypatch.setattr(common, "SAFE_DIRS", [tmp_path])
    monkeypatch.setattr(files, "SAFE_DIRS", [tmp_path], raising=False)

    launched: list = []
    monkeypatch.setattr(files.os, "startfile", lambda p: launched.append(p))

    _call(open_file_or_folder, str(folder))

    assert launched == [folder]


# --- the write side of the chain --------------------------------------------


def test_a_desktop_file_cannot_be_given_an_executable_extension() -> None:
    """`create_desktop_file("x.bat")` must not produce a runnable file.

    _safe_desktop_child only appended `.txt` when the suffix was EMPTY, so an
    explicit `.bat` passed straight through and wrote an executable.
    """
    from tools.files import _safe_desktop_child

    assert not str(_safe_desktop_child("payload.bat")).endswith(".bat")
    assert not str(_safe_desktop_child("payload.exe")).endswith(".exe")
    assert str(_safe_desktop_child("notes")).endswith(".txt")
    assert str(_safe_desktop_child("notes.md")).endswith(".md")
