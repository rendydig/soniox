#!/usr/bin/env python3
import sys
import os
import queue
import time
import asyncio
import json
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
from dotenv import load_dotenv
import google.generativeai as genai

from PySide6.QtCore import Qt, QThread, Signal, QMetaObject, Q_ARG, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QLineEdit,
    QTextEdit,
)

load_dotenv()


class RecorderWorker(QThread):
    error = Signal(str)
    status = Signal(str)
    saved = Signal(str)

    def __init__(self, device_id: int, samplerate: float, channels: int, filepath: str, parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._samplerate = int(samplerate)
        self._channels = channels
        self._filepath = filepath
        self._stop_flag = False
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=64)

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            self.status.emit("Opening audio stream...")

            # Open file for writing WAV
            with sf.SoundFile(
                self._filepath,
                mode="w",
                samplerate=self._samplerate,
                channels=self._channels,
                subtype="PCM_16",
                format="WAV",
            ) as wav_file:

                def callback(indata, frames, time_info, status):
                    if status:
                        # Forward PortAudio status warnings to UI
                        self.status.emit(f"Audio status: {status}")
                    # Copy to avoid referencing the underlying buffer
                    try:
                        self._q.put_nowait(indata.copy())
                    except queue.Full:
                        # Drop if writer is slow
                        pass

                with sd.InputStream(
                    samplerate=self._samplerate,
                    channels=self._channels,
                    device=self._device_id,
                    dtype="int16",
                    callback=callback,
                ):
                    self.status.emit("Recording...")
                    # Writer loop
                    while not self._stop_flag or not self._q.empty():
                        try:
                            data = self._q.get(timeout=0.2)
                            wav_file.write(data)
                        except queue.Empty:
                            if self._stop_flag:
                                break
                            continue

            self.saved.emit(self._filepath)
        except Exception as e:
            self.error.emit(str(e))


class GeminiWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    
    def __init__(self, text: str, target_language: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._target_language = target_language
        self._api_key = os.environ.get("GEMINI_API_KEY")
    
    def run(self):
        try:
            if not self._api_key:
                self.error.emit("GEMINI_API_KEY not found in .env file")
                return
            
            genai.configure(api_key=self._api_key)
            model = genai.GenerativeModel('gemini-pro')
            
            prompt = f"""Translate the following text to {self._target_language}. Provide the response in this exact format:

{self._target_language} Text: [Write the sentence using natural {self._target_language} script]

Syllables/Pronunciation: [Provide the pronunciation in Latin alphabet with Indonesian spelling so I know how to speak it]

English Translation: [Provide the meaning in clear English]

Text to translate: {self._text}"""
            
            response = model.generate_content(prompt)
            self.result.emit(response.text)
        except Exception as e:
            self.error.emit(f"Gemini error: {str(e)}")


class SonioxWorker(QThread):
    error = Signal(str)
    status = Signal(str)
    transcription_update = Signal(str, bool)
    
    def __init__(self, device_id: int, parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._stop_flag = False
        self._api_key = os.environ.get("SONIOX_API_KEY")
        self._ws_url = "wss://stt-rt.soniox.com/transcribe-websocket"
        self._sample_rate = 16000
        self._channels = 1
        self._audio_queue = queue.Queue(maxsize=16)
        
    def stop(self):
        self._stop_flag = True
        
    def run(self):
        try:
            if not self._api_key:
                self.error.emit("SONIOX_API_KEY not found in .env file")
                return
                
            self.status.emit("Connecting to Soniox...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._stream_audio())
        except Exception as e:
            self.error.emit(f"Soniox error: {e}")
            
    async def _stream_audio(self):
        try:
            async with websockets.connect(self._ws_url) as ws:
                self.status.emit("Connected to Soniox")
                
                config = {
                    "api_key": self._api_key,
                    "model": "stt-rt-v3",
                    "audio_format": "pcm_s16le",
                    "sample_rate": self._sample_rate,
                    "num_channels": self._channels,
                    "enable_endpoint_detection": True,
                }
                
                await ws.send(json.dumps(config))
                self.status.emit("Streaming audio to Soniox...")
                
                async def sender():
                    def audio_callback(indata, frames, time_info, status):
                        if not self._stop_flag:
                            pcm16 = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
                            try:
                                self._audio_queue.put_nowait(pcm16)
                            except queue.Full:
                                pass
                    
                    with sd.InputStream(
                        samplerate=self._sample_rate,
                        channels=self._channels,
                        dtype="float32",
                        callback=audio_callback,
                        blocksize=1024,
                        device=self._device_id,
                    ):
                        while not self._stop_flag:
                            try:
                                chunk = self._audio_queue.get_nowait()
                                await ws.send(chunk)
                            except queue.Empty:
                                await asyncio.sleep(0.01)
                    
                    await ws.send("")
                
                async def receiver():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            
                            if data.get("error_code"):
                                self.error.emit(f"{data['error_code']}: {data.get('error_message', '')}")
                                break
                            
                            tokens = data.get("tokens", [])
                            if tokens:
                                final_tokens = [t for t in tokens if t.get("is_final")]
                                non_final_tokens = [t for t in tokens if not t.get("is_final")]
                                
                                if final_tokens:
                                    text_parts = []
                                    for t in final_tokens:
                                        token_text = t.get("text", "")
                                        if token_text == "<end>":
                                            text_parts.append("\n")
                                        else:
                                            text_parts.append(token_text)
                                    text = "".join(text_parts)
                                    print(f"[DEBUG] Emitting FINAL: {repr(text)}")
                                    self.transcription_update.emit(text, True)
                                elif non_final_tokens:
                                    text = "".join(t.get("text", "") for t in non_final_tokens)
                                    print(f"[DEBUG] Emitting PARTIAL: {repr(text)}")
                                    self.transcription_update.emit(text, False)
                            
                            if data.get("finished"):
                                self.status.emit("Session finished")
                                break
                        except json.JSONDecodeError:
                            pass
                        except Exception as e:
                            print(f"Receiver error: {e}")
                
                await asyncio.gather(sender(), receiver())
                
        except Exception as e:
            self.error.emit(f"WebSocket error: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Soniox Real-Time Transcription")
        self.setMinimumSize(700, 500)

        self._recorder_worker: RecorderWorker | None = None
        self._soniox_worker: SonioxWorker | None = None
        self._gemini_worker: GeminiWorker | None = None
        self._recording = False
        self._transcribing = False
        self._final_transcript = ""
        self._devices = []  # list of dicts with device info
        self._device_ids = []  # parallel list of actual device indices
        self._channels_default = 2

        # Base folder
        self._base_dir = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "recordings")
        os.makedirs(self._base_dir, exist_ok=True)

        # Print important macOS note for system audio capture
        print("Note: To capture system audio on macOS, install a virtual audio driver (e.g., BlackHole or VB-Cable),\n"
              "then select that device as the input device in this app.")

        self._build_ui()
        self._populate_devices()
        self._update_state_label("Ready.")

    def _build_ui(self):
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Device selection
        device_row = QHBoxLayout()
        device_label = QLabel("Audio Input Device:")
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(360)
        device_row.addWidget(device_label)
        device_row.addWidget(self.device_combo, 1)
        layout.addLayout(device_row)

        # Destination folder
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

        # Text areas row (side by side)
        text_areas_label = QLabel("Output:")
        layout.addWidget(text_areas_label)
        
        text_areas_row = QHBoxLayout()
        
        # Transcription text area (left)
        transcription_container = QVBoxLayout()
        transcription_label = QLabel("Real-Time Transcription")
        self.transcription_text = QTextEdit()
        self.transcription_text.setPlaceholderText("Transcription will appear here...")
        self.transcription_text.setMinimumHeight(200)
        transcription_container.addWidget(transcription_label)
        transcription_container.addWidget(self.transcription_text)
        
        # Gemini suggestion text area (right)
        gemini_container = QVBoxLayout()
        gemini_label = QLabel("Gemini Suggestion")
        self.gemini_text = QTextEdit()
        self.gemini_text.setPlaceholderText("Gemini translation will appear here...")
        self.gemini_text.setMinimumHeight(200)
        self.gemini_text.setReadOnly(True)
        gemini_container.addWidget(gemini_label)
        gemini_container.addWidget(self.gemini_text)
        
        text_areas_row.addLayout(transcription_container)
        text_areas_row.addLayout(gemini_container)
        layout.addLayout(text_areas_row)
        
        # Translation input section
        translation_section_label = QLabel("Translation:")
        layout.addWidget(translation_section_label)
        
        # Language selection and input field
        translation_row = QHBoxLayout()
        
        lang_label = QLabel("Target Language:")
        self.language_combo = QComboBox()
        self.language_combo.addItems(["English", "Arabic", "Japanese", "Chinese", "Korean"])
        self.language_combo.setMinimumWidth(150)
        
        translation_row.addWidget(lang_label)
        translation_row.addWidget(self.language_combo)
        translation_row.addStretch()
        
        layout.addLayout(translation_row)
        
        # Translation input field
        input_label = QLabel("Text to Translate (Press Ctrl+Enter to submit):")
        layout.addWidget(input_label)
        
        self.translation_input = QTextEdit()
        self.translation_input.setPlaceholderText("Type text to translate and press Ctrl+Enter...")
        self.translation_input.setMinimumHeight(80)
        self.translation_input.installEventFilter(self)
        layout.addWidget(self.translation_input)
        
        # Status label
        self.status_label = QLabel("Idle")
        font = self.status_label.font()
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label)

        # Buttons row
        buttons_row = QHBoxLayout()
        
        # Transcribe button
        self.transcribe_btn = QPushButton("Start Transcription")
        self.transcribe_btn.setCheckable(True)
        self.transcribe_btn.setMinimumHeight(56)
        self.transcribe_btn.clicked.connect(self._toggle_transcription)
        buttons_row.addWidget(self.transcribe_btn)
        
        # Record button
        self.record_btn = QPushButton("Record to File")
        self.record_btn.setCheckable(True)
        self.record_btn.setMinimumHeight(56)
        self.record_btn.clicked.connect(self._toggle_recording)
        buttons_row.addWidget(self.record_btn)
        
        layout.addLayout(buttons_row)

        # Styling for a cleaner look
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QComboBox, QLineEdit { padding: 6px; }
            QPushButton { padding: 10px 16px; }
            QPushButton:checked { background-color: #d9534f; color: white; }
            QTextEdit { font-family: monospace; font-size: 13px; }
            """
        )

        self.setCentralWidget(central)

    def _choose_destination(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose destination folder", self._base_dir)
        if folder:
            self._base_dir = folder
            self.dest_edit.setText(folder)

    def _populate_devices(self):
        try:
            all_devices = sd.query_devices()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to query audio devices: {e}")
            return

        self._devices = []
        self._device_ids = []
        self.device_combo.clear()

        for idx, dev in enumerate(all_devices):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Device {idx}")
                sr = dev.get("default_samplerate") or 44100
                label = f"[{idx}] {name} — {int(sr)} Hz"
                self.device_combo.addItem(label)
                self._devices.append(dev)
                self._device_ids.append(idx)

        if not self._devices:
            QMessageBox.warning(
                self,
                "No Input Devices",
                "No input-capable audio devices found.\n\n"
                "On macOS, to capture system audio, install a virtual device (BlackHole/VB-Cable) and select it here.",
            )

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
        channels = min(dev_info.get("max_input_channels", 1), self._channels_default)
        channels = max(1, channels)

        os.makedirs(self._base_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.wav"
        filepath = os.path.join(self._base_dir, filename)

        self._recorder_worker = RecorderWorker(device_id, samplerate, channels, filepath)
        self._recorder_worker.status.connect(self._update_state_label)
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
        self.transcribe_btn.setEnabled(False)
        self._update_state_label("Recording...")

    def _stop_recording(self):
        if self._recorder_worker is not None:
            self._recorder_worker.stop()
        self._update_state_label("Stopping...")
    
    def _toggle_transcription(self, checked: bool):
        if checked:
            self._start_transcription()
        else:
            self._stop_transcription()
    
    def _start_transcription(self):
        if not self._device_ids:
            QMessageBox.warning(self, "No Device", "No input device is available.")
            self.transcribe_btn.setChecked(False)
            return
        
        index = self.device_combo.currentIndex()
        if index < 0 or index >= len(self._device_ids):
            QMessageBox.warning(self, "No Device Selected", "Please select an input device.")
            self.transcribe_btn.setChecked(False)
            return
        
        device_id = self._device_ids[index]
        
        self._final_transcript = ""
        self.transcription_text.clear()
        
        self._soniox_worker = SonioxWorker(device_id)
        self._soniox_worker.status.connect(self._update_state_label, Qt.ConnectionType.QueuedConnection)
        self._soniox_worker.error.connect(self._on_soniox_error, Qt.ConnectionType.QueuedConnection)
        self._soniox_worker.transcription_update.connect(self._on_transcription_update, Qt.ConnectionType.QueuedConnection)
        
        try:
            self._soniox_worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start transcription: {e}")
            self._soniox_worker = None
            self.transcribe_btn.setChecked(False)
            return
        
        self._transcribing = True
        self.transcribe_btn.setText("Stop Transcription")
        self.record_btn.setEnabled(False)
        self._update_state_label("Transcribing...")
    
    def _stop_transcription(self):
        if self._soniox_worker is not None:
            self._soniox_worker.stop()
        self._update_state_label("Stopping transcription...")
    
    def _on_transcription_update(self, text: str, is_final: bool):
        print(f"[DEBUG] Received in UI: is_final={is_final}, text={repr(text)}")
        if is_final:
            cursor = self.transcription_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.transcription_text.setTextCursor(cursor)
            self.transcription_text.ensureCursorVisible()
            self._final_transcript = self.transcription_text.toPlainText()
        else:
            self.status_label.setText(f"Listening: {text}..." if text.strip() else "Listening...")
    
    def _on_soniox_error(self, msg: str):
        self._transcribing = False
        self.transcribe_btn.setChecked(False)
        self.transcribe_btn.setText("Start Transcription")
        self.record_btn.setEnabled(True)
        QMessageBox.critical(self, "Transcription Error", msg)
        self._update_state_label("Error.")

    def _on_recorder_error(self, msg: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record to File")
        self.transcribe_btn.setEnabled(True)
        QMessageBox.critical(self, "Recording Error", msg +
                             "\n\nTip (macOS): Ensure microphone permission is granted in System Settings > Privacy & Security > Microphone.")
        self._update_state_label("Error.")

    def _on_recorder_saved(self, path: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record to File")
        self.transcribe_btn.setEnabled(True)
        self._update_state_label(f"Saved to: {path}")

    def _update_state_label(self, text: str):
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
        
        target_language = self.language_combo.currentText()
        
        if self._gemini_worker is not None and self._gemini_worker.isRunning():
            QMessageBox.warning(self, "Translation in Progress", "Please wait for the current translation to complete.")
            return
        
        self._gemini_worker = GeminiWorker(text, target_language)
        self._gemini_worker.result.connect(self._on_gemini_result, Qt.ConnectionType.QueuedConnection)
        self._gemini_worker.error.connect(self._on_gemini_error, Qt.ConnectionType.QueuedConnection)
        
        self.gemini_text.setText("Translating...")
        self._update_state_label(f"Translating to {target_language}...")
        self._gemini_worker.start()
    
    def _on_gemini_result(self, result: str):
        self.gemini_text.setText(result)
        self._update_state_label("Translation complete.")
    
    def _on_gemini_error(self, msg: str):
        QMessageBox.critical(self, "Translation Error", msg)
        self.gemini_text.setText("Translation failed.")
        self._update_state_label("Translation error.")

    def closeEvent(self, event):
        try:
            if self._recorder_worker is not None and self._recorder_worker.isRunning():
                self._recorder_worker.stop()
                self._recorder_worker.wait(3000)
            if self._soniox_worker is not None and self._soniox_worker.isRunning():
                self._soniox_worker.stop()
                self._soniox_worker.wait(3000)
            if self._gemini_worker is not None and self._gemini_worker.isRunning():
                self._gemini_worker.wait(3000)
        except Exception:
            pass
        return super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
