"""Native macOS window tweaks, driven through the Objective-C runtime (ctypes).

Sibling of ``screen_protection`` (the Windows equivalent): both are called from
every platform, but only do work on their own OS.

* **Always on top** — Qt already maps ``WindowStaysOnTopHint`` onto a floating
  ``NSWindow`` level (measured: level 8), so this is not a no-op on macOS: it
  re-asserts the level after a window is re-created/re-shown and adds
  ``NSWindowCollectionBehaviorFullScreenAuxiliary`` so the window also stays
  above a *full-screen* app, which the Qt flag alone does not do.
* **Capture exclusion** — sets ``NSWindow.sharingType`` to
  ``NSWindowSharingNone``, which drops the window from the window-server frame
  buffer. Apple deprecated this in macOS 13 and ScreenCaptureKit-based
  capturers (macOS 15+) may ignore it, so it is **best-effort**, but it still
  hides the window from legacy ``CGWindowListCreateImage`` style capture.

Everything here is a no-op unless running on macOS under the Cocoa platform
plugin, so the callers never need to branch on the OS.
"""

import ctypes
import ctypes.util
import logging
import sys

from PySide6.QtGui import QGuiApplication

logger = logging.getLogger(__name__)

_IS_MACOS = sys.platform == "darwin"

# NSWindowLevel (AppKit NSWindow.h).
NS_NORMAL_WINDOW_LEVEL = 0
NS_FLOATING_WINDOW_LEVEL = 3
# NSWindowCollectionBehavior (NS_OPTIONS, NSUInteger).
NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY = 1 << 8
# NSWindowSharingType.
NS_WINDOW_SHARING_NONE = 0
NS_WINDOW_SHARING_READ_ONLY = 1

_ready = False
_sel_register = None
_libobjc = None
# objc_msgSend casts are cached by signature (they are used on every call).
_send_cache = {}


def _init_objc() -> bool:
    """Load libobjc and cache ``sel_registerName``. Returns True on success."""
    global _ready, _sel_register, _libobjc
    if _ready:
        return True
    if not _IS_MACOS:
        return False
    try:
        _libobjc = ctypes.CDLL(ctypes.util.find_library("objc"))
        sel_register = _libobjc.sel_registerName
        sel_register.restype = ctypes.c_void_p
        sel_register.argtypes = [ctypes.c_char_p]
        _sel_register = sel_register
        _ready = True
    except Exception as e:
        logger.warning("Could not load the Objective-C runtime: %s", e)
        return False
    return True


def _usable() -> bool:
    """True when we can safely touch real NSWindow objects."""
    if not _IS_MACOS or QGuiApplication.instance() is None:
        return False
    # Guard against non-Cocoa platforms (e.g. the offscreen plugin): there
    # winId() is not an NSView and messaging it would crash.
    return QGuiApplication.platformName() == "cocoa" and _init_objc()


def _send(restype, *argtypes):
    """A cached ``objc_msgSend`` cast with an explicit signature.

    The explicit argtypes matter: without them ctypes passes every argument as
    a C ``int``, truncating the 64-bit object/SEL pointers and crashing.
    """
    if not _init_objc():
        raise RuntimeError("the Objective-C runtime is not available")
    key = (restype, argtypes)
    func = _send_cache.get(key)
    if func is None:
        func = ctypes.CFUNCTYPE(restype, *argtypes)(("objc_msgSend", _libobjc))
        _send_cache[key] = func
    return func


def _sel(name: bytes) -> ctypes.c_void_p:
    return ctypes.c_void_p(_sel_register(name))


def _ns_window(widget):
    """Return the widget's ``NSWindow*``, or None if it has no native window."""
    try:
        view_value = int(widget.winId())
    except (TypeError, ValueError, RuntimeError):
        return None
    if not view_value:
        return None
    msg = _send(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    window = msg(ctypes.c_void_p(view_value), _sel(b"window"))
    return window or None


def _get_unsigned(win, name: str) -> int:
    msg = _send(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)
    return int(msg(win, _sel(name.encode())))


def _set_unsigned(win, name: str, value: int):
    """Send a one-argument setter. ``name`` is the bare property name; the
    Objective-C selector needs the trailing colon (``setLevel:``)."""
    msg = _send(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    msg(win, _sel(f"{name}:".encode()), value)


def _responds_to(win, name: str) -> bool:
    """Whether the window implements ``name`` (avoids an unrecognised-selector
    crash, which aborts the process rather than raising)."""
    msg = _send(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    try:
        return bool(msg(win, _sel(b"respondsToSelector:"), _sel(f"{name}:".encode())))
    except Exception:
        return False


def _set_bool(win, name: str, value: bool):
    """Send a setter whose argument is a C ``BOOL``."""
    msg = _send(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
    msg(win, _sel(f"{name}:".encode()), bool(value))


def is_supported() -> bool:
    """Return True if the native macOS window tweaks are available."""
    return _usable()


def set_always_on_top(widget, enabled: bool) -> bool:
    """Float ``widget`` above normal windows (and full-screen apps).

    The level is re-asserted explicitly because Qt re-creates the ``NSWindow``
    when window flags change, and ``FullScreenAuxiliary`` is added so the window
    is also usable alongside a full-screen app — the part Qt's
    ``WindowStaysOnTopHint`` alone does not cover. Returns True when the native
    call was applied.
    """
    if not _usable():
        return False
    win = _ns_window(widget)
    if win is None:
        return False
    try:
        if enabled:
            # Never *lower* the level Qt already assigned: Qt uses
            # NSModalPanelWindowLevel (8) for WindowStaysOnTopHint, which is
            # above NSFloatingWindowLevel (3), so only raise it when needed.
            level = max(int(_get_unsigned(win, "level")), NS_FLOATING_WINDOW_LEVEL)
        else:
            level = NS_NORMAL_WINDOW_LEVEL
        _set_unsigned(win, "setLevel", level)
        behavior = _get_unsigned(win, "collectionBehavior")
        if enabled:
            behavior |= NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
        else:
            behavior &= ~NS_WINDOW_COLLECTION_BEHAVIOR_FULL_SCREEN_AUXILIARY
        _set_unsigned(win, "setCollectionBehavior", behavior)
        # Qt::Tool windows are NSPanels whose hidesOnDeactivate defaults to YES,
        # so macOS hides them the moment the app loses focus. Clear it so the
        # window really stays on top of other apps.
        if _responds_to(win, "setHidesOnDeactivate"):
            _set_bool(win, "setHidesOnDeactivate", False)
    except Exception as e:
        logger.warning("Failed to set the macOS window level: %s", e)
        return False
    return True


def set_capture_exclusion(widget, enabled: bool) -> bool:
    """Hide ``widget`` from (or restore it to) capture via ``sharingType``.

    Returns True only when the requested value actually took effect. On macOS
    ``sharingType`` is effectively **one-way**: once a window is
    ``NSWindowSharingNone`` it cannot be made shareable again, so disabling the
    exclusion on an already-excluded window reports False (the window stays
    hidden from capture until it is recreated).
    """
    if not _usable():
        return False
    win = _ns_window(widget)
    if win is None:
        return False
    wanted = NS_WINDOW_SHARING_NONE if enabled else NS_WINDOW_SHARING_READ_ONLY
    try:
        _set_unsigned(win, "setSharingType", wanted)
        applied = _get_unsigned(win, "sharingType")
    except Exception as e:
        logger.warning("Failed to set the macOS window sharing type: %s", e)
        return False
    if applied != wanted:
        if not enabled:
            logger.warning(
                "macOS cannot restore screen-capture exclusion for an already-excluded "
                "window (NSWindow.sharingType is one-way); it stays hidden from capture."
            )
        return False
    return True
