#!/usr/bin/env python3
import sys
import os
import queue
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from PySide6.QtCore import Qt, QThread, Signal
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
)


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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PySide6 Audio Recorder (sounddevice)")
        self.setMinimumSize(520, 280)

        self._worker: RecorderWorker | None = None
        self._recording = False
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

        # Status label
        self.status_label = QLabel("Idle")
        font = self.status_label.font()
        font.setPointSize(font.pointSize() + 1)
        self.status_label.setFont(font)
        layout.addWidget(self.status_label)

        # Record/Stop button
        self.record_btn = QPushButton("Record")
        self.record_btn.setCheckable(True)
        self.record_btn.setMinimumHeight(56)
        self.record_btn.clicked.connect(self._toggle_recording)
        layout.addWidget(self.record_btn)

        # Styling for a cleaner look
        self.setStyleSheet(
            """
            QWidget { font-size: 14px; }
            QComboBox, QLineEdit { padding: 6px; }
            QPushButton { padding: 10px 16px; }
            QPushButton:checked { background-color: #d9534f; color: white; }
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

        self._worker = RecorderWorker(device_id, samplerate, channels, filepath)
        self._worker.status.connect(self._update_state_label)
        self._worker.error.connect(self._on_worker_error)
        self._worker.saved.connect(self._on_worker_saved)

        try:
            self._worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start recording: {e}")
            self._worker = None
            self.record_btn.setChecked(False)
            return

        self._recording = True
        self.record_btn.setText("Stop")
        self._update_state_label("Recording...")

    def _stop_recording(self):
        if self._worker is not None:
            self._worker.stop()
        self._update_state_label("Stopping...")

    def _on_worker_error(self, msg: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record")
        QMessageBox.critical(self, "Recording Error", msg +
                             "\n\nTip (macOS): Ensure microphone permission is granted in System Settings > Privacy & Security > Microphone.")
        self._update_state_label("Error.")

    def _on_worker_saved(self, path: str):
        self._recording = False
        self.record_btn.setChecked(False)
        self.record_btn.setText("Record")
        self._update_state_label(f"Saved to: {path}")

    def _update_state_label(self, text: str):
        self.status_label.setText(text)

    def closeEvent(self, event):
        try:
            if self._worker is not None and self._worker.isRunning():
                self._worker.stop()
                # Wait briefly to allow proper shutdown of stream
                self._worker.wait(3000)
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
