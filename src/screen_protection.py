"""Screen-capture exclusion for Qt top-level windows.

**Windows** uses ``SetWindowDisplayAffinity`` (user32) so the OS omits the
window's pixels from captures while it stays visible on the physical monitor.

**macOS** has no exact equivalent: it sets ``NSWindow.sharingType`` to
``NSWindowSharingNone`` through ``macos_window``. Apple deprecated that in
macOS 13 and ScreenCaptureKit-based capturers (macOS 15+) may ignore it, so the
macOS behaviour is **best-effort** — it still hides the window from legacy
``CGWindowListCreateImage`` style capture, including some of the app's own
screenshots, but a modern capturer cannot be forced to skip the window.

Callers never need to branch on the OS: ``set_capture_protection`` returns
False when the platform has no implementation or the native call fails.
"""

import ctypes
import sys

from src.macos_window import set_capture_exclusion as _macos_set_capture_exclusion

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

if _IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _SetWindowDisplayAffinity = _user32.SetWindowDisplayAffinity
    _SetWindowDisplayAffinity.argtypes = [wintypes.HANDLE, ctypes.c_uint]
    _SetWindowDisplayAffinity.restype = wintypes.BOOL


def is_supported() -> bool:
    """Return True if capture exclusion can actually be applied right now.

    On macOS this needs a Cocoa (non-offscreen) application, so it delegates to
    ``macos_window``; on Windows the Win32 call is always available.
    """
    if _IS_WINDOWS:
        return True
    if _IS_MACOS:
        from src.macos_window import is_supported as _macos_is_supported
        return _macos_is_supported()
    return False


def set_capture_protection(widget, enabled: bool) -> bool:
    """Exclude a Qt top-level widget from screen capture (or restore it).

    Returns True when the native call was applied, False on an unsupported
    platform or if the underlying call fails.
    """
    if _IS_WINDOWS:
        hwnd = wintypes.HWND(int(widget.winId()))
        affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
        return bool(_SetWindowDisplayAffinity(hwnd, affinity))
    if _IS_MACOS:
        return _macos_set_capture_exclusion(widget, enabled)
    return False
