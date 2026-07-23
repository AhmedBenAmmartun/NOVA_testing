"""Extract real Windows app icons as PNG data URIs (best effort).

Given a shortcut (.lnk) or executable path, ask the Windows Shell for the icon
it actually shows (this resolves .lnk targets, UWP/Store apps, and custom
icons uniformly), then convert the HICON to a 32-bit PNG with alpha. Results
are cached in memory by source path.

Everything fails soft: any error returns None, and the dashboard falls back to
its gradient placeholder tiles. Windows-only (ctypes + PIL).
"""
from __future__ import annotations

import base64
import ctypes
import json
from ctypes import wintypes
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except Exception:  # pragma: no cover - PIL should be present in the venv
    Image = None

_shell32 = ctypes.windll.shell32
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_ole32 = ctypes.windll.ole32

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
_COINIT_APARTMENTTHREADED = 0x2
_RPC_E_CHANGED_MODE = -2147417850  # 0x80010106

# Only successful extractions are cached (failures retry on the next scan).
_cache: dict[str, str] = {}
_CACHE_FILE = Path(__file__).resolve().parent / "runtime" / "icon_cache.json"


def _load_cache() -> None:
    try:
        if _CACHE_FILE.is_file():
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _cache.update({k: v for k, v in data.items() if isinstance(v, str)})
    except Exception:
        pass


def save_cache() -> None:
    """Persist captured icons so coverage survives restarts."""
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(_cache, ensure_ascii=True), encoding="utf-8"
        )
    except Exception:
        pass


_load_cache()


class _SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


# Declare argument/return types so 64-bit handles are passed as pointers, not
# truncated to C int (which raises OverflowError for handles above 2**31).
_shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.POINTER(_SHFILEINFO), wintypes.UINT, wintypes.UINT,
]
_shell32.SHGetFileInfoW.restype = ctypes.c_void_p
_user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
_user32.GetIconInfo.restype = wintypes.BOOL
_user32.DestroyIcon.argtypes = [wintypes.HICON]
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetObjectW.restype = ctypes.c_int
_gdi32.GetDIBits.argtypes = [
    wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
]
_gdi32.GetDIBits.restype = ctypes.c_int
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long


def _hicon_to_png(hicon: int, out_size: int) -> str | None:
    """Convert an HICON to a base64 PNG data URI, preserving alpha."""
    info = _ICONINFO()
    if not _user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    try:
        bitmap = _BITMAP()
        _gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bitmap), ctypes.byref(bitmap))
        width, height = bitmap.bmWidth, bitmap.bmHeight
        if width <= 0 or height <= 0:
            return None

        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # negative => top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB

        buffer = (ctypes.c_char * (width * height * 4))()
        screen_dc = _user32.GetDC(0)
        scanlines = _gdi32.GetDIBits(
            screen_dc, info.hbmColor, 0, height, buffer, ctypes.byref(header), 0
        )
        _user32.ReleaseDC(0, screen_dc)
        if not scanlines:
            return None

        image = Image.frombuffer(
            "RGBA", (width, height), bytes(buffer), "raw", "BGRA", 0, 1
        )
        # Older icons carry no alpha channel (all zero) -> render them opaque.
        if image.getchannel("A").getextrema() == (0, 0):
            image.putalpha(255)
        if (width, height) != (out_size, out_size):
            image = image.resize((out_size, out_size), Image.LANCZOS)

        out = BytesIO()
        image.save(out, format="PNG")
        return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    finally:
        if info.hbmColor:
            _gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            _gdi32.DeleteObject(info.hbmMask)


def icon_data_uri(source: str, out_size: int = 32) -> str | None:
    """Return a PNG data URI for the Shell icon of `source`, or None.

    COM is initialized for the call because SHGetFileInfo needs it to resolve
    shortcut (.lnk) and UWP icons reliably from a worker thread.
    """
    if Image is None or not source:
        return None
    cached = _cache.get(source)
    if cached:
        return cached

    # Initialize COM on this thread; balance CoUninitialize only when we own it.
    hresult = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    own_com = hresult != _RPC_E_CHANGED_MODE

    result: str | None = None
    try:
        info = _SHFILEINFO()
        found = _shell32.SHGetFileInfoW(
            ctypes.c_wchar_p(source),
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
            SHGFI_ICON | SHGFI_LARGEICON,
        )
        if found and info.hIcon:
            try:
                result = _hicon_to_png(info.hIcon, out_size)
            finally:
                _user32.DestroyIcon(info.hIcon)
    except Exception:
        result = None
    finally:
        if own_com:
            _ole32.CoUninitialize()

    if result:  # never cache failures, so they retry next scan
        _cache[source] = result
    return result
