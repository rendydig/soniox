from PySide6.QtCore import QObject, Signal, Qt, QTimer
from src.gemini_worker import GeminiWorker, GeminiAutoReplyWorker


class TranslationController(QObject):
    """Handles Gemini-based text translation."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    translation_result = Signal(str)
    translation_started = Signal()
    translation_completed = Signal()
    auto_reply_result = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._gemini_worker = None
        self._auto_reply_worker = None
        self._auto_reply_timer = QTimer()
        self._auto_reply_timer.setSingleShot(True)
        self._auto_reply_timer.timeout.connect(self._trigger_auto_reply)
        self._pending_transcription = ""
        self._pending_context = ""
        self._auto_reply_target_language = "English"
    
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
        if self._gemini_worker is not None:
            self._gemini_worker.wait(1000)
            self._gemini_worker = None
        self.translation_result.emit(result)
        self.translation_completed.emit()
        self.status_changed.emit("Translation complete.")
    
    def _on_error(self, msg: str):
        """Handle errors from worker."""
        if self._gemini_worker is not None:
            self._gemini_worker.wait(1000)
            self._gemini_worker = None
        self.error_occurred.emit(msg)
        self.translation_completed.emit()
        self.status_changed.emit("Translation error.")
    
    def set_auto_reply_language(self, target_language: str):
        """Set the target language for auto-reply."""
        self._auto_reply_target_language = target_language
    
    def schedule_auto_reply(self, transcription_text: str, additional_context: str = ""):
        """
        Schedule an auto-reply after 2 seconds of no new transcription.
        
        Args:
            transcription_text: The transcribed text to respond to
            additional_context: Optional additional context (e.g., from translation input field)
        """
        print(f"[DEBUG TranslationController] schedule_auto_reply called with: '{transcription_text}'")
        if additional_context:
            print(f"[DEBUG TranslationController] Additional context: '{additional_context[:50]}...'")
        self._pending_transcription = transcription_text
        self._pending_context = additional_context
        self._auto_reply_timer.stop()
        self._auto_reply_timer.start(2000)
        print(f"[DEBUG TranslationController] Timer started for 2000ms")
    
    def cancel_auto_reply(self):
        """Cancel any pending auto-reply."""
        print(f"[DEBUG TranslationController] cancel_auto_reply called")
        self._auto_reply_timer.stop()
        self._pending_transcription = ""
        self._pending_context = ""
    
    def _trigger_auto_reply(self):
        """Trigger the auto-reply after debounce period."""
        print(f"[DEBUG TranslationController] _trigger_auto_reply called! Pending text: '{self._pending_transcription}'")
        
        if not self._pending_transcription.strip():
            print(f"[DEBUG TranslationController] No pending transcription, aborting")
            return
        
        if self._auto_reply_worker is not None and self._auto_reply_worker.isRunning():
            print(f"[DEBUG TranslationController] Auto-reply worker already running, aborting")
            return
        
        try:
            print(f"[DEBUG TranslationController] Creating GeminiAutoReplyWorker with language: {self._auto_reply_target_language}")
            self._auto_reply_worker = GeminiAutoReplyWorker(
                self._pending_transcription, 
                self._auto_reply_target_language,
                self._pending_context
            )
            self._auto_reply_worker.result.connect(self._on_auto_reply_result, Qt.ConnectionType.QueuedConnection)
            self._auto_reply_worker.error.connect(self._on_auto_reply_error, Qt.ConnectionType.QueuedConnection)
            
            self.status_changed.emit(f"Auto-replying to: {self._pending_transcription[:50]}...")
            self._auto_reply_worker.start()
            print(f"[DEBUG TranslationController] Auto-reply worker started!")
            
        except Exception as e:
            print(f"[DEBUG TranslationController] Exception in _trigger_auto_reply: {e}")
            self.error_occurred.emit(f"Failed to start auto-reply: {e}")
            self._auto_reply_worker = None
    
    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result from worker."""
        print(f"[DEBUG TranslationController] Auto-reply result received: '{result[:100]}...'")
        if self._auto_reply_worker is not None:
            self._auto_reply_worker.wait(1000)
            self._auto_reply_worker = None
        self.auto_reply_result.emit(result)
        self.status_changed.emit("Auto-reply complete.")
    
    def _on_auto_reply_error(self, msg: str):
        """Handle errors from auto-reply worker."""
        print(f"[DEBUG TranslationController] Auto-reply error: {msg}")
        if self._auto_reply_worker is not None:
            self._auto_reply_worker.wait(1000)
            self._auto_reply_worker = None
        self.error_occurred.emit(msg)
        self.status_changed.emit("Auto-reply error.")
    
    def cleanup(self):
        """Clean up resources."""
        self._auto_reply_timer.stop()
        if self._gemini_worker is not None:
            if self._gemini_worker.isRunning():
                self._gemini_worker.stop()
                self._gemini_worker.wait(3000)
                if self._gemini_worker.isRunning():
                    self._gemini_worker.terminate()
            self._gemini_worker = None
        if self._auto_reply_worker is not None:
            if self._auto_reply_worker.isRunning():
                self._auto_reply_worker.stop()
                self._auto_reply_worker.wait(3000)
                if self._auto_reply_worker.isRunning():
                    self._auto_reply_worker.terminate()
            self._auto_reply_worker = None
