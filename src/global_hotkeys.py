"""System-wide screenshot / bullet-point hotkeys, implemented natively per platform.

The same four shortcuts are registered on every platform:

- ``ALT+SHIFT+K``           capture a screenshot
- ``ALT+CTRL+SHIFT+K``      clear the captured screenshots
- ``CTRL+ALT+SHIFT+G``      send the captured screenshots to the AI
- ``CTRL+ALT+P``            force a bullet-points update

On **Windows** this uses ``user32.RegisterHotKey`` plus a Qt native event filter.
On **macOS** it uses the Carbon framework's ``RegisterEventHotKey`` (loaded via
ctypes, so there is no third-party dependency). Other platforms are a logged
no-op, so importing/starting the app never crashes.

The callbacks always run on the thread that registered the hotkeys (the Qt main
thread), so they may safely touch widgets.
"""

import ctypes
import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

# Hotkey ids used with RegisterHotKey / WM_HOTKEY (Windows) and as the
# EventHotKeyID.id on macOS.
HOTKEY_SCREENSHOT = 1
HOTKEY_CLEAR_SCREENSHOTS = 2
HOTKEY_SEND_IMAGES = 3
HOTKEY_BULLET_POINTS = 4


if _IS_WINDOWS:
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    VK_K = 0x4B
    VK_G = 0x47
    VK_P = 0x50

    _user32 = ctypes.windll.user32
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL


if _IS_MACOS:
    _Carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

    # Modifier masks (Events.h).
    _shiftKey = 0x0200
    _optionKey = 0x0800  # the "Alt" key on a Mac keyboard
    _controlKey = 0x1000

    # Virtual key codes (HIToolbox Events.h).
    _kVK_ANSI_K = 0x28
    _kVK_ANSI_G = 0x05
    _kVK_ANSI_P = 0x23

    # Event class / kind / parameter constants.
    _kEventClassKeyboard = 0x6B657962       # 'keyb'
    _kEventHotKeyPressed = 5
    _kEventParamDirectObject = 0x2D2D2D2D   # '----'
    _typeEventHotKeyID = 0x686B6964         # 'hkid'

    # Any FourCC identifies our registered hotkeys.
    _HOTKEY_SIGNATURE = 0x536E7848          # 'SnxH'

    class _EventHotKeyID(ctypes.Structure):
        _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

    class _EventTypeSpec(ctypes.Structure):
        _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

    # OSStatus EventHandlerProcPtr(EventHandlerCallRef, EventRef, void*)
    _EventHandlerProc = ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )

    _Carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

    _Carbon.InstallEventHandler.argtypes = [
        ctypes.c_void_p,                              # EventTargetRef
        _EventHandlerProc,                            # EventHandlerUPP
        ctypes.c_uint32,                              # ItemCount
        ctypes.POINTER(_EventTypeSpec),               # EventTypeSpec*
        ctypes.c_void_p,                              # userData
        ctypes.POINTER(ctypes.c_void_p),              # EventHandlerRef*
    ]
    _Carbon.InstallEventHandler.restype = ctypes.c_int32

    _Carbon.RegisterEventHotKey.argtypes = [
        ctypes.c_uint32,                              # hotKeyCode
        ctypes.c_uint32,                              # hotKeyModifiers
        _EventHotKeyID,                               # hotKeyID (by value)
        ctypes.c_void_p,                              # EventTargetRef
        ctypes.c_uint32,                              # options
        ctypes.POINTER(ctypes.c_void_p),              # EventHotKeyRef*
    ]
    _Carbon.RegisterEventHotKey.restype = ctypes.c_int32

    _Carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
    _Carbon.UnregisterEventHotKey.restype = ctypes.c_int32

    _Carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]
    _Carbon.RemoveEventHandler.restype = ctypes.c_int32

    _Carbon.GetEventParameter.argtypes = [
        ctypes.c_void_p,                              # EventRef
        ctypes.c_uint32,                              # EventParamName
        ctypes.c_uint32,                              # EventParamType
        ctypes.c_void_p,                              # actualType*
        ctypes.c_uint32,                              # bufferSize
        ctypes.c_void_p,                              # actualSize*
        ctypes.c_void_p,                              # data*
    ]
    _Carbon.GetEventParameter.restype = ctypes.c_int32


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Register system-wide hotkeys and dispatch them to plain callables.

    ``ALT+SHIFT+K`` triggers ``on_screenshot``, ``ALT+CTRL+SHIFT+K`` triggers
    ``on_clear``, ``CTRL+ALT+SHIFT+G`` triggers ``on_send_image`` and
    ``CTRL+ALT+P`` triggers ``on_bullet_points``. On a Mac keyboard ``Alt`` is
    the Option key. The callbacks run on the Qt main thread, so they may safely
    touch widgets.
    """

    def __init__(self, on_screenshot=None, on_clear=None, on_send_image=None, on_bullet_points=None):
        super().__init__()
        self._callbacks = {
            HOTKEY_SCREENSHOT: on_screenshot,
            HOTKEY_CLEAR_SCREENSHOTS: on_clear,
            HOTKEY_SEND_IMAGES: on_send_image,
            HOTKEY_BULLET_POINTS: on_bullet_points,
        }
        self._registered = []
        self._filter_installed = False
        # macOS state; unused on Windows.
        self._mac_handler = None
        self._mac_handler_ref = None
        self._mac_hotkey_refs = []

    def register(self):
        if _IS_WINDOWS:
            self._register_windows()
        elif _IS_MACOS:
            self._register_macos()
        else:
            logger.warning("Global hotkeys are not supported on this platform (%s)", sys.platform)

    def unregister(self):
        if _IS_WINDOWS:
            self._unregister_windows()
        elif _IS_MACOS:
            self._unregister_macos()
        self._registered.clear()

    def _dispatch(self, hotkey_id: int):
        callback = self._callbacks.get(hotkey_id)
        if callback:
            callback()

    # --- Windows -----------------------------------------------------------

    def _register_windows(self):
        app = QApplication.instance()
        if app is None:
            logger.warning("No QApplication; global hotkeys not registered")
            return
        if not self._filter_installed:
            app.installNativeEventFilter(self)
            self._filter_installed = True

        self._register_windows_hotkey(HOTKEY_SCREENSHOT, MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_K)
        self._register_windows_hotkey(
            HOTKEY_CLEAR_SCREENSHOTS, MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_K
        )
        self._register_windows_hotkey(
            HOTKEY_SEND_IMAGES, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_G
        )
        self._register_windows_hotkey(
            HOTKEY_BULLET_POINTS, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_P
        )

    def _register_windows_hotkey(self, hotkey_id: int, modifiers: int, vk: int):
        if _user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
            self._registered.append(hotkey_id)
        else:
            logger.warning("Failed to register hotkey id=%s (already in use?)", hotkey_id)

    def _unregister_windows(self):
        for hotkey_id in self._registered:
            _user32.UnregisterHotKey(None, hotkey_id)

        app = QApplication.instance()
        if app is not None and self._filter_installed:
            app.removeNativeEventFilter(self)
            self._filter_installed = False

    def nativeEventFilter(self, eventType, message):
        if bytes(eventType) in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY:
                self._dispatch(int(msg.wParam))
        return False

    # --- macOS -------------------------------------------------------------

    def _register_macos(self):
        if QApplication.instance() is None:
            logger.warning("No QApplication; global hotkeys not registered")
            return

        # Keep the CFUNCTYPE wrapper alive for as long as the handler is installed.
        self._mac_handler = _EventHandlerProc(self._handle_mac_event)
        handler_ref = ctypes.c_void_p()
        event_type = _EventTypeSpec(_kEventClassKeyboard, _kEventHotKeyPressed)
        status = _Carbon.InstallEventHandler(
            _Carbon.GetApplicationEventTarget(),
            self._mac_handler,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(handler_ref),
        )
        if status != 0:
            logger.warning("Failed to install macOS hotkey handler (OSStatus %d)", status)
            self._mac_handler = None
            return
        self._mac_handler_ref = handler_ref

        self._register_mac_hotkey(HOTKEY_SCREENSHOT, _optionKey | _shiftKey, _kVK_ANSI_K)
        self._register_mac_hotkey(
            HOTKEY_CLEAR_SCREENSHOTS, _optionKey | _controlKey | _shiftKey, _kVK_ANSI_K
        )
        self._register_mac_hotkey(
            HOTKEY_SEND_IMAGES, _controlKey | _optionKey | _shiftKey, _kVK_ANSI_G
        )
        self._register_mac_hotkey(HOTKEY_BULLET_POINTS, _controlKey | _optionKey, _kVK_ANSI_P)

    def _register_mac_hotkey(self, hotkey_id: int, modifiers: int, keycode: int):
        hotkey_ref = ctypes.c_void_p()
        hotkey = _EventHotKeyID(_HOTKEY_SIGNATURE, hotkey_id)
        status = _Carbon.RegisterEventHotKey(
            keycode,
            modifiers,
            hotkey,
            _Carbon.GetApplicationEventTarget(),
            0,
            ctypes.byref(hotkey_ref),
        )
        if status == 0:
            self._mac_hotkey_refs.append(hotkey_ref)
            self._registered.append(hotkey_id)
        else:
            logger.warning(
                "Failed to register hotkey id=%s (OSStatus %d; already in use?)",
                hotkey_id,
                status,
            )

    def _handle_mac_event(self, call_ref, event_ref, user_data):
        hotkey_id = _EventHotKeyID()
        status = _Carbon.GetEventParameter(
            event_ref,
            _kEventParamDirectObject,
            _typeEventHotKeyID,
            None,
            ctypes.sizeof(_EventHotKeyID),
            None,
            ctypes.byref(hotkey_id),
        )
        if status == 0 and hotkey_id.signature == _HOTKEY_SIGNATURE:
            self._dispatch(int(hotkey_id.id))
        return 0

    def _unregister_macos(self):
        for hotkey_ref in self._mac_hotkey_refs:
            _Carbon.UnregisterEventHotKey(hotkey_ref)
        self._mac_hotkey_refs.clear()

        if self._mac_handler_ref is not None:
            _Carbon.RemoveEventHandler(self._mac_handler_ref)
            self._mac_handler_ref = None
        self._mac_handler = None
