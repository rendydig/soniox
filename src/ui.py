import sys
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                             QMessageBox)
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from src.config import MAX_TRANSCRIPTION_LINES, MAX_GEMINI_LINES
from src.text_formatter import append_timestamped_text
from src.controllers import (
    DeviceController,
    TranscriptionController,
    TranslationController
)
from src.websocket_client import WebSocketClient
from src.ui_components import (
    DeviceSettingsWidget,
    ModeSelectionWidget,
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
        
        self._init_ui()
        self._setup_controller_connections()
        self.device_controller.populate_devices()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        self.device_settings = DeviceSettingsWidget()
        layout.addWidget(self.device_settings)
        
        self.mode_selection = ModeSelectionWidget()
        layout.addWidget(self.mode_selection)
        
        self.text_editors = TextEditorsWidget()
        layout.addWidget(self.text_editors)
        
        self.translation_section = TranslationSectionWidget()
        layout.addWidget(self.translation_section)
        
        self.control_buttons = ControlButtonsWidget()
        layout.addWidget(self.control_buttons)
        
        self.status_bar = StatusBarWidget()
        layout.addWidget(self.status_bar)
        
        self._setup_widget_references()
        self._setup_widget_connections()
        self._apply_styles()
    
    def _setup_widget_references(self):
        self.device_combo = self.device_settings.get_device_combo()
        self.speaker_combo = self.device_settings.get_speaker_combo()
        
        self.mode_group = self.mode_selection.get_mode_group()
        self.rb_transcribe = self.mode_selection.get_transcribe_radio()
        self.rb_translate = self.mode_selection.get_translate_radio()
        self.lang_container = self.mode_selection.get_lang_container()
        self.lang_combo = self.mode_selection.get_lang_combo()
        
        self.transcription_editor = self.text_editors.get_transcription_editor()
        self.gemini_text = self.text_editors.get_gemini_text()
        self.auto_reply_checkbox = self.text_editors.get_auto_reply_checkbox()
        
        self.gemini_lang_combo = self.translation_section.get_gemini_lang_combo()
        self.translation_input = self.translation_section.get_translation_input()
        
        self.btn_start = self.control_buttons.get_start_button()
        
        self.status_label = self.status_bar.get_status_label()
        self.memory_label = self.status_bar.get_memory_label()
    
    def _setup_widget_connections(self):
        self.mode_group.buttonToggled.connect(self._on_mode_changed)
        self.translation_input.installEventFilter(self)
        self.btn_start.clicked.connect(self._toggle_start)
        
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

    def _on_mode_changed(self, btn, checked):
        if checked:
            is_translation = (btn == self.rb_translate)
            self.lang_container.setVisible(is_translation)
            if is_translation:
                self.btn_start.setText("Start Translation")
            else:
                self.btn_start.setText("Start Transcription")

    def _toggle_start(self, checked):
        if checked:
            self._start_session()
        else:
            self._stop_session()

    def _start_session(self):
        host_idx = self.device_combo.currentIndex()
        if host_idx < 0:
            QMessageBox.warning(self, "No Device", "Please select a host input device.")
            self.btn_start.setChecked(False)
            return

        device_ids = self.device_controller.get_device_ids()
        if host_idx >= len(device_ids):
            QMessageBox.warning(self, "Invalid Device", "Selected host device is not available.")
            self.btn_start.setChecked(False)
            return
        
        host_device_id = device_ids[host_idx]
        
        # Get speaker device ID (optional)
        speaker_idx = self.speaker_combo.currentIndex()
        speaker_device_id = None
        if speaker_idx >= 0 and speaker_idx < len(device_ids):
            speaker_device_id = device_ids[speaker_idx]
            # Only use speaker device if it's different from host
            if speaker_device_id == host_device_id:
                speaker_device_id = None
        
        mode = "translation" if self.rb_translate.isChecked() else "transcription"
        target_lang = self.lang_combo.currentData()

        self.transcription_editor.clear()
        self.translation_controller.clear_conversation_history()
        self.transcription_controller.start_session(host_device_id, speaker_device_id, mode=mode, target_lang=target_lang)

    def _stop_session(self):
        self.status_label.setText("Stopping...")
        
        self.translation_controller.cancel_auto_reply()
        self.transcription_controller.stop_session()

    def _on_transcription_update(self, text, is_final, input_source):
        print(f"[DEBUG] [{input_source}] _on_transcription_update called: is_final={is_final}, text='{text[:50] if text else ''}...', checkbox_checked={self.auto_reply_checkbox.isChecked()}")
        
        # Always send as "transcription" type (original English text)
        # Translation results are sent separately via _on_translation_update
        self.websocket_client.send_transcription(text, is_final, additional_data={"input_source": input_source}, message_type="transcription")
        
        if is_final:
            # Prefix text with input source label
            labeled_text = f"[{input_source.upper()}] {text}"
            append_timestamped_text(self.transcription_editor, labeled_text, max_lines=MAX_TRANSCRIPTION_LINES)
            
            self._last_final_transcription = text
            
            if self.auto_reply_checkbox.isChecked() and text.strip():
                if input_source == "host":
                    print(f"[DEBUG] [{input_source}] Recording host speech (no auto-reply): '{text}'")
                    self.translation_controller.record_host_speech(text)
                else:
                    print(f"[DEBUG] [{input_source}] Scheduling auto-reply for: '{text}'")
                    additional_context = self.translation_input.toPlainText().strip()
                    if additional_context:
                        print(f"[DEBUG] Including translation input as context: '{additional_context[:50]}...'")
                    self.translation_controller.schedule_auto_reply(text, additional_context, input_source)
            else:
                print(f"[DEBUG] [{input_source}] NOT scheduling auto-reply. Checkbox: {self.auto_reply_checkbox.isChecked()}, Text empty: {not text.strip()}")
        else:
            self.status_label.setText(f"Live [{input_source}]: {text}" if text.strip() else "Listening...")
            
            if self.auto_reply_checkbox.isChecked() and text.strip():
                print(f"[DEBUG] [{input_source}] Canceling auto-reply (non-final text with content received)")
                self.translation_controller.cancel_auto_reply()
            elif self.auto_reply_checkbox.isChecked() and not text.strip():
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
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
    
    def _on_transcription_error(self, msg: str):
        """Handle transcription errors."""
        self.btn_start.setChecked(False)
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
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
        self.gemini_text.setText(result)
    
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
        self.gemini_text.setText(result)
    
    def _manual_reply(self):
        """Manually trigger a Gemini reply using the last final transcription (Ctrl+R / Cmd+R)."""
        text = self._last_final_transcription.strip()
        if not text:
            text = self.transcription_editor.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "No Transcription", "No transcription available to reply to.")
            return
        additional_context = self.translation_input.toPlainText().strip()
        self.translation_controller.trigger_reply_now(text, additional_context, "speaker")
    
    def _on_auto_reply_language_changed(self, language: str):
        """Update auto-reply target language when combo box changes."""
        self.translation_controller.set_auto_reply_language(language)

    def _on_devices_populated(self, device_list: list, device_ids: list):
        """Handle devices populated from controller."""
        self.device_combo.clear()
        self.speaker_combo.clear()
        for label in device_list:
            self.device_combo.addItem(label)
            self.speaker_combo.addItem(label)
        
        # Auto-select BlackHole for speaker device if available
        for idx, label in enumerate(device_list):
            if "blackhole" in label.lower():
                self.speaker_combo.setCurrentIndex(idx)
                break
    
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
