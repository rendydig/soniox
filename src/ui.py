import sys
import os
import sounddevice as sd
from datetime import datetime
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QComboBox, QPushButton, QTextEdit, QMessageBox, 
                             QRadioButton, QButtonGroup, QLineEdit, QFileDialog)
from PySide6.QtCore import Qt
from src.workers import SonioxWorker, RecorderWorker
from src.config import LANGUAGES


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soniox AI: Transcribe & Translate")
        self.resize(800, 600)
        
        self._soniox_worker = None
        self._recorder_worker = None
        self._device_ids = []
        self._recording = False
        self._transcribing = False
        
        self._base_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "recordings")
        os.makedirs(self._base_dir, exist_ok=True)
        
        self._init_ui()
        self._populate_devices()

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
        self.dest_edit = QLineEdit(self._base_dir)
        self.dest_edit.setReadOnly(True)
        browse_btn = QPushButton("Change...")
        browse_btn.clicked.connect(self._choose_destination)
        dest_row.addWidget(dest_label)
        dest_row.addWidget(self.dest_edit, 1)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

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

        transcription_label = QLabel("Output:")
        layout.addWidget(transcription_label)
        
        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText("Output will appear here...")
        self.text_area.setMinimumHeight(200)
        layout.addWidget(self.text_area)

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

        self.status_label = QLabel("Ready")
        font = self.status_label.font()
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QComboBox, QLineEdit { padding: 6px; }
            QPushButton { padding: 10px 16px; }
            QPushButton:checked { background-color: #d9534f; color: white; }
            QTextEdit { font-family: monospace; font-size: 13px; }
            """
        )

    def _choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose destination folder", self._base_dir)
        if folder:
            self._base_dir = folder
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

        device_id = self._device_ids[idx]
        
        mode = "translation" if self.rb_translate.isChecked() else "transcription"
        target_lang = self.lang_combo.currentData()

        self._soniox_worker = SonioxWorker(device_id, mode=mode, target_lang=target_lang)
        self._soniox_worker.transcription_update.connect(self._on_update)
        self._soniox_worker.status.connect(self._update_status)
        self._soniox_worker.error.connect(lambda e: self._on_soniox_error(e))
        self._soniox_worker.start()
        
        self.btn_start.setText("Stop")
        self.record_btn.setEnabled(False)
        self.text_area.clear()
        self._transcribing = True

    def _stop_session(self):
        if self._soniox_worker:
            self._soniox_worker.stop()
            self._soniox_worker = None
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
        self.record_btn.setEnabled(True)
        self._transcribing = False
        self._update_status("Stopped")

    def _on_update(self, text, is_final):
        if is_final:
            cursor = self.text_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.text_area.setTextCursor(cursor)
            self.text_area.ensureCursorVisible()
        else:
            self.status_label.setText(f"Live: {text}" if text.strip() else "Listening...")

    def _on_soniox_error(self, msg: str):
        self._transcribing = False
        self.btn_start.setChecked(False)
        self.btn_start.setText("Start Transcription" if self.rb_transcribe.isChecked() else "Start Translation")
        self.record_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", msg)
        self._update_status("Error")

    def _update_status(self, text: str):
        self.status_label.setText(text)

    def _populate_devices(self):
        try:
            devs = sd.query_devices()
            for idx, d in enumerate(devs):
                if d.get('max_input_channels', 0) > 0:
                    name = d.get('name', f'Device {idx}')
                    sr = d.get('default_samplerate') or 44100
                    label = f"[{idx}] {name} — {int(sr)} Hz"
                    self.device_combo.addItem(label)
                    self._device_ids.append(idx)
        except Exception as e:
            QMessageBox.warning(self, "Device Error", f"Failed to query audio devices: {e}")

    def _toggle_recording(self, checked: bool):
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        if not self._device_ids:
            QMessageBox.warning(self, "No Device", "No input device is available to record from.")
            self.record_btn.setChecked(False)
            return

        index = self.device_combo.currentIndex()
        if index < 0 or index >= len(self._device_ids):
            QMessageBox.warning(self, "No Device Selected", "Please select an input device.")
            self.record_btn.setChecked(False)
            return

        device_id = self._device_ids[index]
        dev_info = sd.query_devices(device_id)
        samplerate = dev_info.get("default_samplerate") or 44100
        channels = min(dev_info.get("max_input_channels", 1), 2)
        channels = max(1, channels)

        os.makedirs(self._base_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.wav"
        filepath = os.path.join(self._base_dir, filename)

        self._recorder_worker = RecorderWorker(device_id, samplerate, channels, filepath)
        self._recorder_worker.status.connect(self._update_status)
        self._recorder_worker.error.connect(self._on_recorder_error)
        self._recorder_worker.saved.connect(self._on_recorder_saved)

        try:
            self._recorder_worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start recording: {e}")
            self._recorder_worker = None
            self.record_btn.setChecked(False)
            return

        self._recording = True
        self.record_btn.setText("Stop Recording")
        self.btn_start.setEnabled(False)
        self._update_status("Recording...")

    def _stop_recording(self):
        if self._recorder_worker is not None:
            self._recorder_worker.stop()
        self._update_status("Stopping...")

    def _on_recorder_error(self, msg: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record to File")
        self.btn_start.setEnabled(True)
        QMessageBox.critical(self, "Recording Error", msg)
        self._update_status("Error")

    def _on_recorder_saved(self, path: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record to File")
        self.btn_start.setEnabled(True)
        self._update_status(f"Saved to: {path}")

    def closeEvent(self, event):
        try:
            if self._recorder_worker is not None and self._recorder_worker.isRunning():
                self._recorder_worker.stop()
                self._recorder_worker.wait(3000)
            if self._soniox_worker is not None and self._soniox_worker.isRunning():
                self._soniox_worker.stop()
                self._soniox_worker.wait(3000)
        except Exception:
            pass
        return super().closeEvent(event)
