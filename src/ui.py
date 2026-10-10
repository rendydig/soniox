import sys
import os
import logging
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QDialog, QMenu, QToolButton, QPushButton, QMessageBox)
from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QActionGroup, QGuiApplication
from src.config import (
    MAX_TRANSCRIPTION_LINES,
    AUTO_REPLY_ENDPOINT_DEBOUNCE_MS,
    BULLET_FLUSH_INTERVAL_MS,
    LAST_PICKUP_DEBOUNCE_MS,
    LAST_PICKUP_ENDPOINT_DEBOUNCE_MS,
)
from src.purpose_store import PurposeStore
from src.text_formatter import append_timestamped_text, format_gemini_result
from src.macos_window import set_always_on_top
from src.screen_protection import set_capture_protection
from src.screen_permission import has_permission, request_permission
from src.screenshot import capture_screen_data_url
from src.global_hotkeys import GlobalHotkeys, default_bindings, parse_bindings, serialize_bindings
from src.controllers import (
    DeviceController,
    TranscriptionController,
    TranslationController,
    BulletPointsController,
    LastPickupController
)
from src.websocket_client import WebSocketClient
from src.websocket_server_manager import WebSocketServerManager
from src.ui_components import (
    SettingsViewWidget,
    TranslationSectionWidget,
    ControlButtonsWidget,
    StatusBarWidget,
    SwitchButton,
    DragHandle,
    GeminiWindow,
    LiveWindow,
    BulletPointsWindow
)
from src.ui_components.pane_resize_handle import PaneResizeHandle
from src.ui_state import load_state, save_state
from src.session_store import SessionStore

logger = logging.getLogger(__name__)

# Default width of the bottom bar. It is fixed (not derived from the panes) and
# user-resizable; the narrowest it can shrink to is the trimmed content minimum.
BAR_WIDTH = 560
# Absolute fallback for the bar's minimum width, used only before its layout is
# built (state load in __init__). The real floor is the trimmed control row's own
# minimum size hint (see _clamp_bar_width), which lets the bar shrink below the
# default width so a stored width is restored as-is.
MIN_BAR_WIDTH = 455
# Height of the bottom bar's always-visible control row (window frame included).
# The manual-translation input row is revealed above it, growing the bar upward.
BAR_HEIGHT = 40
INPUT_ROW_HEIGHT = 40
# Uniform height for the bar's interactive controls (buttons/toggles).
CONTROL_HEIGHT = 24
# Shared button styling. On macOS the native QPushButton and QToolButton bezels
# render at different visual heights for the same widget height, so an explicit
# border/background is required to make every control fill its rect and match.
BUTTON_STYLESHEET = """
QPushButton, QToolButton {
    background-color: #f6f6f6;
    border: 1px solid #c8c8c8;
    border-radius: 5px;
    padding: 3px 8px;
}
QPushButton:hover, QToolButton:hover { background-color: #ededed; }
QPushButton:pressed, QToolButton:pressed { background-color: #dcdcdc; }
QPushButton:checked { background-color: #d9534f; color: white; border-color: #c9433f; }
QToolButton::menu-indicator { image: none; width: 0; }
"""


def _as_dict(value):
    """Return ``value`` if it is a dict, else an empty dict (guards bad state)."""
    return value if isinstance(value, dict) else {}


class MainWindow(QMainWindow):
    # Emitted from the WebSocket receive thread and marshalled onto the Qt
    # main thread via a QueuedConnection (see _setup_controller_connections).
    webview_message = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soniox AI: Transcribe & Translate")
        # Frameless: no title bar, but the bar stays movable via its drag handle.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        
        self.device_controller = DeviceController()
        # Purpose registry: built-ins + user edits + AI-learned personas, persisted
        # asynchronously to purposes.json (memory is the source of truth).
        self.purpose_store = PurposeStore()
        self.transcription_controller = TranscriptionController()
        self.translation_controller = TranslationController(self.purpose_store)
        self.bullet_points_controller = BulletPointsController()
        self.last_pickup_controller = LastPickupController()
        # Session state (restored below, persisted asynchronously to disk).
        self.session_store = SessionStore()
        
        # Bring up the Node web service (port 8765) before connecting / loading
        # the Gemini pane, so both the client and the webview have a server.
        self._server_manager = WebSocketServerManager()
        self._server_manager.ensure_running()

        self.websocket_client = WebSocketClient("ws://localhost:8765")
        self.websocket_client.set_message_handler(self._on_ws_message_raw)
        self.websocket_client.start()

        # System-wide hotkeys: ALT+SHIFT+K captures a screenshot, ALT+CTRL+SHIFT+K
        # clears the ones shown in the Gemini pane, CTRL+ALT+SHIFT+G sends the
        # captured screenshots to Gemini, CTRL+ALT+P updates the bullet points, and
        # CTRL+SHIFT+M (Cmd+Shift+M on macOS) hides/restores all open panes.
        # Restore any user-customised global hotkeys from ui_state before registering.
        stored_hotkeys = _as_dict(_as_dict(load_state().get("settings")).get("hotkeys"))
        self.hotkeys = GlobalHotkeys(
            on_screenshot=self._capture_screenshot,
            on_clear=self._clear_screenshots,
            on_send_image=self._send_images_to_gemini,
            on_bullet_points=self._trigger_bullet_points_now,
            on_toggle_windows=self._toggle_all_panes,
            bindings=parse_bindings(stored_hotkeys),
        )
        self.hotkeys.register()

        # macOS gates screen capture behind the Screen Recording permission (the
        # responsible process is this terminal/IDE, not Python). Ask up front so
        # the system dialog appears instead of silently capturing the wallpaper
        # later; no-op off macOS, where has_permission() is always True.
        if not has_permission():
            logger.warning(
                "macOS Screen Recording permission not granted — screenshots will only "
                "contain the desktop wallpaper. Enable it for this terminal/IDE in "
                "System Settings → Privacy & Security → Screen & System Audio Recording "
                "and restart the app."
            )
            request_permission()

        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._update_memory_usage)
        self._memory_monitor_timer.start(5000)
        
        self._last_final_transcription = ""
        self._screenshots = []
        self._screen_protection_enabled = True
        self._auto_reply_enabled = False
        self._last_pickup_auto_enabled = False
        # Per-purpose "I am:" role choices (purpose_key -> role_key).
        self._host_role_by_purpose = {}
        # CTRL+SHIFT+M hides every open pane and restores exactly the ones that
        # were open; the flag tracks which side of the toggle we are on.
        self._all_panes_hidden = False
        self._panes_visibility_before_hide = {}

        # Separate top-level panes (not Qt children of this window). Their
        # geometry is restored from ui_state.json (written back on change).
        state = load_state()
        main_state = _as_dict(state.get("main_window"))
        gemini_state = _as_dict(state.get("gemini_window"))
        live_state = _as_dict(state.get("live_window"))
        bullet_points_state = _as_dict(state.get("bullet_points_window"))
        settings_state = _as_dict(state.get("settings"))
        self._always_on_top = bool(main_state.get("always_on_top", True))
        # Bar geometry: fixed default width, bottom-center unless the user moved it.
        self._bar_width = self._clamp_bar_width(main_state.get("width"))
        self._bar_x = main_state.get("x")
        self._bar_y = main_state.get("y")
        self.gemini_window = GeminiWindow( edge=gemini_state.get("edge"), width=gemini_state.get("width"), height=gemini_state.get("height"), x=gemini_state.get("x"), y=gemini_state.get("y"), docked=gemini_state.get("docked"),
        )
        self.live_window = LiveWindow( edge=live_state.get("edge"), width=live_state.get("width"), height=live_state.get("height"), x=live_state.get("x"), y=live_state.get("y"), docked=live_state.get("docked"),
        )
        # Defaults to free-floating (no "docked" key) so it doesn't collide with
        # the docked Gemini/Live panes.
        self.bullet_points_window = BulletPointsWindow( edge=bullet_points_state.get("edge"), width=bullet_points_state.get("width"), height=bullet_points_state.get("height"), x=bullet_points_state.get("x"), y=bullet_points_state.get("y"), docked=bullet_points_state.get("docked"),
        )

        # The Tool ▾ "Always on Top" toggle governs all four windows. Start the
        # panes in the persisted state (they are shown later in __init__).
        for _pane in (self.gemini_window, self.live_window, self.bullet_points_window):
            _pane.apply_always_on_top(self._always_on_top)

        self._init_menu()
        self._init_ui()
        self._setup_controller_connections()
        self._connect_pane_signals()
        self._apply_settings_state(settings_state)
        self._restore_session()
        self._connect_settings_signals()
        self.device_controller.populate_devices()
        self._apply_bar_geometry()
        self._connect_screen_signals()
        self.gemini_window.show()
        self.live_window.show()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        # Outer row: the bar content plus a right-edge handle that resizes the width.
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(6)

        # Top row: manual translation input, revealed by the toggle (hidden by
        # default) which grows the bar upward.
        self.translation_section = TranslationSectionWidget()
        self.translation_section.setVisible(False)
        root.addWidget(self.translation_section)

        # Bottom row: always-visible controls, mode/tool menus, status, close.
        row = QHBoxLayout()
        row.setSpacing(4)

        self.drag_handle = DragHandle()
        row.addWidget(self.drag_handle)

        self.control_buttons = ControlButtonsWidget()
        row.addWidget(self.control_buttons)
        row.addWidget(self.mode_button)
        row.addWidget(self.tool_button)
        row.addWidget(self.settings_button)

        # Toggle for the input row above; off by default.
        self.manual_switch = SwitchButton()
        self.manual_switch.setChecked(False)
        self.manual_switch.setToolTip("Show or hide the manual translation input.")
        self.manual_switch.toggled.connect(self._on_manual_switch_toggled)
        row.addWidget(self.manual_switch)

        row.addStretch(1)

        self.status_bar = StatusBarWidget()
        row.addWidget(self.status_bar)

        self.close_button = QPushButton("\u2715")
        self.close_button.setFixedWidth(36)
        self.close_button.setToolTip("Close the app")
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)

        root.addLayout(row)

        outer.addWidget(content, 1)
        self.width_handle = PaneResizeHandle(self, orientation="horizontal")
        self.width_handle.setToolTip("Drag to resize the bar")
        outer.addWidget(self.width_handle)

        # Settings lives in its own dialog. Created eagerly (hidden) so the
        # widget getters in _setup_widget_references stay valid.
        self.settings_view = SettingsViewWidget(purpose_store=self.purpose_store)
        self.settings_dialog = QDialog()
        self.settings_dialog.setWindowTitle("Settings")
        # Separate top-level window: keep it above the always-on-top bar.
        self.settings_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dialog_layout = QVBoxLayout(self.settings_dialog)
        dialog_layout.setContentsMargins(16, 16, 16, 16)
        dialog_layout.addWidget(self.settings_view)
        self.settings_view.back_requested.connect(self.settings_dialog.close)

        self._setup_widget_references()
        self._setup_widget_connections()
        self._apply_styles()

    def _current_bar_height(self):
        """Total bar height, including the input row when the toggle is on."""
        return BAR_HEIGHT + (INPUT_ROW_HEIGHT if self.manual_switch.isChecked() else 0)

    def _clamp_bar_width(self, width):
        try:
            width = int(width)
        except (TypeError, ValueError):
            width = BAR_WIDTH
        screen = QGuiApplication.primaryScreen()
        max_width = screen.availableGeometry().width() if screen is not None else BAR_WIDTH
        # The floor is the trimmed control row's own minimum so the bar can
        # shrink below its default width (the constant is only a fallback before
        # the layout exists); the width can never exceed the screen.
        central = self.centralWidget()
        min_width = central.minimumSizeHint().width() if central is not None else MIN_BAR_WIDTH
        return max(min_width, min(width, max_width))

    def _apply_bar_geometry(self):
        """Place the bar at its fixed width and stored position.

        With no stored position the bar sits bottom-centre, just above the
        taskbar (``availableGeometry`` already excludes the taskbar). A stored
        position is restored, only clamped so it can't land off-screen.
        """
        screen = QGuiApplication.primaryScreen()
        width = self._clamp_bar_width(self._bar_width)
        height = self._current_bar_height()
        x, y = self._bar_x, self._bar_y
        if screen is not None:
            avail = screen.availableGeometry()
            if x is None or y is None:
                x = avail.left() + max((avail.width() - width) // 2, 0)
                y = avail.bottom() + 1 - height
            else:
                x = max(avail.left(), min(int(x), avail.right() - width + 1))
                y = max(avail.top(), min(int(y), avail.bottom() - height + 1))
        else:
            x, y = int(x or 0), int(y or 0)
        self._bar_width, self._bar_x, self._bar_y = width, x, y
        self.resize(width, height)
        # The window is frameless, so move() positions the visible top-left.
        self.move(x, y)

    def get_width(self):
        """Current bar width (used by the right-edge resize handle)."""
        return self.width()

    def resize_by_drag(self, delta_x, start_width):
        """Resize the width from the right-edge handle, keeping the left edge."""
        self._bar_width = self._clamp_bar_width(start_width + delta_x)
        self.resize(self._bar_width, self.height())

    def reset_width(self):
        """Restore the default width (double-click the handle)."""
        self._bar_width = self._clamp_bar_width(BAR_WIDTH)
        self.resize(self._bar_width, self.height())
        self.finish_resize()

    def finish_resize(self):
        """Persist the width once a resize drag settles."""
        self._save_state()

    def move_to(self, point):
        """Move the bar from a drag position, clamped onto the screen."""
        x, y = int(point.x()), int(point.y())
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.left(), min(x, avail.right() - self.width() + 1))
            y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        self._bar_x, self._bar_y = x, y
        self.move(x, y)

    def finish_move(self):
        """Persist the position once a move drag settles."""
        self._save_state()

    def _on_manual_switch_toggled(self, checked):
        """Show/hide the input row, growing or shrinking upward from the bottom.

        The bottom edge is captured before the row is shown/hidden, since
        toggling it can transiently change the window's size hint.
        """
        bottom = self.y() + self.height()
        self.translation_section.setVisible(checked)
        height = self._current_bar_height()
        self.resize(self.width(), height)
        self._bar_y = bottom - height
        self.move(self.x(), self._bar_y)

    def _connect_pane_signals(self):
        """Persist each pane's geometry; the bar no longer follows the panes."""
        for pane in (self.gemini_window, self.live_window, self.bullet_points_window):
            pane.state_changed.connect(self._save_state)

    def _save_state(self):
        """Persist the bar/pane geometry and Settings for the next launch."""
        save_state({
            "main_window": {
                "always_on_top": self._always_on_top,
                "width": self.width(),
                "x": self.x(),
                "y": self.y(),
            },
            "gemini_window": {
                "edge": self.gemini_window.get_edge(),
                "docked": self.gemini_window.is_docked(),
                "width": self.gemini_window.get_width(),
                "height": self.gemini_window.get_height(),
                "x": self.gemini_window.get_x(),
                "y": self.gemini_window.get_y(),
            },
            "live_window": {
                "edge": self.live_window.get_edge(),
                "docked": self.live_window.is_docked(),
                "width": self.live_window.get_width(),
                "height": self.live_window.get_height(),
                "x": self.live_window.get_x(),
                "y": self.live_window.get_y(),
            },
            "bullet_points_window": {
                "edge": self.bullet_points_window.get_edge(),
                "docked": self.bullet_points_window.is_docked(),
                "width": self.bullet_points_window.get_width(),
                "height": self.bullet_points_window.get_height(),
                "x": self.bullet_points_window.get_x(),
                "y": self.bullet_points_window.get_y(),
            },
            "settings": {
                "view_mode": self.view_mode_combo.currentIndex(),
                "ai_reply_language": self.gemini_lang_combo.currentText(),
                "purpose": self.purpose_combo.currentData(),
                "host_role_by_purpose": dict(self._host_role_by_purpose),
                "smart_decision": self.smart_decision_checkbox.isChecked(),
                "pronunciation": self.pronunciation_checkbox.isChecked(),
                "bullet_points": self.bullet_points_checkbox.isChecked(),
                "bullet_points_window_visible": self.bullet_points_window_action.isChecked(),
                "last_pickup_auto": self._last_pickup_auto_enabled,
                "screen_protection": self.screen_protection_checkbox.isChecked(),
                "hotkeys": self._hotkeys_from_editors(),
            },
        })

    def _apply_settings_state(self, state):
        """Restore persisted Settings onto the widgets (falls back to defaults)."""
        view_mode = state.get("view_mode")
        if isinstance(view_mode, int) and 0<= view_mode < self.view_mode_combo.count():
            self.view_mode_combo.setCurrentIndex(view_mode)

        language = state.get("ai_reply_language")
        if language:
            index = self.gemini_lang_combo.findText(language)
            if index >= 0:
                self.gemini_lang_combo.setCurrentIndex(index)

        # Per-purpose "I am:" choices must be in place before the Purpose is
        # applied, so _on_purpose_changed can restore the remembered role.
        host_roles = state.get("host_role_by_purpose")
        if isinstance(host_roles, dict):
            self._host_role_by_purpose = {str(k): str(v) for k, v in host_roles.items()}

        # Purpose first: _on_purpose_changed resets pronunciation to its default.
        purpose = state.get("purpose")
        if purpose:
            index = self.purpose_combo.findData(purpose)
            if index >= 0:
                self.purpose_combo.setCurrentIndex(index)

        # Smart Decision (JEV) toggle. setChecked fires the handler, which pushes
        # the value to the controller and persists it.
        smart_decision = state.get("smart_decision")
        if isinstance(smart_decision, bool):
            self.smart_decision_checkbox.setChecked(smart_decision)

        # The combo may already sit on the stored purpose (so no change signal
        # fired); populate the roles at least once.
        self._refresh_host_roles(self.purpose_combo.currentData())

        pronunciation = state.get("pronunciation")
        if isinstance(pronunciation, bool):
            self.pronunciation_checkbox.setChecked(pronunciation)

        screen_protection = state.get("screen_protection")
        if isinstance(screen_protection, bool):
            self._set_screen_protection(screen_protection)

        # Enabling shows the pane (via _on_bullet_points_toggled); disabled stays hidden.
        bullet_points = state.get("bullet_points")
        if isinstance(bullet_points, bool):
            self.bullet_points_checkbox.setChecked(bullet_points)

        # "Last Picked Up" auto toggle (ui_state). Set before the pane-visibility
        # restore so the effective auto state is computed correctly.
        last_pickup_auto = state.get("last_pickup_auto")
        if isinstance(last_pickup_auto, bool):
            self._last_pickup_auto_enabled = last_pickup_auto

        # Restore the pane's visibility so a manual-only setup survives a restart.
        bullet_points_visible = state.get("bullet_points_window_visible")
        if isinstance(bullet_points_visible, bool):
            self.bullet_points_window_action.setChecked(bullet_points_visible)
        self._update_last_pickup_auto()

        # Global hotkeys: show the saved combination, else the platform default so
        # the fields are never blank before the user edits them. Setting the
        # sequence here does not emit editingFinished.
        stored = serialize_bindings(parse_bindings(_as_dict(state.get("hotkeys"))))
        defaults = serialize_bindings(default_bindings())
        for action, editor in self.hotkey_editors.items():
            shortcut = stored.get(action) or defaults.get(action)
            if shortcut:
                editor.setKeySequence(QKeySequence(shortcut))

    def _connect_settings_signals(self):
        """Persist Settings whenever one of them changes."""
        self.view_mode_combo.currentIndexChanged.connect(self._save_state)
        self.gemini_lang_combo.currentTextChanged.connect(self._save_state)
        self.purpose_combo.currentIndexChanged.connect(self._save_state)
        self.pronunciation_checkbox.toggled.connect(self._save_state)
        self.bullet_points_checkbox.toggled.connect(self._save_state)
        self.bullet_points_window_action.toggled.connect(self._save_state)
        self.screen_protection_checkbox.toggled.connect(self._save_state)
        self.settings_view.hotkeys_changed.connect(self._on_hotkeys_changed)

    def _hotkeys_from_editors(self):
        """Return ``{action_name: shortcut}`` from the Settings hotkey fields."""
        bindings = {}
        for action, editor in self.hotkey_editors.items():
            text = editor.keySequence().toString()
            if text:
                bindings[action] = text
        return bindings

    def _on_hotkeys_changed(self):
        """Re-register the system-wide hotkeys and persist the new combination."""
        bindings = parse_bindings(self._hotkeys_from_editors())
        self.hotkeys.rebind(bindings)
        self._save_state()

    def _connect_screen_signals(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_available_geometry_changed)

    def _on_available_geometry_changed(self, _rect):
        """Re-clamp the bar when the taskbar is shown/hidden/resized."""
        self._apply_bar_geometry()

    def _open_settings(self):
        """Show the separate Settings dialog, honouring screen protection."""
        set_always_on_top(self.settings_dialog, True)
        if self._screen_protection_enabled:
            set_capture_protection(self.settings_dialog, True)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _init_menu(self):
        self.mode_menu = QMenu("Mode: Live Transcription", self)

        self.mode_action_group = QActionGroup(self)
        self.mode_action_group.setExclusive(True)

        self.act_transcribe = QAction("Live Transcription", self)
        self.act_transcribe.setCheckable(True)
        self.act_transcribe.setChecked(True)
        self.act_translate = QAction("Live Translation", self)
        self.act_translate.setCheckable(True)

        self.mode_action_group.addAction(self.act_transcribe)
        self.mode_action_group.addAction(self.act_translate)
        self.mode_menu.addAction(self.act_transcribe)
        self.mode_menu.addAction(self.act_translate)

        self.act_transcribe.triggered.connect(lambda: self._on_mode_changed("transcription"))
        self.act_translate.triggered.connect(lambda: self._on_mode_changed("translation"))

        self.mode_button = QToolButton()
        # The ▾ sits right after the label; the native indicator is hidden in
        # _apply_styles so it doesn't float at the far right of the button.
        self.mode_button.setText("Mode ▾")
        self.mode_button.setToolTip("Mode: Transcription. Switch between Live Transcription and Live Translation.")
        self.mode_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.mode_button.setMenu(self.mode_menu)

        self.tool_menu = QMenu("Tool", self)
        self.screen_protection_action = QAction("Screen Protection", self)
        self.screen_protection_action.setCheckable(True)
        self.screen_protection_action.setChecked(True)
        self.screen_protection_action.toggled.connect(self._set_screen_protection)
        self.tool_menu.addAction(self.screen_protection_action)

        self.gemini_window_action = QAction("Gemini Window", self)
        self.gemini_window_action.setCheckable(True)
        self.gemini_window_action.setChecked(True)
        self.gemini_window_action.setToolTip("Show or hide the AI suggestion pane.")
        self.gemini_window_action.toggled.connect(self._set_gemini_window_visible)
        self.tool_menu.addAction(self.gemini_window_action)

        self.live_window_action = QAction("Live Window", self)
        self.live_window_action.setCheckable(True)
        self.live_window_action.setChecked(True)
        self.live_window_action.setToolTip("Show or hide the live view pane.")
        self.live_window_action.toggled.connect(self._set_live_window_visible)
        self.tool_menu.addAction(self.live_window_action)

        self.bullet_points_window_action = QAction("Bullet Points", self)
        self.bullet_points_window_action.setCheckable(True)
        self.bullet_points_window_action.setChecked(False)
        self.bullet_points_window_action.setToolTip(
            "Show or hide the bullet-points pane. Hiding pauses it and keeps the last list."
        )
        self.bullet_points_window_action.toggled.connect(self._set_bullet_points_window_visible)
        self.tool_menu.addAction(self.bullet_points_window_action)

        self.always_on_top_action = QAction("Always on Top", self)
        self.always_on_top_action.setCheckable(True)
        self.always_on_top_action.setChecked(self._always_on_top)
        self.always_on_top_action.setToolTip("Keep the control bar above other windows.")
        self.always_on_top_action.toggled.connect(self._set_always_on_top)
        self.tool_menu.addAction(self.always_on_top_action)

        # Applied before the window is shown, so no hide/re-show churn.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)

        self.tool_button = QToolButton()
        self.tool_button.setText("Tool ▾")
        self.tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tool_button.setMenu(self.tool_menu)

        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self._open_settings)
    
    def _setup_widget_references(self):
        self.device_combo = self.settings_view.get_device_combo()
        self.speaker_combo = self.settings_view.get_speaker_combo()
        
        self.lang_selection = self.settings_view.get_language_selection()
        self.lang_combo = self.lang_selection.get_lang_combo()
        self.view_mode_combo = self.settings_view.get_view_mode_combo()
        
        self.transcription_editor = self.live_window.get_transcription_editor()
        self.pronunciation_checkbox = self.settings_view.get_pronunciation_checkbox()
        self.purpose_combo = self.settings_view.get_purpose_combo()
        self.host_role_combo = self.settings_view.get_host_role_combo()
        self.smart_decision_checkbox = self.settings_view.get_smart_decision_checkbox()
        self.bullet_points_checkbox = self.settings_view.get_bullet_points_checkbox()
        self.screen_protection_checkbox = self.settings_view.get_screen_protection_checkbox()
        
        self.gemini_lang_combo = self.settings_view.get_gemini_lang_combo()
        self.hotkey_editors = self.settings_view.get_hotkey_editors()
        self.translation_input = self.translation_section.get_translation_input()
        
        self.btn_start = self.control_buttons.get_start_button()
        self.btn_new = self.control_buttons.get_new_button()

        # Equal heights across the control row (and the Settings dialog's button).
        for _button in (self.btn_start, self.btn_new, self.mode_button,
                        self.tool_button, self.settings_button, self.close_button,
                        self.settings_view.back_button):
            _button.setFixedHeight(CONTROL_HEIGHT)

        self.status_label = self.status_bar.get_status_label()
        # Trimmed for the fixed-width bar: the mode label duplicates the Mode
        # menu and the memory readout is dropped.
        self.mode_status_label = self.status_bar.get_mode_label()
        self.mode_status_label.setVisible(False)
        self.memory_label = self.status_bar.get_memory_label()
        self.memory_label.setVisible(False)
    
    def _setup_widget_connections(self):
        self.view_mode_combo.currentIndexChanged.connect(self.live_window.get_view_stack().setCurrentIndex)
        self.live_window.get_view_stack().setCurrentIndex(self.view_mode_combo.currentIndex())

        self.translation_input.installEventFilter(self)
        self.btn_start.clicked.connect(self._toggle_start)
        self.control_buttons.new_session_clicked.connect(self._new_session)
        self.pronunciation_checkbox.toggled.connect(self.translation_controller.set_pronunciation_enabled)
        self.translation_controller.set_pronunciation_enabled(self.pronunciation_checkbox.isChecked())
        self.purpose_combo.currentIndexChanged.connect(self._on_purpose_changed)
        self.host_role_combo.currentIndexChanged.connect(self._on_host_role_changed)
        self.smart_decision_checkbox.toggled.connect(self._on_smart_decision_toggled)
        self.screen_protection_checkbox.toggled.connect(self._set_screen_protection)
        self.bullet_points_checkbox.toggled.connect(self._on_bullet_points_toggled)
        
        reply_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        reply_shortcut.activated.connect(self._manual_reply)
    
    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget { font-size: 13px; }
            QComboBox, QLineEdit { padding: 4px 6px; }
            QTextEdit { font-family: 'Menlo', 'Monaco', 'Courier New', monospace; font-size: 13px; }
            """ + BUTTON_STYLESHEET
        )
        # The Settings dialog is a separate top-level window, so the MainWindow
        # stylesheet does not reach it; give it the same button styling.
        self.settings_dialog.setStyleSheet(BUTTON_STYLESHEET)
    
    def _setup_controller_connections(self):
        """Connect controller signals to UI handlers."""
        self.device_controller.devices_populated.connect(self._on_devices_populated)
        self.device_controller.device_error.connect(self._on_device_error)
        
        self.transcription_controller.status_changed.connect(self._update_status)
        self.transcription_controller.error_occurred.connect(self._on_transcription_error)
        self.transcription_controller.transcription_update.connect(self._on_transcription_update)
        self.transcription_controller.translation_update.connect(self._on_translation_update)
        self.transcription_controller.session_started.connect(self._on_transcription_started)
        self.transcription_controller.session_stopped.connect(self._on_transcription_stopped)
        
        self.translation_controller.status_changed.connect(self._update_status)
        self.translation_controller.error_occurred.connect(self._on_translation_error)
        self.translation_controller.translation_result.connect(self._on_translation_result)
        self.translation_controller.translation_started.connect(self._on_translation_started)
        self.translation_controller.auto_reply_result.connect(self._on_auto_reply_result)
        self.translation_controller.image_reply_result.connect(self._on_image_reply_result)
        self.translation_controller.reply_chunk.connect(self._on_reply_chunk)
        self.translation_controller.reply_skipped.connect(self._on_reply_skipped)

        # AI-learned purposes appear in the Purpose dropdown as they are registered
        # (emitted from the auto-reply worker thread -> queued to the UI thread).
        self.purpose_store.purposes_changed.connect(
            self._on_purpose_added, Qt.ConnectionType.QueuedConnection)
        
        self.bullet_points_controller.updated.connect(self._on_bullet_points_updated)
        self.bullet_points_controller.status_changed.connect(self._send_bullet_status)
        self.bullet_points_controller.error_occurred.connect(self._on_bullet_points_error)
        self.bullet_points_controller.countdown_changed.connect(self._send_bullet_countdown)

        self.last_pickup_controller.updated.connect(self._on_last_pickup_updated)
        self.last_pickup_controller.status_changed.connect(self._send_last_pickup_status)
        self.last_pickup_controller.error_occurred.connect(self._on_last_pickup_error)
        
        self.gemini_lang_combo.currentTextChanged.connect(self._on_auto_reply_language_changed)

        # WebSocket messages arrive on the asyncio thread; hop to the Qt thread.
        self.webview_message.connect(self._handle_webview_message, Qt.ConnectionType.QueuedConnection)

    def _on_mode_changed(self, mode):
        is_translation = (mode == "translation")
        self.lang_selection.setVisible(is_translation)
        label = "Translation" if is_translation else "Transcription"
        # The button stays "Mode" (fixed-width bar); the active mode is shown in
        # its tooltip and the menu checkmark.
        self.mode_button.setToolTip(f"Mode: {label}. Switch between Live Transcription and Live Translation.")
        self.mode_status_label.setText(label)
        self._update_start_button_text()

    def _update_start_button_text(self):
        """Set the start button label from the current mode (unless a session is running)."""
        if self.btn_start.isChecked():
            return
        self.btn_start.setText("Start")

    def _toggle_start(self, checked):
        if checked:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        host_device_id = self.device_combo.currentData()
        if host_device_id is None:
            logger.warning("Cannot start: no host input device selected.")
            self.btn_start.setChecked(False)
            return

        # Get speaker loopback device (optional); only use it if it's different from host
        speaker_device = self.speaker_combo.currentData()
        if speaker_device == host_device_id:
            speaker_device = None
        
        mode = "translation" if self.act_translate.isChecked() else "transcription"
        target_lang = self.lang_combo.currentData()

        # Stop -> Start resumes the same session (no clearing); use New Session
        # to start a fresh one.
        self.transcription_controller.start_session(host_device_id, speaker_device, mode=mode, target_lang=target_lang)

    def _stop_session(self):
        self.status_label.setText("Stopping...")
        
        self.translation_controller.cancel_auto_reply()
        self.bullet_points_controller.flush_now()
        self.transcription_controller.stop_session()

    def _restore_session(self):
        """Restore the previous session's state into the controllers and editor."""
        data = self.session_store.snapshot()
        self.bullet_points_controller.load_state(
            data.get("bullets") or [], data.get("speaker") or {}
        )
        self.last_pickup_controller.load_last_pickup(data.get("last_pickup") or "")
        self.translation_controller.load_conversation_history(data.get("conversation") or [])
        self._screenshots = list(data.get("screenshots") or [])
        for entry in data.get("transcriptions") or []:
            text = entry.get("text", "")
            if not text:
                continue
            append_timestamped_text(
                self.transcription_editor,
                f"[{str(entry.get('source', '')).upper()}] {text}",
                max_lines=MAX_TRANSCRIPTION_LINES,
            )
        logger.info(
            "Session restored: %d bullets, %d transcriptions, %d screenshots",
            len(data.get("bullets") or []),
            len(data.get("transcriptions") or []),
            len(data.get("screenshots") or []),
        )

    def _new_session(self):
        """Archive the current session and start a fresh one (after confirmation)."""
        box = QMessageBox(self)
        box.setWindowTitle("New Session")
        box.setText("Start a new session? The current one will be archived.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if self._screen_protection_enabled:
            set_capture_protection(box, True)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        archived = self.session_store.new_session()
        self.transcription_editor.clear()
        self.translation_controller.clear_conversation_history()
        self.bullet_points_controller.reset()
        self.last_pickup_controller.reset()
        self._screenshots.clear()
        # Empty state resets every webview (gemini/live/bullets).
        self._send_session_state()
        logger.info("New session started (archived=%s)", archived)

    def _on_transcription_update(self, transcription_text, is_final, input_source, endpoint=False):
        # logger.debug("[%s] _on_transcription_update called: is_final=%s, text='%s...', auto_reply_enabled=%s", input_source, is_final, text[:50] if text else '', self._auto_reply_enabled)
        
        # Always send as "transcription" type (original English text)
        # Translation results are sent separately via _on_translation_update
        self.websocket_client.send_transcription(transcription_text, is_final, additional_data={"input_source": input_source}, message_type="transcription")
        
        if is_final:
            # Prefix text with input source label
            labeled_text = f"[{input_source.upper()}] {transcription_text}"
            append_timestamped_text(self.transcription_editor, labeled_text, max_lines=MAX_TRANSCRIPTION_LINES)
            
            self._last_final_transcription = transcription_text
            
            if(transcription_text.strip() != ""):
                self.translation_controller.append_to_history(transcription_text, "", input_source)
                # Always buffered (free); auto mode / the hotkey decide when to call the AI.
                self.bullet_points_controller.add_line(input_source, transcription_text)
                # "Last Picked Up": always buffer the line (host+speaker); a
                # speaker utterance end schedules a refresh when auto is active.
                self.last_pickup_controller.add_line(input_source, transcription_text)
                if input_source != "host":
                    delay = (LAST_PICKUP_ENDPOINT_DEBOUNCE_MS if endpoint
                             else LAST_PICKUP_DEBOUNCE_MS)
                    self.last_pickup_controller.schedule(delay)
                # Persist to the session (async).
                self.session_store.append("transcriptions", {
                    "source": input_source, "text": transcription_text,
                    "timestamp": datetime.now().isoformat(),
                })
                self.session_store.update("conversation", self.translation_controller.get_conversation_history())

            if self._auto_reply_enabled and transcription_text.strip():
                if input_source == "host":
                    logger.debug("[%s] Recording host speech (no auto-reply): %r", input_source, transcription_text)
                elif endpoint:
                    # <end> marks the true end of the utterance (endpoint detection
                    # already waited out the silence), so skip the long debounce.
                    logger.debug("[%s] Endpoint reached; scheduling fast auto-reply", input_source)
                    self.translation_controller.schedule_auto_reply(
                        transcription_text, input_source, delay_ms=AUTO_REPLY_ENDPOINT_DEBOUNCE_MS)
                else:
                    self.translation_controller.schedule_auto_reply(transcription_text, input_source)
            else:
                logger.debug("[%s] NOT scheduling auto-reply. Auto reply: %s, Text empty: %s", input_source, self._auto_reply_enabled, not transcription_text.strip())
        else:
            self.status_label.setText(f"Live [{input_source}]: {transcription_text}" if transcription_text.strip() else "Listening...")
            
            if self._auto_reply_enabled and transcription_text.strip():
                logger.debug("[%s] Canceling auto-reply (non-final text with content received)", input_source)
                self.translation_controller.cancel_auto_reply()
            elif self._auto_reply_enabled and not transcription_text.strip():
                logger.debug("[%s] Ignoring empty non-final text, keeping auto-reply timer active", input_source)
    
    def _on_translation_update(self, text: str, is_final: bool, input_source: str):
        """Handle translation updates from transcription controller (Indonesian translations)."""
        logger.debug("[%s] _on_translation_update called: is_final=%s, text='%s...'", input_source, is_final, text[:50] if text else '')
        
        # Send translation via WebSocket with input_source
        self.websocket_client.send_transcription(text, is_final, additional_data={"input_source": input_source}, message_type="translation")

        if is_final and text.strip():
            self.session_store.append("translations", {
                "source": input_source, "text": text,
                "timestamp": datetime.now().isoformat(),
            })

    def _on_transcription_started(self):
        """Handle transcription session started."""
        self.btn_start.setText("Stop")
    
    def _on_transcription_stopped(self):
        """Handle transcription session stopped."""
        self.btn_start.setChecked(False)
        self._update_start_button_text()
    
    def _on_transcription_error(self, msg: str):
        """Handle transcription errors."""
        self.btn_start.setChecked(False)
        self._update_start_button_text()
        logger.error("%s", msg)

    def _update_status(self, text: str):
        self.status_label.setText(text)
    
    def eventFilter(self, obj, event):
        if obj == self.translation_input and event.type() == QEvent.Type.KeyPress:
            key_event = event
            if key_event.key() == Qt.Key.Key_Return and key_event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self._translate_text()
                return True
        return super().eventFilter(obj, event)
    
    def _translate_text(self):
        text = self.translation_input.toPlainText().strip()
        if not text:
            logger.warning("No text provided to translate.")
            return
        
        target_language = self.gemini_lang_combo.currentText()
        self.translation_controller.translate_text(text, target_language)
    
    def _send_gemini_result(self, text: str, mode: str):
        """Broadcast a formatted Gemini result to the webview."""
        self.websocket_client.send_transcription(
            format_gemini_result(text), True, additional_data={"mode": mode}, message_type="gemini_result"
        )
        self.session_store.append("gemini_results", {
            "text": text, "mode": mode, "timestamp": datetime.now().isoformat(),
        })

    def _send_gemini_stream(self, text: str, mode: str):
        """Broadcast a partial (streaming) Gemini result to the webview."""
        if not text:
            return
        self.websocket_client.send_transcription(
            text, False, additional_data={"mode": mode, "streaming": True}, message_type="gemini_stream"
        )

    def _send_gemini_status(self, status: str, mode: str, text: str = None):
        """Broadcast a Gemini progress/failure status to the webview."""
        additional = {"status": status, "mode": mode}
        if text is not None:
            additional["message"] = text
        self.websocket_client.send_transcription(
            text or "", False, additional_data=additional, message_type="gemini_status"
        )

    def _capture_screenshot(self):
        """Capture the primary screen and append it to the Gemini pane."""
        data_url = capture_screen_data_url()
        if not data_url:
            if not has_permission():
                self._send_gemini_status(
                    "failed",
                    "image",
                    text="Screen Recording permission required — enable it for your "
                    "terminal/IDE in System Settings → Privacy & Security → Screen & "
                    "System Audio Recording, then restart the app.",
                )
            return
        self._screenshots.append(data_url)
        self.websocket_client.send_message({"type": "screenshot", "image": data_url})
        self.session_store.append("screenshots", data_url)
        logger.info("Sent capture (%d bytes)", len(data_url))

    def _clear_screenshots(self):
        """Clear the screenshot gallery in the Gemini pane."""
        self._screenshots.clear()
        self.websocket_client.send_message({"type": "clear_screenshots"})
        logger.info("Clear requested")

    def _send_images_to_gemini(self):
        """Send the captured screenshots to Gemini with the conversation context."""
        if not self._screenshots:
            self._send_gemini_status("failed", "image", text="No screenshots to send.")
            logger.info("No screenshots to send")
            return
        self._send_gemini_status("started", "image")
        self.translation_controller.trigger_image_reply(list(self._screenshots))

    def _on_translation_started(self):
        """Handle manual translation start."""
        self._send_gemini_status("started", "manual")

    def _on_translation_result(self, result: str):
        """Handle translation result."""
        self._send_gemini_result(result, "manual")
    
    def _on_translation_error(self, msg: str):
        """Handle translation errors."""
        if "already in progress" in msg.lower():
            logger.warning("Translation already in progress.")
        elif "auto-reply" not in msg.lower():
            logger.error("%s", msg)
        
        if "auto-reply" not in msg.lower():
            self._send_gemini_status("failed", "manual", text="Translation failed.")
    
    def _on_reply_chunk(self, text: str, is_image: bool):
        """Stream a partial auto-reply/image-reply to the webview."""
        self._send_gemini_stream(text, "image" if is_image else "auto_reply")

    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result."""
        self._send_gemini_result(result, "auto_reply")

    def _on_image_reply_result(self, result: str):
        """Handle the reply to a screenshot sent to Gemini."""
        self._send_gemini_result(result, "image")

    def _regenerate_bullet_points(self):
        """Rebuild the bullet list from the entire session transcript (Rebuild button)."""
        transcriptions = self.session_store.snapshot().get("transcriptions") or []
        lines = [
            (entry.get("source"), entry.get("text"))
            for entry in transcriptions
            if entry.get("text")
        ]
        self.bullet_points_controller.hard_regenerate(lines)

    def _on_bullet_points_updated(self, items: list, speaker: dict):
        """Broadcast the updated bullet list + speaker profile to the webview."""
        self.websocket_client.send_message({
            "type": "bullet_points",
            "items": list(items or []),
            "speaker": dict(speaker or {}),
        })
        self.session_store.set_bullets(items)
        self.session_store.set_speaker(speaker)

    def _send_bullet_status(self, status: str):
        """Broadcast a bullet-points progress/failure status to the webview."""
        self.websocket_client.send_message({"type": "bullet_points_status", "status": status})

    def _send_bullet_countdown(self, auto: bool, next_flush_at: float):
        """Broadcast the auto-flush countdown (pane shows it under the tab title).

        ``next_flush_at`` is an absolute epoch deadline from the controller's
        own QTimer, so the pane's ticking display and the backend timer count
        down from the same instant; ``auto=False`` hides it.
        """
        self.websocket_client.send_message({
            "type": "bullet_points_countdown",
            "auto": bool(auto),
            "next_flush_at": float(next_flush_at or 0.0),
            "interval_ms": BULLET_FLUSH_INTERVAL_MS,
        })

    def _on_last_pickup_updated(self, text: str):
        """Broadcast the latest picked-up topic to the webview and persist it."""
        self.websocket_client.send_message({"type": "last_pickup", "text": text or ""})
        self.session_store.update("last_pickup", text or "")

    def _send_last_pickup_status(self, status: str):
        """Broadcast a last-pickup progress/failure status to the webview."""
        self.websocket_client.send_message({"type": "last_pickup_status", "status": status})

    def _on_last_pickup_error(self, msg: str):
        """Handle last-pickup worker errors (logged, not popped up)."""
        logger.warning("Last pickup error: %s", msg)

    def _send_session_state(self):
        """Send the full session state so webviews can repopulate on connect."""
        payload = {"type": "session_state", **self.session_store.snapshot()}
        # The auto-pickup toggle lives in ui_state (not the session), so include
        # it here so the pane's checkbox reflects the current value on connect.
        payload["last_pickup_auto"] = self._last_pickup_auto_enabled
        self.websocket_client.send_message(payload)
        self._send_purpose_state()
        # A (re)connecting pane has no countdown yet: push the current one so a
        # reload / pane re-show resumes the same number the backend is showing.
        controller = self.bullet_points_controller
        self._send_bullet_countdown(controller.is_auto(), controller.next_flush_at)

    def _send_purpose_state(self):
        """Broadcast the selected Purpose + ``I am:`` role labels to the panes."""
        self.websocket_client.send_message({
            "type": "purpose_state",
            "purpose": self.purpose_combo.currentText(),
            "role": self.host_role_combo.currentText(),
        })

    def _on_bullet_points_error(self, msg: str):
        """Handle bullet-points worker errors (logged, not popped up)."""
        logger.warning("Bullet points error: %s", msg)
    
    def _on_ws_message_raw(self, data: dict):
        """Receive a decoded WebSocket message (runs on the asyncio thread)."""
        self.webview_message.emit(data)

    def _handle_webview_message(self, data: dict):
        """Handle control messages sent from the webview (Qt main thread)."""
        msg_type = data.get("type")
        if msg_type == "request_session_state":
            logger.info("Session state requested from webview")
            self._send_session_state()
        elif msg_type == "auto_reply_toggle":
            self._auto_reply_enabled = bool(data.get("enabled"))
            logger.info("Auto reply set to %s from webview", self._auto_reply_enabled)
        elif msg_type == "auto_reply_request":
            logger.info("Auto-reply requested from webview")
            self._manual_reply()
        elif msg_type == "hide_gemini_window":
            logger.info("Hide requested from Gemini window")
            # Unchecking routes through _set_gemini_window_visible(False) -> hide()
            # and keeps the menu item in sync with the pane's visibility.
            self.gemini_window_action.setChecked(False)
        elif msg_type == "hide_live_window":
            logger.info("Hide requested from Live window")
            # Unchecking routes through _set_live_window_visible(False) -> hide()
            # and keeps the menu item in sync with the pane's visibility.
            self.live_window_action.setChecked(False)
        elif msg_type == "set_gemini_window_edge":
            logger.info("Gemini window edge -> %s", data.get('edge'))
            self._set_pane_edge(self.gemini_window, data.get("edge"))
        elif msg_type == "set_live_window_edge":
            logger.info("Live window edge -> %s", data.get('edge'))
            self._set_pane_edge(self.live_window, data.get("edge"))
        elif msg_type == "hide_bullet_points_window":
            logger.info("Hide requested from Bullet Points window")
            # Unchecking pauses generation and hides the pane (checkpoint kept).
            self.bullet_points_window_action.setChecked(False)
        elif msg_type == "set_bullet_points_window_edge":
            logger.info("Bullet Points window edge -> %s", data.get('edge'))
            self._set_pane_edge(self.bullet_points_window, data.get("edge"))
        elif msg_type == "regenerate_bullet_points":
            logger.info("Bullet points rebuild requested from webview")
            self._regenerate_bullet_points()
        elif msg_type == "set_last_pickup_auto":
            logger.info("Last pickup auto -> %s", data.get("enabled"))
            self._last_pickup_auto_enabled = bool(data.get("enabled"))
            self._update_last_pickup_auto()
            self._save_state()

    def _manual_reply(self):
        """Manually trigger a Gemini reply using the last final transcription (Ctrl+R / Cmd+R)."""
        text = self._last_final_transcription.strip()
        if not text:
            text = self.transcription_editor.toPlainText().strip()
        if not text:
            logger.warning("No transcription available to reply to.")
            return
        self.translation_controller.trigger_reply_now(text, "speaker")
    
    def _on_auto_reply_language_changed(self, language: str):
        """Update auto-reply target language when combo box changes."""
        self.translation_controller.set_auto_reply_language(language)

    def _on_purpose_changed(self, index: int):
        """Update the auto-reply purpose, its roles, and default pronunciation."""
        key = self.purpose_combo.currentData()
        if not key:
            return
        self.translation_controller.set_auto_reply_purpose(key)
        purpose = self.purpose_store.get(key)
        if purpose is not None:
            self.pronunciation_checkbox.setChecked(purpose.get("include_pronunciation_default", False))
        self._refresh_host_roles(key)
        self._send_purpose_state()

    def _refresh_host_roles(self, purpose_key):
        """Repopulate the ``I am:`` combo for a purpose and apply its role."""
        if not purpose_key:
            return
        roles = self.purpose_store.roles(purpose_key)
        remembered = self._host_role_by_purpose.get(purpose_key, "smart")
        self.settings_view.populate_host_roles(roles, remembered)
        role = self.host_role_combo.currentData() or "smart"
        self._host_role_by_purpose[purpose_key] = role
        self.translation_controller.set_host_role(role)

    def _on_host_role_changed(self, index: int):
        """Persist the chosen ``I am:`` role and push it to the controller."""
        key = self.purpose_combo.currentData()
        role = self.host_role_combo.currentData() or "smart"
        if key:
            self._host_role_by_purpose[key] = role
        self.translation_controller.set_host_role(role)
        self._send_purpose_state()
        self._save_state()

    def _on_smart_decision_toggled(self, checked: bool):
        """Enable/disable the JEV decision gate and persist the choice."""
        self.translation_controller.set_jev_enabled(checked)
        self._save_state()

    def _on_purpose_added(self, key: str):
        """Insert an AI-learned purpose into the dropdown without changing selection."""
        if not key or self.purpose_combo.findData(key) >= 0:
            return
        purpose = self.purpose_store.get(key)
        self.purpose_combo.addItem(purpose.get("label", key), key)
        logger.info("Purpose added to dropdown: %s", purpose.get("label", key))

    def _on_reply_skipped(self, reason: str):
        """JEV chose not to reply: tell the pane, persist nothing."""
        self._send_gemini_status("skipped", "auto_reply", text=reason or "No reply needed")

    def _on_devices_populated(self, host_list: list, host_ids: list, speaker_list: list, speaker_items: list):
        """Handle devices populated from controller."""
        self.device_combo.clear()
        for label, dev_id in zip(host_list, host_ids):
            self.device_combo.addItem(label, dev_id)

        self.speaker_combo.clear()
        for label, item in zip(speaker_list, speaker_items):
            self.speaker_combo.addItem(label, item)

        default_host = self.device_controller.get_default_host_id()
        if default_host in host_ids:
            self.device_combo.setCurrentIndex(host_ids.index(default_host))

        default_speaker = self.device_controller.get_default_speaker_index()
        if default_speaker is not None:
            self.speaker_combo.setCurrentIndex(default_speaker)

        if not speaker_list:
            self.status_label.setText(self.device_controller.missing_speaker_message())
    
    def _on_device_error(self, msg: str):
        """Handle device errors."""
        logger.warning("Device error: %s", msg)

    def _update_memory_usage(self):
        """Update memory usage indicator."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            mem_mb = mem_info.rss / 1024 / 1024
            
            trans_lines = self.transcription_editor.document().blockCount()
            
            self.memory_label.setText(f"Memory: {mem_mb:.1f} MB | Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except ImportError:
            trans_lines = self.transcription_editor.document().blockCount()
            self.memory_label.setText(f"Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except Exception:
            pass
    
    def _set_gemini_window_visible(self, visible):
        """Show or hide the separate AI suggestion pane."""
        if visible:
            self.gemini_window._apply_geometry()
            self.gemini_window.showNormal()  # also restores if minimized
            self.gemini_window.raise_()
        else:
            self.gemini_window.hide()

    def _set_live_window_visible(self, visible):
        """Show or hide the separate live-view pane."""
        if visible:
            self.live_window._apply_geometry()
            self.live_window.showNormal()  # also restores if minimized
            self.live_window.raise_()
        else:
            self.live_window.hide()

    def _on_bullet_points_toggled(self, enabled):
        """Toggle auto updates. Enabling also shows the pane; disabling leaves it."""
        if enabled:
            self.bullet_points_window_action.setChecked(True)
        self._update_bullet_points_auto()

    def _set_bullet_points_window_visible(self, visible):
        """Show or hide the bullet-points pane. Hiding pauses auto updates."""
        if visible:
            self.bullet_points_window._apply_geometry()
            self.bullet_points_window.showNormal()  # also restores if minimized
            self.bullet_points_window.raise_()
        else:
            self.bullet_points_window.hide()
        self._update_bullet_points_auto()
        self._update_last_pickup_auto()

    def _toggle_all_panes(self):
        """CTRL+SHIFT+M (Cmd+Shift+M on macOS): hide all open panes, or restore
        exactly the set that was open before they were hidden.

        The Tool ▾ checkable actions are the single source of truth, so driving
        them routes each change through the normal show/hide setters (keeping the
        menu in sync and pausing/resuming bullet-point auto-updates).
        """
        panes = (
            ("gemini", self.gemini_window_action),
            ("live", self.live_window_action),
            ("bullet_points", self.bullet_points_window_action),
        )
        if not self._all_panes_hidden:
            self._panes_visibility_before_hide = {
                name: action.isChecked() for name, action in panes
            }
            for _name, action in panes:
                action.setChecked(False)
            self._all_panes_hidden = True
            open_names = [name for name, is_open in self._panes_visibility_before_hide.items() if is_open]
            logger.info("Hotkey: hid all panes (was open: %s)", open_names or "none")
        else:
            for name, action in panes:
                action.setChecked(self._panes_visibility_before_hide.get(name, False))
            self._all_panes_hidden = False
            open_names = [name for name, is_open in self._panes_visibility_before_hide.items() if is_open]
            logger.info("Hotkey: restored panes (%s)", open_names or "none")

    def _update_bullet_points_auto(self):
        """Auto updates run only when the feature is enabled AND the pane is shown."""
        auto = (self.bullet_points_checkbox.isChecked()
                and self.bullet_points_window_action.isChecked())
        self.bullet_points_controller.set_auto(auto)

    def _update_last_pickup_auto(self):
        """Auto pickup runs only when the pane toggle is on AND the pane is shown."""
        auto = (self._last_pickup_auto_enabled
                and self.bullet_points_window_action.isChecked())
        self.last_pickup_controller.set_auto(auto)

    def _trigger_bullet_points_now(self):
        """CTRL+ALT+P: update the list on demand (silent; only when the pane is shown)."""
        if not self.bullet_points_window_action.isChecked():
            logger.info("Bullet points pane hidden; CTRL+ALT+P ignored")
            return
        logger.info("Bullet points manual update requested")
        self.bullet_points_controller.flush_now(force=True)

    def _set_pane_edge(self, window, edge):
        """Dock a pane to ``edge``, moving any docked pane on that edge to the opposite side."""
        if edge not in ("left", "right"):
            return
        # A same-edge pane that is already docked needs no change; a same-edge
        # floating pane still re-docks to that edge.
        if window.get_edge() == edge and window.is_docked():
            return
        opposite = "left" if edge == "right" else "right"
        for other in (self.gemini_window, self.live_window, self.bullet_points_window):
            if other is window:
                continue
            if other.is_docked() and other.get_edge() == edge:
                other.set_edge(opposite)
        window.set_edge(edge)

    def _set_always_on_top(self, enabled):
        """Keep the bar above other windows (mirrors the panes' top-most flag)."""
        enabled = bool(enabled)
        if self._always_on_top == enabled:
            return
        self._always_on_top = enabled
        # Changing window flags on a visible window hides it, so re-show and
        # re-raise; showEvent re-snaps the bar and re-applies capture protection.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.show()
        self.raise_()
        self.activateWindow()
        # macOS: re-assert the native window level (setting flags recreates the
        # NSWindow). No-op elsewhere.
        set_always_on_top(self, enabled)
        # The toggle governs the panes too, so they stay on top together.
        self.gemini_window.apply_always_on_top(enabled)
        self.live_window.apply_always_on_top(enabled)
        self.bullet_points_window.apply_always_on_top(enabled)
        self._save_state()

    def _set_screen_protection(self, enabled):
        """Exclude this window from screen capture and mirror the state on both controls."""
        enabled = bool(enabled)
        self._screen_protection_enabled = enabled
        set_capture_protection(self, enabled)
        self.gemini_window.apply_screen_protection(enabled)
        self.live_window.apply_screen_protection(enabled)
        self.bullet_points_window.apply_screen_protection(enabled)
        if hasattr(self, "settings_dialog"):
            set_capture_protection(self.settings_dialog, enabled)
        for widget in (self.screen_protection_action, self.screen_protection_checkbox):
            if widget.isChecked() != enabled:
                widget.setChecked(enabled)

    def showEvent(self, event):
        super().showEvent(event)
        # Re-apply the bar's geometry after the first real show (and re-shows),
        # re-clamping a stored position onto the current screen.
        QTimer.singleShot(0, self._apply_bar_geometry)
        # Changing window flags / re-showing can reset both the capture
        # exclusion and the native (macOS) window level, so re-apply on show.
        set_always_on_top(self, self._always_on_top)
        if self._screen_protection_enabled:
            set_capture_protection(self, True)

    def closeEvent(self, event):
        """Clean up resources on window close."""
        try:
            self._memory_monitor_timer.stop()

            # Release the global hotkeys
            self.hotkeys.unregister()

            # Persist the pane layout and Settings, then close the panes and settings dialog
            self._save_state()
            # Flush + stop the async session writer.
            self.session_store.close()
            # Flush + stop the async purpose writer (AI-learned personas are global).
            self.purpose_store.close()
            self.settings_dialog.close()
            self.gemini_window.close()
            self.live_window.close()
            self.bullet_points_window.close()

            # Stop transcription first to stop audio streams
            self.transcription_controller.cleanup()
            
            # Stop translation
            self.translation_controller.cleanup()

            # Stop the bullet-points worker/timer
            self.bullet_points_controller.cleanup()

            # Stop the last-pickup worker/timer
            self.last_pickup_controller.cleanup()
            
            # Stop websocket
            self.websocket_client.stop()

            # Stop the web service if this app started it
            self._server_manager.stop()
            
            # Give threads time to finish
            from PySide6.QtCore import QThread
            QThread.msleep(500)
            
        except Exception as e:
            logger.error("Error during cleanup: %s", e)
        
        event.accept()
        return super().closeEvent(event)
