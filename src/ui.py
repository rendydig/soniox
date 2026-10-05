import sys
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QMessageBox, QDialog, QMenu, QToolButton, QPushButton)
from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QActionGroup, QGuiApplication
from src.config import MAX_TRANSCRIPTION_LINES
from src.purposes import PURPOSES
from src.text_formatter import append_timestamped_text, format_gemini_result
from src.screen_protection import set_capture_protection
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
from src.ui_components.live_window import LIVE_WINDOW_WIDTH
from src.ui_components.gemini_window import GEMINI_WINDOW_WIDTH

# Height of the bottom bar's always-visible control row (window frame included).
# The manual-translation input row is revealed above it, growing the bar upward.
BAR_HEIGHT = 60
INPUT_ROW_HEIGHT = 40


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
        
        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._update_memory_usage)
        self._memory_monitor_timer.start(5000)
        
        self._last_final_transcription = ""
        self._screen_protection_enabled = True
        self._auto_reply_enabled = False

        # Separate top-level panes (not Qt children of this window).
        self.gemini_window = GeminiWindow()
        self.live_window = LiveWindow()

        self._init_menu()
        self._init_ui()
        self._setup_controller_connections()
        self.device_controller.populate_devices()
        self._snap_to_bottom()
        self._connect_screen_signals()
        self.gemini_window.show()
        self.live_window.show()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(6)

        # Top row: manual translation input, revealed by the toggle (hidden by
        # default) which grows the bar upward.
        self.translation_section = TranslationSectionWidget()
        self.translation_section.setVisible(False)
        root.addWidget(self.translation_section)

        # Bottom row: always-visible controls, mode/tool menus, status, close.
        row = QHBoxLayout()
        row.setSpacing(8)

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

        # Settings lives in its own dialog. Created eagerly (hidden) so the
        # widget getters in _setup_widget_references stay valid.
        self.settings_view = SettingsViewWidget()
        self.settings_dialog = QDialog()
        self.settings_dialog.setWindowTitle("Settings")
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

    def _snap_to_bottom(self):
        """Pin the bar between the two side panes, just above the taskbar.

        ``availableGeometry`` already excludes the taskbar (and any other reserved
        app bars), so no taskbar measurement is needed. The bar spans the middle
        of the screen: ``screen width - Live pane - Gemini pane``, starting right
        after the Live pane on the left.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()

        width = max(avail.width() - LIVE_WINDOW_WIDTH - GEMINI_WINDOW_WIDTH, 1)
        height = self._current_bar_height()
        self.resize(width, height)
        # The window is frameless, so move() positions the visible top-left.
        self.move(avail.left() + LIVE_WINDOW_WIDTH, avail.bottom() + 1 - height)

    def _on_manual_switch_toggled(self, checked):
        """Show/hide the input row, growing or shrinking upward from the bottom."""
        self.translation_section.setVisible(checked)
        bottom = self.frameGeometry().bottom()
        height = self._current_bar_height()
        self.resize(self.width(), height)
        self.move(self.x(), bottom + 1 - height)

    def _connect_screen_signals(self):
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_available_geometry_changed)

    def _on_available_geometry_changed(self, _rect):
        """Re-snap when the taskbar is shown/hidden/resized or the screen changes."""
        self._snap_to_bottom()

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
        self.mode_button.setText("Transcription")
        self.mode_button.setToolTip("Switch between Live Transcription and Live Translation.")
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
        self.mode_status_label = self.status_bar.get_mode_label()
        self.memory_label = self.status_bar.get_memory_label()
    
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
            QPushButton, QToolButton { padding: 4px 10px; }
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
        
        self.gemini_lang_combo.currentTextChanged.connect(self._on_auto_reply_language_changed)

        # WebSocket messages arrive on the asyncio thread; hop to the Qt thread.
        self.webview_message.connect(self._handle_webview_message, Qt.ConnectionType.QueuedConnection)

    def _on_mode_changed(self, mode):
        is_translation = (mode == "translation")
        self.lang_selection.setVisible(is_translation)
        label = "Translation" if is_translation else "Transcription"
        self.mode_button.setText(label)
        self.mode_status_label.setText(label)
        self._update_start_button_text()

    def _update_start_button_text(self):
        """Set the start button label from the current mode (unless a session is running)."""
        if self.btn_start.isChecked():
            return
        self.btn_start.setText("Start Translation" if self.act_translate.isChecked() else "Start Transcription")

    def _toggle_start(self, checked):
        if checked:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        host_device_id = self.device_combo.currentData()
        if host_device_id is None:
            QMessageBox.warning(self, "No Device", "Please select a host input device.")
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
        # print(f"[DEBUG] [{input_source}] _on_transcription_update called: is_final={is_final}, text='{text[:50] if text else ''}...', auto_reply_enabled={self._auto_reply_enabled}")
        
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
                    print(f"[DEBUG] [{input_source}] Recording host speech (no auto-reply): '{transcription_text}'")
                else:
                    self.translation_controller.schedule_auto_reply(transcription_text, input_source)
            else:
                print(f"[DEBUG] [{input_source}] NOT scheduling auto-reply. Auto reply: {self._auto_reply_enabled}, Text empty: {not transcription_text.strip()}")
        else:
            self.status_label.setText(f"Live [{input_source}]: {transcription_text}" if transcription_text.strip() else "Listening...")
            
            if self._auto_reply_enabled and transcription_text.strip():
                print(f"[DEBUG] [{input_source}] Canceling auto-reply (non-final text with content received)")
                self.translation_controller.cancel_auto_reply()
            elif self._auto_reply_enabled and not transcription_text.strip():
                print(f"[DEBUG] [{input_source}] Ignoring empty non-final text, keeping auto-reply timer active")
    
    def _on_translation_update(self, text: str, is_final: bool, input_source: str):
        """Handle translation updates from transcription controller (Indonesian translations)."""
        print(f"[DEBUG] [{input_source}] _on_translation_update called: is_final={is_final}, text='{text[:50] if text else ''}...'")
        
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
        QMessageBox.critical(self, "Error", msg)

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
            QMessageBox.warning(self, "No Text", "Please enter text to translate.")
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

    def _on_translation_started(self):
        """Handle manual translation start."""
        self._send_gemini_status("started", "manual")

    def _on_translation_result(self, result: str):
        """Handle translation result."""
        self._send_gemini_result(result, "manual")
    
    def _on_translation_error(self, msg: str):
        """Handle translation errors."""
        if "already in progress" in msg.lower():
            QMessageBox.warning(self, "Translation in Progress", "Please wait for the current translation to complete.")
        elif "auto-reply" not in msg.lower():
            QMessageBox.critical(self, "Translation Error", msg)
        
        if "auto-reply" not in msg.lower():
            self._send_gemini_status("failed", "manual", text="Translation failed.")
    
    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result."""
        self._send_gemini_result(result, "auto_reply")
    
    def _on_ws_message_raw(self, data: dict):
        """Receive a decoded WebSocket message (runs on the asyncio thread)."""
        self.webview_message.emit(data)

    def _handle_webview_message(self, data: dict):
        """Handle control messages sent from the webview (Qt main thread)."""
        msg_type = data.get("type")
        if msg_type == "auto_reply_toggle":
            self._auto_reply_enabled = bool(data.get("enabled"))
            print(f"[WebSocket] Auto reply set to {self._auto_reply_enabled} from webview")
        elif msg_type == "auto_reply_request":
            print("[WebSocket] Auto-reply requested from webview")
            self._manual_reply()
        elif msg_type == "hide_gemini_window":
            print("[WebSocket] Hide requested from Gemini window")
            # Unchecking routes through _set_gemini_window_visible(False) -> hide()
            # and keeps the menu item in sync with the pane's visibility.
            self.gemini_window_action.setChecked(False)
        elif msg_type == "hide_live_window":
            print("[WebSocket] Hide requested from Live window")
            # Unchecking routes through _set_live_window_visible(False) -> hide()
            # and keeps the menu item in sync with the pane's visibility.
            self.live_window_action.setChecked(False)

    def _manual_reply(self):
        """Manually trigger a Gemini reply using the last final transcription (Ctrl+R / Cmd+R)."""
        text = self._last_final_transcription.strip()
        if not text:
            text = self.transcription_editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No Transcription", "No transcription available to reply to.")
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
        QMessageBox.warning(self, "Device Error", msg)

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
            self.gemini_window._position_on_screen()
            self.gemini_window.showNormal()  # also restores if minimized
            self.gemini_window.raise_()
        else:
            self.gemini_window.hide()

    def _set_live_window_visible(self, visible):
        """Show or hide the separate live-view pane."""
        if visible:
            self.live_window._position_on_screen()
            self.live_window.showNormal()  # also restores if minimized
            self.live_window.raise_()
        else:
            self.live_window.hide()

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
        # The frame metrics are only valid once shown, so re-snap the bar to the
        # bottom edge after the first real show (and after re-shows).
        QTimer.singleShot(0, self._snap_to_bottom)
        # Changing window flags / re-showing resets the display affinity,
        # so re-apply it whenever the window becomes visible.
        if self._screen_protection_enabled:
            set_capture_protection(self, True)

    def closeEvent(self, event):
        """Clean up resources on window close."""
        try:
            self._memory_monitor_timer.stop()

            # Close the separate panes and the settings dialog
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
            print(f"[Cleanup] Error during cleanup: {e}")
        
        event.accept()
        return super().closeEvent(event)
