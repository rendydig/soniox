from PySide6.QtCore import QObject, Signal, Qt
from src.gemini_worker import GeminiWorker


class TranslationController(QObject):
    """Handles Gemini-based text translation."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    translation_result = Signal(str)
    translation_started = Signal()
    translation_completed = Signal()
    
    def __init__(self):
        super().__init__()
        self._gemini_worker = None
    
    def is_translating(self):
        """Check if currently translating."""
        return self._gemini_worker is not None and self._gemini_worker.isRunning()
    
    def translate_text(self, text: str, target_language: str):
        """
        Translate text using Gemini API.
        
        Args:
            text: Text to translate
            target_language: Target language name (e.g., "English", "Arabic")
        """
        if not text.strip():
            self.error_occurred.emit("No text provided for translation")
            return False
        
        if self.is_translating():
            self.error_occurred.emit("Translation already in progress")
            return False
        
        try:
            self._gemini_worker = GeminiWorker(text, target_language)
            self._gemini_worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._gemini_worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            
            self.translation_started.emit()
            self.status_changed.emit(f"Translating to {target_language}...")
            self._gemini_worker.start()
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"Failed to start translation: {e}")
            self._gemini_worker = None
            return False
    
    def _on_result(self, result: str):
        """Handle translation result from worker."""
        self._gemini_worker = None
        self.translation_result.emit(result)
        self.translation_completed.emit()
        self.status_changed.emit("Translation complete.")
    
    def _on_error(self, msg: str):
        """Handle errors from worker."""
        self._gemini_worker = None
        self.error_occurred.emit(msg)
        self.translation_completed.emit()
        self.status_changed.emit("Translation error.")
    
    def cleanup(self):
        """Clean up resources."""
        if self._gemini_worker is not None and self._gemini_worker.isRunning():
            self._gemini_worker.wait(3000)
            self._gemini_worker = None
