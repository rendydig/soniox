"""Screen-capture permission checks (macOS Screen Recording).

Sibling of ``screen_protection``: both are called from every platform, but only
do work on their own OS.

macOS 10.15+ requires the process that captures the screen to hold the *Screen
Recording* permission. Without it the capture does not fail: the CoreGraphics
API behind ``QScreen.grabWindow()`` silently returns an image containing only
the desktop wallpaper and the menu bar, so every other window is missing.

This module wraps ``CGPreflightScreenCaptureAccess`` /
``CGRequestScreenCaptureAccess`` (CoreGraphics, via ctypes — no third-party
dependency) so callers can detect that state and prompt for it. It reports
"granted" on non-macOS platforms, so callers never branch on the OS.
"""

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

_IS_MACOS = sys.platform == "darwin"

_cg = None
if _IS_MACOS:
    try:
        _cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        _cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        _cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
    except (OSError, AttributeError) as e:
        # Pre-10.15 macOS has no Screen Recording permission and no API.
        logger.warning("CoreGraphics screen-capture permission APIs unavailable: %s", e)
        _cg = None


def is_supported() -> bool:
    """True when a real permission check is possible (macOS + CoreGraphics)."""
    return _IS_MACOS and _cg is not None


def has_permission() -> bool:
    """Whether this process may capture the screen, without prompting.

    Always True off macOS (or when the API is unavailable), so callers can
    treat a False result as "a capture would only return the wallpaper".
    """
    if not is_supported():
        return True
    return bool(_cg.CGPreflightScreenCaptureAccess())


def request_permission() -> bool:
    """Ask macOS for Screen Recording permission, showing the system prompt.

    Returns whether it is granted *now*. macOS grants it asynchronously, so a
    False result means the user must enable it in System Settings → Privacy &
    Security → Screen Recording and restart the app. No-op returning True off
    macOS. macOS only shows the prompt once; if it was previously denied the
    user has to enable it manually.
    """
    if not is_supported():
        return True
    return bool(_cg.CGRequestScreenCaptureAccess())
