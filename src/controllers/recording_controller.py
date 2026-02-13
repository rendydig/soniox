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
        self._host_recorder = None
        self._speaker_recorder = None
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
    
    def start_recording(self, host_device_id: int, samplerate: float, channels: int, speaker_device_id: int = None):
        """Start recording audio to file(s)."""
        if self._recording:
            self.error_occurred.emit("Already recording")
            return False
        
        try:
            os.makedirs(self._base_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Create host recorder
            host_filename = f"recording_host_{timestamp}.wav"
            host_filepath = os.path.join(self._base_dir, host_filename)
            
            self._host_recorder = RecorderWorker(host_device_id, samplerate, channels, host_filepath)
            self._host_recorder.status.connect(lambda msg: self.status_changed.emit(f"[HOST] {msg}"))
            self._host_recorder.error.connect(lambda msg: self._on_error(msg, "host"))
            self._host_recorder.saved.connect(lambda path: self._on_saved(path, "host"))
            self._host_recorder.finished.connect(lambda: self._on_worker_finished("host"))
            
            self._host_recorder.start()
            
            # Create speaker recorder if device is provided
            if speaker_device_id is not None:
                speaker_filename = f"recording_speaker_{timestamp}.wav"
                speaker_filepath = os.path.join(self._base_dir, speaker_filename)
                
                self._speaker_recorder = RecorderWorker(speaker_device_id, samplerate, channels, speaker_filepath)
                self._speaker_recorder.status.connect(lambda msg: self.status_changed.emit(f"[SPEAKER] {msg}"))
                self._speaker_recorder.error.connect(lambda msg: self._on_error(msg, "speaker"))
                self._speaker_recorder.saved.connect(lambda path: self._on_saved(path, "speaker"))
                self._speaker_recorder.finished.connect(lambda: self._on_worker_finished("speaker"))
                
                self._speaker_recorder.start()
            
            self._recording = True
            self.recording_started.emit()
            self.status_changed.emit("Recording...")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start recording: {e}")
            self._host_recorder = None
            self._speaker_recorder = None
            return False
    
    def stop_recording(self):
        """Stop the current recording."""
        if self._host_recorder is not None:
            self._host_recorder.stop()
        
        if self._speaker_recorder is not None:
            self._speaker_recorder.stop()
        
        self.status_changed.emit("Stopping...")
    
    def _on_error(self, msg: str, input_source: str):
        """Handle errors from worker."""
        self.error_occurred.emit(f"[{input_source.upper()}] {msg}")
        
        # Stop both recorders on error
        if self._host_recorder:
            self._host_recorder.stop()
        if self._speaker_recorder:
            self._speaker_recorder.stop()
        
        self._recording = False
        self._host_recorder = None
        self._speaker_recorder = None
        self.recording_stopped.emit()
    
    def _on_saved(self, path: str, input_source: str):
        """Handle successful save from worker."""
        self.recording_saved.emit(path)
        self.status_changed.emit(f"[{input_source.upper()}] Saved to: {path}")
        
        # Check if both recorders are done
        host_done = self._host_recorder is None or not self._host_recorder.isRunning()
        speaker_done = self._speaker_recorder is None or not self._speaker_recorder.isRunning()
        
        if host_done and speaker_done:
            self._recording = False
            self.recording_stopped.emit()
    
    def _on_worker_finished(self, input_source: str):
        """Handle worker thread finished."""
        if input_source == "host" and self._host_recorder is not None:
            self._host_recorder.deleteLater()
            self._host_recorder = None
        elif input_source == "speaker" and self._speaker_recorder is not None:
            self._speaker_recorder.deleteLater()
            self._speaker_recorder = None
    
    def cleanup(self):
        """Clean up resources."""
        if self._host_recorder is not None and self._host_recorder.isRunning():
            self._host_recorder.stop()
            self._host_recorder.wait(3000)
            self._host_recorder = None
        
        if self._speaker_recorder is not None and self._speaker_recorder.isRunning():
            self._speaker_recorder.stop()
            self._speaker_recorder.wait(3000)
            self._speaker_recorder = None
