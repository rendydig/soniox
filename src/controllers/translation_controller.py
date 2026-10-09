import os
import logging
from datetime import datetime
from PySide6.QtCore import QObject, Signal, Qt, QTimer
from src.gemini_worker import GeminiWorker, GeminiAutoReplyWorker
from src.config import AUTO_REPLY_DEBOUNCE_MS
from src.purposes import DEFAULT_PURPOSE

logger = logging.getLogger(__name__)


class TranslationController(QObject):
    """Handles Gemini-based text translation."""
    
    status_changed = Signal(str)
    error_occurred = Signal(str)
    translation_result = Signal(str)
    translation_started = Signal()
    translation_completed = Signal()
    auto_reply_result = Signal(str)
    image_reply_result = Signal(str)
    reply_chunk = Signal(str, bool)
    
    MAX_HISTORY_TURNS = 25
    HISTORY_LOG_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "logs",
        "conversation_history.log"
    )

    def __init__(self):
        super().__init__()
        self._gemini_worker = None
        self._auto_reply_worker = None
        self._old_workers = []
        self._auto_reply_timer = QTimer()
        self._auto_reply_timer.setSingleShot(True)
        self._auto_reply_timer.timeout.connect(self._trigger_auto_reply)
        self._pending_transcription = ""
        self._pending_input_source = "speaker"
        self._auto_reply_target_language = "English"
        self._include_pronunciation = False
        self._auto_reply_purpose = DEFAULT_PURPOSE
        self._conversation_history = []
        self._auto_reply_is_image = False
    
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
            self._cleanup_old_workers()
            self._gemini_worker = None
        self.translation_result.emit(result)
        self.translation_completed.emit()
        self.status_changed.emit("Translation complete.")
    
    def _on_error(self, msg: str):
        """Handle errors from worker."""
        if self._gemini_worker is not None:
            self._gemini_worker.wait(1000)
            self._cleanup_old_workers()
            self._gemini_worker = None
        self.error_occurred.emit(msg)
        self.translation_completed.emit()
        self.status_changed.emit("Translation error.")
    
    def set_auto_reply_language(self, target_language: str):
        """Set the target language for auto-reply."""
        self._auto_reply_target_language = target_language
    
    def set_pronunciation_enabled(self, enabled: bool):
        """Set whether auto-reply includes syllables/pronunciation and English translation."""
        self._include_pronunciation = enabled
    
    def set_auto_reply_purpose(self, purpose: str):
        """Set the purpose/persona used for the auto-reply."""
        self._auto_reply_purpose = purpose
    
    def schedule_auto_reply(self, transcription_text: str, input_source: str = "speaker", delay_ms: int = None):
        """
        Schedule an auto-reply after a short period of no new transcription.

        Args:
            transcription_text: The transcribed text to respond to
            input_source: Who said this text — "host" (you) or "speaker" (the other person)
            delay_ms: Debounce delay; defaults to AUTO_REPLY_DEBOUNCE_MS. Pass a
                smaller value (e.g. 0) for an endpoint-marked end of utterance.
        """
        delay_ms = AUTO_REPLY_DEBOUNCE_MS if delay_ms is None else delay_ms
        logger.debug("schedule_auto_reply called with: %r (from %s)", transcription_text, input_source)
        self._pending_transcription = transcription_text
        self._pending_input_source = input_source
        self._auto_reply_timer.stop()
        self._auto_reply_timer.start(delay_ms)
        logger.debug("Timer started for %dms", delay_ms)
    
    def trigger_reply_now(self, transcription_text: str = None, input_source: str = "speaker"):
        """Trigger a Gemini reply immediately without debounce timer."""
        if transcription_text is not None:
            self._pending_transcription = transcription_text
        self._pending_input_source = input_source
        self._auto_reply_timer.stop()
        self._trigger_auto_reply()

    def cancel_auto_reply(self):
        """Cancel any pending auto-reply."""
        logger.debug("cancel_auto_reply called")
        self._auto_reply_timer.stop()
        self._pending_transcription = ""
        self._pending_input_source = "speaker"
    
    def _start_auto_reply_worker(self, transcription_text: str, images: list = None, is_image: bool = False):
        """Create and start a Gemini auto-reply worker. Returns True if started."""
        if self._auto_reply_worker is not None and self._auto_reply_worker.isRunning():
            logger.debug("Auto-reply worker already running, aborting")
            return False

        try:
            logger.debug("Creating GeminiAutoReplyWorker with language: %s", self._auto_reply_target_language)
            self._auto_reply_is_image = is_image
            self._auto_reply_worker = GeminiAutoReplyWorker(
                transcription_text,
                self._auto_reply_target_language,
                conversation_history=list(self._conversation_history),
                include_pronunciation=self._include_pronunciation,
                purpose=self._auto_reply_purpose,
                images=images
            )
            self._auto_reply_worker.result.connect(self._on_auto_reply_result, Qt.ConnectionType.QueuedConnection)
            self._auto_reply_worker.error.connect(self._on_auto_reply_error, Qt.ConnectionType.QueuedConnection)
            self._auto_reply_worker.chunk.connect(self._on_auto_reply_chunk, Qt.ConnectionType.QueuedConnection)
            self._auto_reply_worker.start()
            return True
        except Exception as e:
            logger.error("Exception starting auto-reply: %s", e)
            self.error_occurred.emit(f"Failed to start auto-reply: {e}")
            self._auto_reply_worker = None
            self._auto_reply_is_image = False
            return False

    def _trigger_auto_reply(self):
        """Trigger the auto-reply after debounce period."""
        logger.debug("_trigger_auto_reply called! Pending text: %r", self._pending_transcription)

        if not self._pending_transcription.strip():
            logger.debug("No pending transcription, aborting")
            return

        if self._start_auto_reply_worker(self._pending_transcription, is_image=False):
            self.status_changed.emit(f"Auto-replying to: {self._pending_transcription[:50]}...")
            logger.debug("Auto-reply worker started!")

    def trigger_image_reply(self, images: list):
        """Send captured screenshots to Gemini using the auto-reply context/format."""
        if not images:
            self.error_occurred.emit("No screenshots to send")
            return False

        self._auto_reply_timer.stop()
        logger.debug("trigger_image_reply called with %d screenshot(s)", len(images))
        if self._start_auto_reply_worker("", images=images, is_image=True):
            self.status_changed.emit(f"Sending {len(images)} screenshot(s) to Gemini...")
            logger.debug("Image reply worker started!")
            return True
        return False
    
    def _on_auto_reply_chunk(self, text: str):
        """Forward a partial (streaming) auto-reply to the UI."""
        self.reply_chunk.emit(text, self._auto_reply_is_image)

    def _on_auto_reply_result(self, result: str):
        """Handle auto-reply result from worker."""
        logger.debug("Auto-reply result received: %r...", result[:100])
        is_image = self._auto_reply_is_image
        self._auto_reply_is_image = False
        if self._auto_reply_worker is not None:
            self._old_workers.append(self._auto_reply_worker)
            self._auto_reply_worker = None
            self._cleanup_old_workers()
        if is_image:
            self.image_reply_result.emit(result)
        else:
            self.auto_reply_result.emit(result)
        self.status_changed.emit("Auto-reply complete.")
    
    def _on_auto_reply_error(self, msg: str):
        """Handle errors from auto-reply worker."""
        logger.error("Auto-reply error: %s", msg)
        self._auto_reply_is_image = False
        if self._auto_reply_worker is not None:
            self._old_workers.append(self._auto_reply_worker)
            self._auto_reply_worker = None
            self._cleanup_old_workers()
        self.error_occurred.emit(msg)
        self.status_changed.emit("Auto-reply error.")
    
    def _cleanup_old_workers(self):
        """Clean up finished workers to prevent memory buildup."""
        workers_to_keep = []
        for worker in self._old_workers:
            if worker.isRunning():
                workers_to_keep.append(worker)
            else:
                worker.deleteLater()
        self._old_workers = workers_to_keep
        
        if len(self._old_workers) > 10:
            for worker in self._old_workers[:5]:
                if worker.isRunning():
                    worker.stop()
                    worker.wait(500)
                worker.deleteLater()
            self._old_workers = self._old_workers[5:]
    
    def clear_conversation_history(self):
        """Clear the conversation history buffer."""
        self._conversation_history.clear()
        logger.debug("Conversation history cleared")

    def load_conversation_history(self, history):
        """Seed the history from a restored session, keeping the last N turns."""
        self._conversation_history = list(history or [])[-self.MAX_HISTORY_TURNS:]
        logger.debug("Conversation history restored: %d turns", len(self._conversation_history))

    def get_conversation_history(self):
        """Return a copy of the current conversation history."""
        return list(self._conversation_history)

    def append_to_history(self, text: str, suggestion: str, input_source: str):
        """Append a conversation turn to history, keeping only last MAX_HISTORY_TURNS."""
        self._conversation_history.append({
            "text": text,
            "role": input_source,
            "suggestion": suggestion
        })
        if len(self._conversation_history) > self.MAX_HISTORY_TURNS:
            self._conversation_history = self._conversation_history[-self.MAX_HISTORY_TURNS:]
        self._log_history_to_file(text, suggestion, input_source)
        logger.debug("History updated: %d turns (last from %s)", len(self._conversation_history), input_source)

    def _log_history_to_file(self, text: str, suggestion: str, input_source: str):
        """Append the conversation turn to a persistent text log file."""
        try:
            os.makedirs(os.path.dirname(self.HISTORY_LOG_FILE), exist_ok=True)
            timestamp = datetime.now().isoformat()
            with open(self.HISTORY_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] source={input_source}\n")
                f.write(f"  text: {text}\n")
                f.write(f"  suggestion: {suggestion}\n")
                f.write("-" * 80 + "\n")
        except Exception as e:
            logger.error("Failed to write history log: %s", e)

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
        
        for worker in self._old_workers:
            if worker.isRunning():
                worker.stop()
                worker.wait(1000)
            worker.deleteLater()
        self._old_workers.clear()
