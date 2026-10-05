import sys
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                             QMessageBox, QStackedWidget)
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QActionGroup
from src.config import MAX_TRANSCRIPTION_LINES, MAX_GEMINI_LINES
from src.purposes import PURPOSES
from src.text_formatter import append_timestamped_text, format_gemini_result
from src.screen_protection import set_capture_protection
from src.controllers import (
    DeviceController,
    TranscriptionController,
    TranslationController
)
from src.websocket_client import WebSocketClient
from src.ui_components import (
    SettingsViewWidget,
    TextEditorsWidget,
    TranslationSectionWidget,
    ControlButtonsWidget,
    StatusBarWidget
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soniox AI: Transcribe & Translate")
        self.resize(800, 600)
        
        self.device_controller = DeviceController()
        self.transcription_controller = TranscriptionController()
        self.translation_controller = TranslationController()
        
        self.websocket_client = WebSocketClient("ws://localhost:8765")
        self.websocket_client.start()
        
        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._update_memory_usage)
        self._memory_monitor_timer.start(5000)
        
        self._last_final_transcription = ""
        self._screen_protection_enabled = True
        
        self._init_ui()
        self._init_menu()
        self._setup_controller_connections()
        self.device_controller.populate_devices()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.view_stack = QStackedWidget()
        layout.addWidget(self.view_stack)

        # Main view: transcription output and session controls.
        self.main_view = QWidget()
        main_layout = QVBoxLayout(self.main_view)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(12)

        self.text_editors = TextEditorsWidget()
        main_layout.addWidget(self.text_editors)

        self.translation_section = TranslationSectionWidget()
        main_layout.addWidget(self.translation_section)

        self.control_buttons = ControlButtonsWidget()
        main_layout.addWidget(self.control_buttons)

        self.status_bar = StatusBarWidget()
        main_layout.addWidget(self.status_bar)

        # Settings view: devices, languages, and session options.
        self.settings_view = SettingsViewWidget()
        self.settings_view.back_requested.connect(self._show_main_view)

        self.view_stack.addWidget(self.main_view)
        self.view_stack.addWidget(self.settings_view)

        self._setup_widget_references()
        self._setup_widget_connections()
        self._apply_styles()

    def _on_settings_toggled(self, checked):
        self.view_stack.setCurrentWidget(self.settings_view if checked else self.main_view)

    def _show_main_view(self):
        self.settings_action.setChecked(False)

    def _init_menu(self):
        self.mode_menu = self.menuBar().addMenu("Mode: Live Transcription")

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

        tool_menu = self.menuBar().addMenu("Tool")
        self.screen_protection_action = QAction("Screen Protection", self)
        self.screen_protection_action.setCheckable(True)
        self.screen_protection_action.setChecked(True)
        self.screen_protection_action.toggled.connect(self._set_screen_protection)
        tool_menu.addAction(self.screen_protection_action)

        self.settings_action = QAction("Settings", self)
        self.settings_action.setCheckable(True)
        self.settings_action.toggled.connect(self._on_settings_toggled)
        self.menuBar().addAction(self.settings_action)
    
    def _setup_widget_references(self):
        self.device_combo = self.settings_view.get_device_combo()
        self.speaker_combo = self.settings_view.get_speaker_combo()
        
        self.lang_selection = self.settings_view.get_language_selection()
        self.lang_combo = self.lang_selection.get_lang_combo()
        
        self.transcription_editor = self.text_editors.get_transcription_editor()
        self.gemini_text = self.text_editors.get_gemini_text()
        self.auto_reply_checkbox = self.text_editors.get_auto_reply_checkbox()
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
            QWidget { font-size: 14px; }
            QComboBox, QLineEdit { padding: 6px; }
            QPushButton { padding: 10px 16px; }
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
        self.translation_controller.translation_started.connect(lambda: self.gemini_text.setText("Translating..."))
        self.translation_controller.auto_reply_result.connect(self._on_auto_reply_result)
        
        self.gemini_lang_combo.currentTextChanged.connect(self._on_auto_reply_language_changed)

    def _on_mode_changed(self, mode):
        is_translation = (mode == "translation")
        self.lang_selection.setVisible(is_translation)
        self.mode_menu.setTitle("Mode: Live Translation" if is_translation else "Mode: Live Transcription")
        self.mode_status_label.setText("Mode: Live Translation" if is_translation else "Mode: Live Transcription")
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
        # print(f"[DEBUG] [{input_source}] _on_transcription_update called: is_final={is_final}, text='{text[:50] if text else ''}...', checkbox_checked={self.auto_reply_checkbox.isChecked()}")
        
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

            if self.auto_reply_checkbox.isChecked() and transcription_text.strip():
                if input_source == "host":
                    print(f"[DEBUG] [{input_source}] Recording host speech (no auto-reply): '{transcription_text}'")
                else:
                    self.translation_controller.schedule_auto_reply(transcription_text, input_source)
            else:
                print(f"[DEBUG] [{input_source}] NOT scheduling auto-reply. Checkbox: {self.auto_reply_checkbox.isChecked()}, Text empty: {not transcription_text.strip()}")
        else:
            self.status_label.setText(f"Live [{input_source}]: {transcription_text}" if transcription_text.strip() else "Listening...")
            
            if self.auto_reply_checkbox.isChecked() and transcription_text.strip():
                print(f"[DEBUG] [{input_source}] Canceling auto-reply (non-final text with content received)")
                self.translation_controller.cancel_auto_reply()
            elif self.auto_reply_checkbox.isChecked() and not transcription_text.strip():
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
    
    def _on_translation_result(self, result: str):
        """Handle translation result."""
        self.gemini_text.setText(format_gemini_result(result))
    
    def _on_translation_error(self, msg: str):
        """Handle translation errors."""
        if "already in progress" in msg.lower():
            QMessageBox.warning(self, "Translation in Progress", "Please wait for the current translation to complete.")
        elif "auto-reply" not in msg.lower():
            QMessageBox.critical(self, "Translation Error", msg)
        
        if "auto-reply" not in msg.lower():
            self.gemini_text.setText("Translation failed.")
    
    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result."""
        self.gemini_text.setText(format_gemini_result(result))
    
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
            gemini_lines = self.gemini_text.document().blockCount()
            
            self.memory_label.setText(f"Memory: {mem_mb:.1f} MB | Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except ImportError:
            trans_lines = self.transcription_editor.document().blockCount()
            self.memory_label.setText(f"Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except Exception:
            pass
    
    def _set_screen_protection(self, enabled):
        """Exclude this window from screen capture and mirror the state on both controls."""
        enabled = bool(enabled)
        self._screen_protection_enabled = enabled
        set_capture_protection(self, enabled)
        for widget in (self.screen_protection_action, self.screen_protection_checkbox):
            if widget.isChecked() != enabled:
                widget.setChecked(enabled)

    def showEvent(self, event):
        super().showEvent(event)
        # Changing window flags / re-showing resets the display affinity,
        # so re-apply it whenever the window becomes visible.
        if self._screen_protection_enabled:
            set_capture_protection(self, True)

    def closeEvent(self, event):
        """Clean up resources on window close."""
        try:
            self._memory_monitor_timer.stop()
            
            # Stop transcription first to stop audio streams
            self.transcription_controller.cleanup()
            
            # Stop translation
            self.translation_controller.cleanup()
            
            # Stop websocket
            self.websocket_client.stop()
            
            # Give threads time to finish
            from PySide6.QtCore import QThread
            QThread.msleep(500)
            
        except Exception as e:
            print(f"[Cleanup] Error during cleanup: {e}")
        
        event.accept()
        return super().closeEvent(event)
