import os
from datetime import datetime
from PySide6.QtCore import QObject, Signal
from src.workers import RecorderWorker


class RecordingController(QObject):
    """Handles audio recording logic and file management."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    recording_saved = Signal(str)
    recording_started = Signal()
    recording_stopped = Signal()
    
    def __init__(self, base_dir: str):
        super().__init__()
        self._base_dir = base_dir
        self._recorder_worker = None
        self._recording = False
        
        os.makedirs(self._base_dir, exist_ok=True)
    
    def set_base_dir(self, base_dir: str):
        """Update the base directory for recordings."""
        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)
    
    def get_base_dir(self):
        """Get the current base directory."""
        return self._base_dir
    
    def is_recording(self):
        """Check if currently recording."""
        return self._recording
    
    def start_recording(self, device_id: int, samplerate: float, channels: int):
        """Start recording audio to a file."""
        if self._recording:
            self.error_occurred.emit("Already recording")
            return False
        
        try:
            os.makedirs(self._base_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.wav"
            filepath = os.path.join(self._base_dir, filename)
            
            self._recorder_worker = RecorderWorker(device_id, samplerate, channels, filepath)
            self._recorder_worker.status.connect(self.status_changed)
            self._recorder_worker.error.connect(self._on_error)
            self._recorder_worker.saved.connect(self._on_saved)
            self._recorder_worker.finished.connect(self._on_worker_finished)
            
            self._recorder_worker.start()
            self._recording = True
            self.recording_started.emit()
            self.status_changed.emit("Recording...")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start recording: {e}")
            self._recorder_worker = None
            return False
    
    def stop_recording(self):
        """Stop the current recording."""
        if self._recorder_worker is not None:
            self._recorder_worker.stop()
            self.status_changed.emit("Stopping...")
    
    def _on_error(self, msg: str):
        """Handle errors from worker."""
        self._recording = False
        self._recorder_worker = None
        self.error_occurred.emit(msg)
        self.recording_stopped.emit()
    
    def _on_saved(self, path: str):
        """Handle successful save from worker."""
        self._recording = False
        self.recording_saved.emit(path)
        self.recording_stopped.emit()
        self.status_changed.emit(f"Saved to: {path}")
    
    def _on_worker_finished(self):
        """Handle worker thread finished."""
        if self._recorder_worker is not None:
            self._recorder_worker.deleteLater()
            self._recorder_worker = None
    
    def cleanup(self):
        """Clean up resources."""
        if self._recorder_worker is not None and self._recorder_worker.isRunning():
            self._recorder_worker.stop()
            self._recorder_worker.wait(3000)
            self._recorder_worker = None
