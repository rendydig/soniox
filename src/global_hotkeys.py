"""System-wide screenshot / bullet-point hotkeys, implemented natively per platform.

Four actions are registered, each with a configurable shortcut (defaults below):

- ``screenshot``         capture a screenshot          (Alt+Shift+K)
- ``clear_screenshots``  clear the captured screenshots
- ``send_images``        send the captured screenshots to the AI
- ``bullet_points``      force a bullet-points update

On **Windows** this uses ``user32.RegisterHotKey`` plus a Qt native event filter.
On **macOS** it uses the Carbon framework's ``RegisterEventHotKey`` (loaded via
ctypes, so there is no third-party dependency). Other platforms are a logged
no-op, so importing/starting the app never crashes.

Shortcuts are handled as Qt **portable** strings (``"Ctrl+Alt+P"``), so the user
can rebind them from Settings. ``rebind(``{id: shortcut}``)`` unregisters the old
set and registers the new one without restarting the app. The callbacks always
run on the thread that registered the hotkeys (the Qt main thread), so they may
safely touch widgets.
"""

import ctypes
import logging
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence
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

# Stable action names used for persistence (ui_state.json / Settings).
HOTKEY_ACTIONS = {
    HOTKEY_SCREENSHOT: "screenshot",
    HOTKEY_CLEAR_SCREENSHOTS: "clear_screenshots",
    HOTKEY_SEND_IMAGES: "send_images",
    HOTKEY_BULLET_POINTS: "bullet_points",
}
HOTKEY_IDS = {name: hotkey_id for hotkey_id, name in HOTKEY_ACTIONS.items()}


def default_bindings():
    """Default portable shortcut per hotkey id (mirrors the historical keys)."""
    if _IS_MACOS:
        # Qt swaps Ctrl/Cmd on macOS, so "Meta" is the physical Control key.
        return {
            HOTKEY_SCREENSHOT: "Alt+Shift+K",
            HOTKEY_CLEAR_SCREENSHOTS: "Meta+Alt+Shift+K",
            HOTKEY_SEND_IMAGES: "Meta+Alt+Shift+G",
            HOTKEY_BULLET_POINTS: "Meta+Alt+P",
        }
    return {
        HOTKEY_SCREENSHOT: "Alt+Shift+K",
        HOTKEY_CLEAR_SCREENSHOTS: "Alt+Ctrl+Shift+K",
        HOTKEY_SEND_IMAGES: "Ctrl+Alt+Shift+G",
        HOTKEY_BULLET_POINTS: "Ctrl+Alt+P",
    }


def parse_bindings(mapping):
    """Convert a persisted ``{action_name: shortcut}`` dict to ``{hotkey_id: shortcut}``."""
    result = {}
    if isinstance(mapping, dict):
        for name, shortcut in mapping.items():
            hotkey_id = HOTKEY_IDS.get(name)
            if hotkey_id is not None and isinstance(shortcut, str) and shortcut.strip():
                result[hotkey_id] = shortcut.strip()
    return result


def serialize_bindings(bindings):
    """Convert ``{hotkey_id: shortcut}`` to ``{action_name: shortcut}`` for persistence."""
    return {
        HOTKEY_ACTIONS[hotkey_id]: shortcut
        for hotkey_id, shortcut in (bindings or {}).items()
        if hotkey_id in HOTKEY_ACTIONS
    }


def _parse_shortcut(shortcut):
    """Return ``(Qt.Key, Qt.KeyboardModifier)`` for a single-combo shortcut, else ``None``."""
    if not shortcut:
        return None
    try:
        seq = QKeySequence(shortcut)
    except (TypeError, ValueError):
        return None
    if seq.isEmpty() or seq.count() != 1:
        return None
    item = seq[0]
    if hasattr(item, "key"):  # Qt6 QKeyCombination
        key = int(item.key())
        mods = item.keyboardModifiers()
    else:  # pragma: no cover - older bindings returned a plain int
        raw = int(item)
        key = raw & ~0xFE000000
        mods = Qt.KeyboardModifier(raw & 0xFE000000)
    if key in (0, int(Qt.Key.Key_unknown)):
        return None
    return key, mods


if _IS_WINDOWS:
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    _user32 = ctypes.windll.user32
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL

    # Qt key -> Windows virtual-key code (letters, digits, F1-F24, space).
    _WINDOWS_VK = {}
    for _i, _ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        _WINDOWS_VK[int(getattr(Qt.Key, f"Key_{_ch}"))] = 0x41 + _i
    for _d in range(10):
        _WINDOWS_VK[int(getattr(Qt.Key, f"Key_{_d}"))] = 0x30 + _d
    for _n in range(1, 25):
        _WINDOWS_VK[int(getattr(Qt.Key, f"Key_F{_n}"))] = 0x70 + (_n - 1)
    _WINDOWS_VK[int(Qt.Key.Key_Space)] = 0x20

    def _to_windows(shortcut):
        """Map a portable shortcut to ``(modifiers, virtual_key)`` or ``None``."""
        parsed = _parse_shortcut(shortcut)
        if parsed is None:
            return None
        key, mods = parsed
        vk = _WINDOWS_VK.get(key)
        if vk is None:
            return None
        mask = MOD_NOREPEAT
        if mods & Qt.KeyboardModifier.AltModifier:
            mask |= MOD_ALT
        if mods & Qt.KeyboardModifier.ControlModifier:
            mask |= MOD_CONTROL
        if mods & Qt.KeyboardModifier.ShiftModifier:
            mask |= MOD_SHIFT
        if mods & Qt.KeyboardModifier.MetaModifier:
            mask |= MOD_WIN
        return mask, vk


if _IS_MACOS:
    _Carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")

    # Modifier masks (Events.h).
    _cmdKey = 0x0100
    _shiftKey = 0x0200
    _optionKey = 0x0800  # the "Alt" key on a Mac keyboard
    _controlKey = 0x1000

    # Qt key -> Carbon virtual key code (ANSI letters/digits, F1-F12, space).
    _MAC_KEYCODES = {
        Qt.Key.Key_A: 0x00, Qt.Key.Key_S: 0x01, Qt.Key.Key_D: 0x02, Qt.Key.Key_F: 0x03,
        Qt.Key.Key_H: 0x04, Qt.Key.Key_G: 0x05, Qt.Key.Key_Z: 0x06, Qt.Key.Key_X: 0x07,
        Qt.Key.Key_C: 0x08, Qt.Key.Key_V: 0x09, Qt.Key.Key_B: 0x0B, Qt.Key.Key_Q: 0x0C,
        Qt.Key.Key_W: 0x0D, Qt.Key.Key_E: 0x0E, Qt.Key.Key_R: 0x0F, Qt.Key.Key_Y: 0x10,
        Qt.Key.Key_T: 0x11, Qt.Key.Key_1: 0x12, Qt.Key.Key_2: 0x13, Qt.Key.Key_3: 0x14,
        Qt.Key.Key_4: 0x15, Qt.Key.Key_6: 0x16, Qt.Key.Key_5: 0x17, Qt.Key.Key_9: 0x19,
        Qt.Key.Key_7: 0x1A, Qt.Key.Key_8: 0x1C, Qt.Key.Key_0: 0x1D, Qt.Key.Key_O: 0x1F,
        Qt.Key.Key_U: 0x20, Qt.Key.Key_I: 0x22, Qt.Key.Key_P: 0x23, Qt.Key.Key_L: 0x25,
        Qt.Key.Key_J: 0x26, Qt.Key.Key_K: 0x28, Qt.Key.Key_N: 0x2D, Qt.Key.Key_M: 0x2E,
        Qt.Key.Key_F1: 0x7A, Qt.Key.Key_F2: 0x78, Qt.Key.Key_F3: 0x63, Qt.Key.Key_F4: 0x76,
        Qt.Key.Key_F5: 0x60, Qt.Key.Key_F6: 0x61, Qt.Key.Key_F7: 0x62, Qt.Key.Key_F8: 0x64,
        Qt.Key.Key_F9: 0x65, Qt.Key.Key_F10: 0x6D, Qt.Key.Key_F11: 0x67, Qt.Key.Key_F12: 0x6F,
        Qt.Key.Key_Space: 0x31,
    }
    _MAC_KEYCODES = {int(k): v for k, v in _MAC_KEYCODES.items()}

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

    def _to_macos(shortcut):
        """Map a portable shortcut to ``(modifiers, keycode)`` or ``None``.

        Qt swaps Ctrl/Cmd on macOS: ``ControlModifier`` is the Command key and
        ``MetaModifier`` is the physical Control key, so the mapping is inverted
        relative to the Carbon modifier names.
        """
        parsed = _parse_shortcut(shortcut)
        if parsed is None:
            return None
        key, mods = parsed
        code = _MAC_KEYCODES.get(key)
        if code is None:
            return None
        mask = 0
        if mods & Qt.KeyboardModifier.ControlModifier:
            mask |= _cmdKey
        if mods & Qt.KeyboardModifier.AltModifier:
            mask |= _optionKey
        if mods & Qt.KeyboardModifier.ShiftModifier:
            mask |= _shiftKey
        if mods & Qt.KeyboardModifier.MetaModifier:
            mask |= _controlKey
        return mask, code


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Register system-wide hotkeys and dispatch them to plain callables.

    Each action maps to a portable shortcut (see :func:`default_bindings`) and to
    a callback; ``on_screenshot`` fires for ``screenshot``, ``on_clear`` for
    ``clear_screenshots``, ``on_send_image`` for ``send_images`` and
    ``on_bullet_points`` for ``bullet_points``. Bindings can be changed at runtime
    with :meth:`rebind`. The callbacks run on the Qt main thread, so they may
    safely touch widgets.
    """

    def __init__(self, on_screenshot=None, on_clear=None, on_send_image=None,
                 on_bullet_points=None, bindings=None):
        super().__init__()
        self._callbacks = {
            HOTKEY_SCREENSHOT: on_screenshot,
            HOTKEY_CLEAR_SCREENSHOTS: on_clear,
            HOTKEY_SEND_IMAGES: on_send_image,
            HOTKEY_BULLET_POINTS: on_bullet_points,
        }
        self._bindings = default_bindings()
        self._apply_overrides(bindings)
        self._registered = []
        self._filter_installed = False
        # macOS state; unused on Windows.
        self._mac_handler = None
        self._mac_handler_ref = None
        self._mac_hotkey_refs = []

    def _apply_overrides(self, bindings):
        """Merge valid ``{hotkey_id: shortcut}`` overrides into the defaults."""
        if not isinstance(bindings, dict):
            return
        for hotkey_id, shortcut in bindings.items():
            if hotkey_id in self._bindings and isinstance(shortcut, str) and shortcut.strip():
                self._bindings[hotkey_id] = shortcut.strip()

    def bindings(self):
        """Return a copy of the current ``{hotkey_id: shortcut}`` mapping."""
        return dict(self._bindings)

    def register(self):
        if _IS_WINDOWS:
            self._register_windows()
        elif _IS_MACOS:
            self._register_macos()
        else:
            logger.warning("Global hotkeys are not supported on this platform (%s)", sys.platform)

    def rebind(self, bindings):
        """Replace the shortcuts and re-register the system-wide hotkeys.

        Unknown keys are logged and skipped; the rest still register. A hotkey
        whose combination is already taken by another app fails to register (the
        OS reports it) and is logged rather than raised.
        """
        self.unregister()
        self._apply_overrides(bindings)
        self.register()
        logger.info("Global hotkeys rebound: %s", serialize_bindings(self._bindings))

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

        for hotkey_id, shortcut in self._bindings.items():
            parsed = _to_windows(shortcut)
            if parsed is None:
                logger.warning(
                    "Cannot register hotkey id=%s: unsupported shortcut %r", hotkey_id, shortcut
                )
                continue
            modifiers, vk = parsed
            self._register_windows_hotkey(hotkey_id, modifiers, vk)

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

        for hotkey_id, shortcut in self._bindings.items():
            parsed = _to_macos(shortcut)
            if parsed is None:
                logger.warning(
                    "Cannot register hotkey id=%s: unsupported shortcut %r", hotkey_id, shortcut
                )
                continue
            modifiers, keycode = parsed
            self._register_mac_hotkey(hotkey_id, modifiers, keycode)

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
