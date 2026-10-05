"""Windows screen-capture exclusion for Qt top-level windows.

Uses ``SetWindowDisplayAffinity`` (user32) so the OS omits the window's pixels
from screen captures while leaving it visible on the physical monitor.
"""

import ctypes
import sys
from ctypes import wintypes

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _SetWindowDisplayAffinity = _user32.SetWindowDisplayAffinity
    _SetWindowDisplayAffinity.argtypes = [wintypes.HANDLE, ctypes.c_uint]
    _SetWindowDisplayAffinity.restype = wintypes.BOOL


def is_supported() -> bool:
    """Return True if capture exclusion is available on this platform."""
    return _IS_WINDOWS


def set_capture_protection(widget, enabled: bool) -> bool:
    """Exclude a Qt top-level widget from screen capture (or restore it).

    Returns True on success, False on non-Windows platforms or if the
    underlying Win32 call fails.
    """
    if not _IS_WINDOWS:
        return False
    hwnd = wintypes.HWND(int(widget.winId()))
    affinity = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
    return bool(_SetWindowDisplayAffinity(hwnd, affinity))
