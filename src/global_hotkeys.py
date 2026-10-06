import ctypes
import logging
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_K = 0x4B
VK_G = 0x47

# Hotkey ids used with RegisterHotKey / WM_HOTKEY.
HOTKEY_SCREENSHOT = 1
HOTKEY_CLEAR_SCREENSHOTS = 2
HOTKEY_SEND_IMAGES = 3

_user32 = ctypes.windll.user32
_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.UnregisterHotKey.restype = wintypes.BOOL


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Register system-wide hotkeys and dispatch them to plain callables.

    ``ALT+SHIFT+K`` triggers ``on_screenshot``, ``ALT+CTRL+SHIFT+K`` triggers
    ``on_clear`` and ``CTRL+ALT+SHIFT+G`` triggers ``on_send_image``. The
    callbacks run on the Qt main thread (the thread that registered the
    hotkeys), so they may safely touch widgets.
    """

    def __init__(self, on_screenshot=None, on_clear=None, on_send_image=None):
        super().__init__()
        self._on_screenshot = on_screenshot
        self._on_clear = on_clear
        self._on_send_image = on_send_image
        self._registered = []
        self._filter_installed = False

    def register(self):
        app = QApplication.instance()
        if app is None:
            logger.warning("No QApplication; global hotkeys not registered")
            return
        if not self._filter_installed:
            app.installNativeEventFilter(self)
            self._filter_installed = True

        self._register_hotkey(HOTKEY_SCREENSHOT, MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_K)
        self._register_hotkey(HOTKEY_CLEAR_SCREENSHOTS, MOD_ALT | MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_K)
        self._register_hotkey(HOTKEY_SEND_IMAGES, MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT, VK_G)

    def _register_hotkey(self, hotkey_id: int, modifiers: int, vk: int):
        if _user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
            self._registered.append(hotkey_id)
        else:
            logger.warning("Failed to register hotkey id=%s (already in use?)", hotkey_id)

    def unregister(self):
        for hotkey_id in self._registered:
            _user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()

        app = QApplication.instance()
        if app is not None and self._filter_installed:
            app.removeNativeEventFilter(self)
            self._filter_installed = False

    def nativeEventFilter(self, eventType, message):
        if bytes(eventType) in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY:
                if msg.wParam == HOTKEY_SCREENSHOT and self._on_screenshot:
                    self._on_screenshot()
                elif msg.wParam == HOTKEY_CLEAR_SCREENSHOTS and self._on_clear:
                    self._on_clear()
                elif msg.wParam == HOTKEY_SEND_IMAGES and self._on_send_image:
                    self._on_send_image()
        return False
