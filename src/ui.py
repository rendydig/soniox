import sys
import os
import logging
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QDialog, QMenu, QToolButton, QPushButton)
from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QActionGroup, QGuiApplication
from src.config import MAX_TRANSCRIPTION_LINES
from src.purposes import PURPOSES
from src.text_formatter import append_timestamped_text, format_gemini_result
from src.screen_protection import set_capture_protection
from src.screenshot import capture_screen_data_url
from src.global_hotkeys import GlobalHotkeys
from src.controllers import (
    DeviceController,
    TranscriptionController,
    TranslationController
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
    LiveWindow
)
from src.ui_components.pane_resize_handle import PaneResizeHandle
from src.ui_state import load_state, save_state

logger = logging.getLogger(__name__)

# Default width of the bottom bar. It is fixed (not derived from the panes) and
# user-resizable; the narrowest it can shrink to is the trimmed content minimum.
BAR_WIDTH = 560
MIN_BAR_WIDTH = 540
# Height of the bottom bar's always-visible control row (window frame included).
# The manual-translation input row is revealed above it, growing the bar upward.
BAR_HEIGHT = 60
INPUT_ROW_HEIGHT = 40


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
        self.transcription_controller = TranscriptionController()
        self.translation_controller = TranslationController()
        
        # Bring up the Node web service (port 8765) before connecting / loading
        # the Gemini pane, so both the client and the webview have a server.
        self._server_manager = WebSocketServerManager()
        self._server_manager.ensure_running()

        self.websocket_client = WebSocketClient("ws://localhost:8765")
        self.websocket_client.set_message_handler(self._on_ws_message_raw)
        self.websocket_client.start()

        # System-wide hotkeys: ALT+SHIFT+K captures a screenshot, ALT+CTRL+SHIFT+K
        # clears the ones shown in the Gemini pane, and CTRL+ALT+SHIFT+G sends the
        # captured screenshots to Gemini.
        self.hotkeys = GlobalHotkeys(
            on_screenshot=self._capture_screenshot,
            on_clear=self._clear_screenshots,
            on_send_image=self._send_images_to_gemini,
        )
        self.hotkeys.register()
        
        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._update_memory_usage)
        self._memory_monitor_timer.start(5000)
        
        self._last_final_transcription = ""
        self._screenshots = []
        self._screen_protection_enabled = True
        self._auto_reply_enabled = False

        # Separate top-level panes (not Qt children of this window). Their
        # geometry is restored from ui_state.json (written back on change).
        state = load_state()
        main_state = _as_dict(state.get("main_window"))
        gemini_state = _as_dict(state.get("gemini_window"))
        live_state = _as_dict(state.get("live_window"))
        settings_state = _as_dict(state.get("settings"))
        self._always_on_top = bool(main_state.get("always_on_top", True))
        # Bar geometry: fixed default width, bottom-center unless the user moved it.
        self._bar_width = self._clamp_bar_width(main_state.get("width"))
        self._bar_x = main_state.get("x")
        self._bar_y = main_state.get("y")
        self.gemini_window = GeminiWindow(
            edge=gemini_state.get("edge"), width=gemini_state.get("width"),
            height=gemini_state.get("height"), x=gemini_state.get("x"),
            y=gemini_state.get("y"), docked=gemini_state.get("docked"),
        )
        self.live_window = LiveWindow(
            edge=live_state.get("edge"), width=live_state.get("width"),
            height=live_state.get("height"), x=live_state.get("x"),
            y=live_state.get("y"), docked=live_state.get("docked"),
        )

        self._init_menu()
        self._init_ui()
        self._setup_controller_connections()
        self._connect_pane_signals()
        self._apply_settings_state(settings_state)
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
        self.settings_view = SettingsViewWidget()
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
        return max(MIN_BAR_WIDTH, min(width, max_width))

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
        for pane in (self.gemini_window, self.live_window):
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
            "settings": {
                "view_mode": self.view_mode_combo.currentIndex(),
                "ai_reply_language": self.gemini_lang_combo.currentText(),
                "purpose": self.purpose_combo.currentData(),
                "pronunciation": self.pronunciation_checkbox.isChecked(),
                "screen_protection": self.screen_protection_checkbox.isChecked(),
            },
        })

    def _apply_settings_state(self, state):
        """Restore persisted Settings onto the widgets (falls back to defaults)."""
        view_mode = state.get("view_mode")
        if isinstance(view_mode, int) and 0 <= view_mode < self.view_mode_combo.count():
            self.view_mode_combo.setCurrentIndex(view_mode)

        language = state.get("ai_reply_language")
        if language:
            index = self.gemini_lang_combo.findText(language)
            if index >= 0:
                self.gemini_lang_combo.setCurrentIndex(index)

        # Purpose first: _on_purpose_changed resets pronunciation to its default.
        purpose = state.get("purpose")
        if purpose:
            index = self.purpose_combo.findData(purpose)
            if index >= 0:
                self.purpose_combo.setCurrentIndex(index)

        pronunciation = state.get("pronunciation")
        if isinstance(pronunciation, bool):
            self.pronunciation_checkbox.setChecked(pronunciation)

        screen_protection = state.get("screen_protection")
        if isinstance(screen_protection, bool):
            self._set_screen_protection(screen_protection)

    def _connect_settings_signals(self):
        """Persist Settings whenever one of them changes."""
        self.view_mode_combo.currentIndexChanged.connect(self._save_state)
        self.gemini_lang_combo.currentTextChanged.connect(self._save_state)
        self.purpose_combo.currentIndexChanged.connect(self._save_state)
        self.pronunciation_checkbox.toggled.connect(self._save_state)
        self.screen_protection_checkbox.toggled.connect(self._save_state)

    def _connect_screen_signals(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_available_geometry_changed)

    def _on_available_geometry_changed(self, _rect):
        """Re-clamp the bar when the taskbar is shown/hidden/resized."""
        self._apply_bar_geometry()

    def _open_settings(self):
        """Show the separate Settings dialog, honouring screen protection."""
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
        self.mode_button.setText("Mode")
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
        self.gemini_window_action.setToolTip("Show or hide the Gemini suggestion pane.")
        self.gemini_window_action.toggled.connect(self._set_gemini_window_visible)
        self.tool_menu.addAction(self.gemini_window_action)

        self.live_window_action = QAction("Live Window", self)
        self.live_window_action.setCheckable(True)
        self.live_window_action.setChecked(True)
        self.live_window_action.setToolTip("Show or hide the live view pane.")
        self.live_window_action.toggled.connect(self._set_live_window_visible)
        self.tool_menu.addAction(self.live_window_action)

        self.always_on_top_action = QAction("Always on Top", self)
        self.always_on_top_action.setCheckable(True)
        self.always_on_top_action.setChecked(self._always_on_top)
        self.always_on_top_action.setToolTip("Keep the control bar above other windows.")
        self.always_on_top_action.toggled.connect(self._set_always_on_top)
        self.tool_menu.addAction(self.always_on_top_action)

        # Applied before the window is shown, so no hide/re-show churn.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)

        self.tool_button = QToolButton()
        self.tool_button.setText("Tool")
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
        self.screen_protection_checkbox = self.settings_view.get_screen_protection_checkbox()
        
        self.gemini_lang_combo = self.settings_view.get_gemini_lang_combo()
        self.translation_input = self.translation_section.get_translation_input()
        
        self.btn_start = self.control_buttons.get_start_button()
        
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
        self.pronunciation_checkbox.toggled.connect(self.translation_controller.set_pronunciation_enabled)
        self.translation_controller.set_pronunciation_enabled(self.pronunciation_checkbox.isChecked())
        self.purpose_combo.currentIndexChanged.connect(self._on_purpose_changed)
        self.screen_protection_checkbox.toggled.connect(self._set_screen_protection)
        
        reply_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        reply_shortcut.activated.connect(self._manual_reply)
    
    def _apply_styles(self):
        self.setStyleSheet(
            """
            QWidget { font-size: 13px; }
            QComboBox, QLineEdit { padding: 4px 6px; }
            QPushButton, QToolButton { padding: 3px 8px; }
            QPushButton:checked { background-color: #d9534f; color: white; }
            QTextEdit { font-family: 'Menlo', 'Monaco', 'Courier New', monospace; font-size: 13px; }
            """
        )
    
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

        self.transcription_editor.clear()
        self.translation_controller.clear_conversation_history()
        self.transcription_controller.start_session(host_device_id, speaker_device, mode=mode, target_lang=target_lang)

    def _stop_session(self):
        self.status_label.setText("Stopping...")
        
        self.translation_controller.cancel_auto_reply()
        self.transcription_controller.stop_session()

    def _on_transcription_update(self, transcription_text, is_final, input_source):
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

            if self._auto_reply_enabled and transcription_text.strip():
                if input_source == "host":
                    logger.debug("[%s] Recording host speech (no auto-reply): %r", input_source, transcription_text)
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
            format_gemini_result(text), True,
            additional_data={"mode": mode}, message_type="gemini_result"
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
            return
        self._screenshots.append(data_url)
        self.websocket_client.send_message({"type": "screenshot", "image": data_url})
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
    
    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result."""
        self._send_gemini_result(result, "auto_reply")

    def _on_image_reply_result(self, result: str):
        """Handle the reply to a screenshot sent to Gemini."""
        self._send_gemini_result(result, "image")
    
    def _on_ws_message_raw(self, data: dict):
        """Receive a decoded WebSocket message (runs on the asyncio thread)."""
        self.webview_message.emit(data)

    def _handle_webview_message(self, data: dict):
        """Handle control messages sent from the webview (Qt main thread)."""
        msg_type = data.get("type")
        if msg_type == "auto_reply_toggle":
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
        """Update the auto-reply purpose and apply its default pronunciation setting."""
        key = self.purpose_combo.currentData()
        self.translation_controller.set_auto_reply_purpose(key)
        purpose = PURPOSES.get(key)
        if purpose is not None:
            self.pronunciation_checkbox.setChecked(purpose.get("include_pronunciation_default", False))

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
            self.status_label.setText("No loopback output device found")
    
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
        """Show or hide the separate Gemini suggestion pane."""
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

    def _set_pane_edge(self, window, edge):
        """Dock a pane to ``edge``, swapping the other docked pane to the opposite side."""
        if edge not in ("left", "right"):
            return
        # A same-edge pane that is already docked needs no change; a same-edge
        # floating pane still re-docks to that edge.
        if window.get_edge() == edge and window.is_docked():
            return
        other = self.live_window if window is self.gemini_window else self.gemini_window
        if other.is_docked() and other.get_edge() == edge:
            other.set_edge("left" if edge == "right" else "right")
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
        self._save_state()

    def _set_screen_protection(self, enabled):
        """Exclude this window from screen capture and mirror the state on both controls."""
        enabled = bool(enabled)
        self._screen_protection_enabled = enabled
        set_capture_protection(self, enabled)
        self.gemini_window.apply_screen_protection(enabled)
        self.live_window.apply_screen_protection(enabled)
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
        # Changing window flags / re-showing resets the display affinity,
        # so re-apply it whenever the window becomes visible.
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
            self.settings_dialog.close()
            self.gemini_window.close()
            self.live_window.close()

            # Stop transcription first to stop audio streams
            self.transcription_controller.cleanup()
            
            # Stop translation
            self.translation_controller.cleanup()
            
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
