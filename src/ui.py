import sys
import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QPushButton, QTextEdit, QMessageBox, 
                             QRadioButton, QButtonGroup, QLineEdit, QFileDialog, QCheckBox)
from PySide6.QtCore import Qt, QEvent, QTimer
from src.config import LANGUAGES, MAX_TRANSCRIPTION_LINES, MAX_GEMINI_LINES
from src.text_formatter import append_timestamped_text
from src.controllers import (
    DeviceController,
    RecordingController,
    TranscriptionController,
    TranslationController
)
from src.websocket_client import WebSocketClient


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soniox AI: Transcribe & Translate")
        self.resize(800, 600)
        
        base_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "recordings")
        
        self.device_controller = DeviceController()
        self.recording_controller = RecordingController(base_dir)
        self.transcription_controller = TranscriptionController()
        self.translation_controller = TranslationController()
        
        self.websocket_client = WebSocketClient("ws://localhost:8765")
        self.websocket_client.start()
        
        self._memory_monitor_timer = QTimer()
        self._memory_monitor_timer.timeout.connect(self._update_memory_usage)
        self._memory_monitor_timer.start(5000)
        
        self._init_ui()
        self._setup_controller_connections()
        self.device_controller.populate_devices()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        dev_layout = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(360)
        dev_layout.addWidget(QLabel("Input Device:"))
        dev_layout.addWidget(self.device_combo, 1)
        layout.addLayout(dev_layout)

        dest_row = QHBoxLayout()
        dest_label = QLabel("Destination Folder:")
        self.dest_edit = QLineEdit(self.recording_controller.get_base_dir())
        self.dest_edit.setReadOnly(True)
        browse_btn = QPushButton("Change...")
        browse_btn.clicked.connect(self._choose_destination)
        dest_row.addWidget(dest_label)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        self.auto_record_checkbox = QCheckBox("Auto-record to WAV when transcribing/translating")
        self.auto_record_checkbox.setChecked(False)
        layout.addWidget(self.auto_record_checkbox)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        
        self.mode_group = QButtonGroup(self)
        self.rb_transcribe = QRadioButton("Live Transcription")
        self.rb_translate = QRadioButton("Live Translation")
        self.rb_transcribe.setChecked(True)
        
        self.mode_group.addButton(self.rb_transcribe)
        self.mode_group.addButton(self.rb_translate)
        
        mode_layout.addWidget(self.rb_transcribe)
        mode_layout.addWidget(self.rb_translate)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        self.lang_container = QWidget()
        lang_layout = QHBoxLayout(self.lang_container)
        lang_layout.setContentsMargins(0,0,0,0)
        
        self.lang_combo = QComboBox()
        for name, code in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentText("Indonesian")
        
        lang_layout.addWidget(QLabel("Target Language:"))
        lang_layout.addWidget(self.lang_combo, 1)
        
        layout.addWidget(self.lang_container)
        self.lang_container.setVisible(False)

        self.mode_group.buttonToggled.connect(self._on_mode_changed)

        # Text areas row (side by side)
        transcription_editors_label = QLabel("Output:")
        layout.addWidget(transcription_editors_label)
        
        transcription_editors_row = QHBoxLayout()
        
        # Transcription text area (left)
        transcription_container = QVBoxLayout()
        transcription_label = QLabel("Real-Time Transcription")
        self.transcription_editor = QTextEdit()
        self.transcription_editor.setPlaceholderText("Transcription will appear here...")
        self.transcription_editor.setMinimumHeight(200)
        transcription_container.addWidget(transcription_label)
        transcription_container.addWidget(self.transcription_editor)
        
        # Gemini suggestion text area (right)
        gemini_container = QVBoxLayout()
        gemini_header = QHBoxLayout()
        gemini_label = QLabel("Gemini Suggestion")
        self.auto_reply_checkbox = QCheckBox("Auto reply")
        gemini_header.addWidget(gemini_label)
        gemini_header.addWidget(self.auto_reply_checkbox)
        gemini_header.addStretch()
        self.gemini_text = QTextEdit()
        self.gemini_text.setPlaceholderText("Gemini translation will appear here...")
        self.gemini_text.setMinimumHeight(200)
        self.gemini_text.setReadOnly(True)
        gemini_container.addLayout(gemini_header)
        gemini_container.addWidget(self.gemini_text)
        
        transcription_editors_row.addLayout(transcription_container)
        transcription_editors_row.addLayout(gemini_container)
        layout.addLayout(transcription_editors_row)
        
        # Translation section
        translation_section_label = QLabel("Gemini Translation:")
        layout.addWidget(translation_section_label)
        
        # Language selection for Gemini
        gemini_lang_row = QHBoxLayout()
        gemini_lang_label = QLabel("Target translation Language:")
        self.gemini_lang_combo = QComboBox()
        self.gemini_lang_combo.addItems(["English", "Arabic", "Japanese", "Chinese", "Korean"])
        self.gemini_lang_combo.setMinimumWidth(150)
        
        gemini_lang_row.addWidget(gemini_lang_label)
        gemini_lang_row.addWidget(self.gemini_lang_combo)
        gemini_lang_row.addStretch()
        layout.addLayout(gemini_lang_row)
        
        # Translation input field
        input_label = QLabel("Text to Translate (Press Ctrl+Enter to submit):")
        layout.addWidget(input_label)
        
        self.translation_input = QTextEdit()
        self.translation_input.setPlaceholderText("Type text to translate and press Ctrl+Enter...")
        self.translation_input.setMinimumHeight(80)
        self.translation_input.installEventFilter(self)
        layout.addWidget(self.translation_input)

        buttons_row = QHBoxLayout()
        
        self.btn_start = QPushButton("Start Transcription")
        self.btn_start.setCheckable(True)
        self.btn_start.setMinimumHeight(56)
        self.btn_start.clicked.connect(self._toggle_start)
        buttons_row.addWidget(self.btn_start)
        
        self.record_btn = QPushButton("Record to File")
        self.record_btn.setCheckable(True)
        self.record_btn.setMinimumHeight(56)
        self.record_btn.clicked.connect(self._toggle_recording)
        buttons_row.addWidget(self.record_btn)
        
        layout.addLayout(buttons_row)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        font = self.status_label.font()
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        status_row.addWidget(self.status_label, 1)
        
        self.memory_label = QLabel("")
        self.memory_label.setStyleSheet("color: #666; font-size: 11px;")
        status_row.addWidget(self.memory_label)
        layout.addLayout(status_row)

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
        
        self.recording_controller.status_changed.connect(self._update_status)
        self.recording_controller.error_occurred.connect(self._on_recording_error)
        self.recording_controller.recording_started.connect(self._on_recording_started)
        self.recording_controller.recording_stopped.connect(self._on_recording_stopped)
        
        self.transcription_controller.status_changed.connect(self._update_status)
        self.transcription_controller.error_occurred.connect(self._on_transcription_error)
        self.transcription_controller.transcription_update.connect(self._on_update)
        self.transcription_controller.translation_update.connect(self._on_translation_update)
        self.transcription_controller.session_started.connect(self._on_transcription_started)
        self.transcription_controller.session_stopped.connect(self._on_transcription_stopped)
        
        self.translation_controller.status_changed.connect(self._update_status)
        self.translation_controller.error_occurred.connect(self._on_translation_error)
        self.translation_controller.translation_result.connect(self._on_translation_result)
        self.translation_controller.translation_started.connect(lambda: self.gemini_text.setText("Translating..."))
        self.translation_controller.auto_reply_result.connect(self._on_auto_reply_result)
        
        self.gemini_lang_combo.currentTextChanged.connect(self._on_auto_reply_language_changed)

    def _choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose destination folder", self.recording_controller.get_base_dir())
        if folder:
            self.recording_controller.set_base_dir(folder)
            self.dest_edit.setText(folder)

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
        idx = self.device_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "No Device", "Please select an input device.")
            self.btn_start.setChecked(False)
            return

        device_ids = self.device_controller.get_device_ids()
        if idx >= len(device_ids):
            QMessageBox.warning(self, "Invalid Device", "Selected device is not available.")
            self.btn_start.setChecked(False)
            return
        
        device_id = device_ids[idx]
        mode = "translation" if self.rb_translate.isChecked() else "transcription"
        target_lang = self.lang_combo.currentData()

        self.transcription_editor.clear()
        self.transcription_controller.start_session(device_id, mode=mode, target_lang=target_lang)
        
        if self.auto_record_checkbox.isChecked():
            dev_info = self.device_controller.get_device_info(device_id)
            if dev_info:
                samplerate = dev_info.get("default_samplerate") or 44100
                channels = min(dev_info.get("max_input_channels", 1), 2)
                channels = max(1, channels)
                self.recording_controller.start_recording(device_id, samplerate, channels)
                self.record_btn.setText("Recording (auto)")
                self.record_btn.setEnabled(False)

    def _stop_session(self):
        self.status_label.setText("Stopping...")
        
        self.transcription_controller.stop_session()
        
        if self.auto_record_checkbox.isChecked() and self.recording_controller.is_recording():
            self.recording_controller.stop_recording()

    def _on_update(self, text, is_final):
        print(f"[DEBUG] _on_update called: is_final={is_final}, text='{text[:50]}...', checkbox_checked={self.auto_reply_checkbox.isChecked()}")
        
        # Always send as "transcription" type (original English text)
        # Translation results are sent separately via _on_translation_update
        self.websocket_client.send_transcription(text, is_final, message_type="transcription")
        
        if is_final:
            append_timestamped_text(self.transcription_editor, text, max_lines=MAX_TRANSCRIPTION_LINES)
            
            if self.auto_reply_checkbox.isChecked() and text.strip():
                print(f"[DEBUG] Scheduling auto-reply for: '{text}'")
                additional_context = self.translation_input.toPlainText().strip()
                if additional_context:
                    print(f"[DEBUG] Including translation input as context: '{additional_context[:50]}...'")
                self.translation_controller.schedule_auto_reply(text, additional_context)
            else:
                print(f"[DEBUG] NOT scheduling auto-reply. Checkbox: {self.auto_reply_checkbox.isChecked()}, Text empty: {not text.strip()}")
        else:
            self.status_label.setText(f"Live: {text}" if text.strip() else "Listening...")
            
            if self.auto_reply_checkbox.isChecked() and text.strip():
                print(f"[DEBUG] Canceling auto-reply (non-final text with content received)")
                self.translation_controller.cancel_auto_reply()
            elif self.auto_reply_checkbox.isChecked() and not text.strip():
                print(f"[DEBUG] Ignoring empty non-final text, keeping auto-reply timer active")
    
    def _on_translation_update(self, text: str, is_final: bool):
        """Handle translation updates from transcription controller (Indonesian translations)."""
        print(f"[DEBUG] _on_translation_update called: is_final={is_final}, text='{text[:50]}...'")
        
        # Send translation via WebSocket
        self.websocket_client.send_transcription(text, is_final, message_type="translation")

    def _on_transcription_started(self):
        """Handle transcription session started."""
        self.btn_start.setText("Stop")
        self.record_btn.setEnabled(False)
    
    def _on_transcription_stopped(self):
        """Handle transcription session stopped."""
        self.btn_start.setChecked(False)
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
        self.record_btn.setEnabled(True)
    
    def _on_transcription_error(self, msg: str):
        """Handle transcription errors."""
        self.btn_start.setChecked(False)
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
        self.record_btn.setEnabled(True)
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
    
    def _on_auto_reply_language_changed(self, language: str):
        """Update auto-reply target language when combo box changes."""
        self.translation_controller.set_auto_reply_language(language)

    def _on_devices_populated(self, device_list: list, device_ids: list):
        """Handle devices populated from controller."""
        self.device_combo.clear()
        for label in device_list:
            self.device_combo.addItem(label)
    
    def _on_device_error(self, msg: str):
        """Handle device errors."""
        QMessageBox.warning(self, "Device Error", msg)

    def _toggle_recording(self, checked: bool):
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        if not self.device_controller.has_devices():
            QMessageBox.warning(self, "No Device", "No input device is available to record from.")
            self.record_btn.setChecked(False)
            return

        index = self.device_combo.currentIndex()
        device_ids = self.device_controller.get_device_ids()
        
        if index < 0 or index >= len(device_ids):
            QMessageBox.warning(self, "No Device Selected", "Please select an input device.")
            self.record_btn.setChecked(False)
            return

        device_id = device_ids[index]
        dev_info = self.device_controller.get_device_info(device_id)
        
        if not dev_info:
            self.record_btn.setChecked(False)
            return
        
        samplerate = dev_info.get("default_samplerate") or 44100
        channels = min(dev_info.get("max_input_channels", 1), 2)
        channels = max(1, channels)

        success = self.recording_controller.start_recording(device_id, samplerate, channels)
        if not success:
            self.record_btn.setChecked(False)

    def _stop_recording(self):
        self.recording_controller.stop_recording()

    def _on_recording_started(self):
        """Handle recording started."""
        self.record_btn.setText("Stop Recording")
        if not self.auto_record_checkbox.isChecked():
            self.btn_start.setEnabled(False)
    
    def _on_recording_stopped(self):
        """Handle recording stopped."""
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record to File")
        if not self.auto_record_checkbox.isChecked():
            self.btn_start.setEnabled(True)
        self.record_btn.setEnabled(True)
    
    def _on_recording_error(self, msg: str):
        """Handle recording errors."""
        QMessageBox.critical(self, "Recording Error", msg)

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
            self.recording_controller.cleanup()
            self.transcription_controller.cleanup()
            self.translation_controller.cleanup()
            self.websocket_client.stop()
        except Exception:
            pass
        return super().closeEvent(event)
