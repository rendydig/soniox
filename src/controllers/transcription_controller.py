from PySide6.QtCore import QObject, Signal
from src.workers import SonioxWorker


class TranscriptionController(QObject):
    """Handles transcription and live translation logic."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    transcription_update = Signal(str, bool)
    session_started = Signal()
    session_stopped = Signal()
    
    def __init__(self):
        super().__init__()
        self._soniox_worker = None
        self._transcribing = False
        self._current_mode = "transcription"
        self._target_lang = None
    
    def is_transcribing(self):
        """Check if currently transcribing."""
        return self._transcribing
    
    def get_current_mode(self):
        """Get the current mode (transcription or translation)."""
        return self._current_mode
    
    def start_session(self, device_id: int, mode: str = "transcription", target_lang: str = None):
        """
        Start a transcription or translation session.
        
        Args:
            device_id: Audio input device ID
            mode: Either "transcription" or "translation"
            target_lang: Target language code for translation mode
        """
        if self._transcribing:
            self.error_occurred.emit("Already transcribing")
            return False
        
        try:
            self._current_mode = mode
            self._target_lang = target_lang
            
            self._soniox_worker = SonioxWorker(device_id, mode=mode, target_lang=target_lang)
            self._soniox_worker.transcription_update.connect(self._on_transcription_update)
            self._soniox_worker.status.connect(self.status_changed)
            self._soniox_worker.error.connect(self._on_error)
            self._soniox_worker.finished.connect(self._on_worker_finished)
            
            self._soniox_worker.start()
            self._transcribing = True
            self.session_started.emit()
            
            status_text = "Translating..." if mode == "translation" else "Transcribing..."
            self.status_changed.emit(status_text)
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start session: {e}")
            self._soniox_worker = None
            return False
    
    def stop_session(self):
        """Stop the current transcription/translation session."""
        if self._soniox_worker:
            self._soniox_worker.stop()
        
        self._transcribing = False
        self.session_stopped.emit()
        self.status_changed.emit("Stopped")
    
    def _on_transcription_update(self, text: str, is_final: bool):
        """Handle transcription updates from worker."""
        self.transcription_update.emit(text, is_final)
        
        if not is_final and text.strip():
            self.status_changed.emit(f"Live: {text}")
        elif not is_final:
            self.status_changed.emit("Listening...")
    
    def _on_error(self, msg: str):
        """Handle errors from worker."""
        self._transcribing = False
        self._soniox_worker = None
        self.error_occurred.emit(msg)
        self.session_stopped.emit()
    
    def _on_worker_finished(self):
        """Handle worker thread finished."""
        if self._soniox_worker is not None:
            self._soniox_worker.deleteLater()
            self._soniox_worker = None
    
    def cleanup(self):
        """Clean up resources."""
        if self._soniox_worker is not None and self._soniox_worker.isRunning():
            self._soniox_worker.stop()
            self._soniox_worker.wait(3000)
            self._soniox_worker = None
