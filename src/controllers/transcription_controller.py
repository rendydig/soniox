from PySide6.QtCore import QObject, Signal
from src.workers import SonioxWorker


class TranscriptionController(QObject):
    """Handles transcription and live translation logic."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    transcription_update = Signal(str, bool, str)
    translation_update = Signal(str, bool, str)
    session_started = Signal()
    session_stopped = Signal()
    
    def __init__(self):
        super().__init__()
        self._host_worker = None
        self._speaker_worker = None
        self._transcribing = False
        self._current_mode = "transcription"
        self._target_lang = None
    
    def is_transcribing(self):
        """Check if currently transcribing."""
        return self._transcribing
    
    def get_current_mode(self):
        """Get the current mode (transcription or translation)."""
        return self._current_mode
    
    def start_session(self, host_device_id: int, speaker_device_id: int = None, mode: str = "transcription", target_lang: str = None):
        """
        Start a transcription or translation session with dual audio inputs.
        
        Args:
            host_device_id: Audio input device ID for host
            speaker_device_id: Audio input device ID for speaker (optional)
            mode: Either "transcription" or "translation"
            target_lang: Target language code for translation mode
        """
        if self._transcribing:
            self.error_occurred.emit("Already transcribing")
            return False
        
        try:
            self._current_mode = mode
            self._target_lang = target_lang
            
            # Create host worker
            self._host_worker = SonioxWorker(host_device_id, mode=mode, target_lang=target_lang, input_source="host")
            self._host_worker.transcription_update.connect(self._on_transcription_update)
            self._host_worker.translation_update.connect(self._on_translation_update)
            self._host_worker.status.connect(self._on_status_update)
            self._host_worker.error.connect(self._on_error)
            self._host_worker.finished.connect(lambda: self._on_worker_finished("host"))
            
            self._host_worker.start()
            
            # Create speaker worker if device is provided
            if speaker_device_id is not None:
                self._speaker_worker = SonioxWorker(speaker_device_id, mode=mode, target_lang=target_lang, input_source="speaker")
                self._speaker_worker.transcription_update.connect(self._on_transcription_update)
                self._speaker_worker.translation_update.connect(self._on_translation_update)
                self._speaker_worker.status.connect(self._on_status_update)
                self._speaker_worker.error.connect(self._on_error)
                self._speaker_worker.finished.connect(lambda: self._on_worker_finished("speaker"))
                
                self._speaker_worker.start()
            
            self._transcribing = True
            self.session_started.emit()
            
            status_text = "Translating..." if mode == "translation" else "Transcribing..."
            self.status_changed.emit(status_text)
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start session: {e}")
            self._host_worker = None
            self._speaker_worker = None
            return False
    
    def stop_session(self):
        """Stop the current transcription/translation session."""
        if self._host_worker:
            self._host_worker.stop()
        
        if self._speaker_worker:
            self._speaker_worker.stop()
        
        self._transcribing = False
        self.session_stopped.emit()
        self.status_changed.emit("Stopped")
    
    def _on_transcription_update(self, text: str, is_final: bool, input_source: str):
        """Handle transcription updates from worker."""
        self.transcription_update.emit(text, is_final, input_source)
        
        if not is_final and text.strip():
            self.status_changed.emit(f"Live [{input_source}]: {text}")
        elif not is_final:
            self.status_changed.emit("Listening...")
    
    def _on_translation_update(self, text: str, is_final: bool, input_source: str):
        """Handle translation updates from worker."""
        self.translation_update.emit(text, is_final, input_source)
    
    def _on_status_update(self, status: str, input_source: str):
        """Handle status updates from workers."""
        self.status_changed.emit(f"[{input_source}] {status}")
    
    def _on_error(self, msg: str, input_source: str):
        """Handle errors from worker."""
        self.error_occurred.emit(f"[{input_source}] {msg}")
        
        # Stop both workers on error
        if self._host_worker:
            self._host_worker.stop()
        if self._speaker_worker:
            self._speaker_worker.stop()
        
        self._transcribing = False
        self._host_worker = None
        self._speaker_worker = None
        self.session_stopped.emit()
    
    def _on_worker_finished(self, input_source: str):
        """Handle worker thread finished."""
        if input_source == "host" and self._host_worker is not None:
            self._host_worker.deleteLater()
            self._host_worker = None
        elif input_source == "speaker" and self._speaker_worker is not None:
            self._speaker_worker.deleteLater()
            self._speaker_worker = None
    
    def cleanup(self):
        """Clean up resources."""
        if self._host_worker is not None and self._host_worker.isRunning():
            self._host_worker.stop()
            self._host_worker.wait(3000)
            self._host_worker = None
        
        if self._speaker_worker is not None and self._speaker_worker.isRunning():
            self._speaker_worker.stop()
            self._speaker_worker.wait(3000)
            self._speaker_worker = None
