import logging

from PySide6.QtCore import QThread, Signal

from src.ai_client import get_ai_client
from src.config import BULLET_MAX_LINE_CHARS

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You listen to a live two-person conversation and pick up the LATEST \
thing the speaker is trying to convey.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- Focus on the most recent [speaker] message(s): what they are trying to say, asking, or confirming.
- Ignore greetings, filler, and small talk with no substance.
- Answer with detailed sentence(s) in Bahasa Indonesia that captures that latest topic/intent.
- Write natural, everyday Indonesian. No preamble, no quotes, no labels, no reasoning.
- If there is nothing meaningful to pick up, return an empty string."""


class LastPickupWorker(QThread):
    """Extract the latest speaker topic/intent from a window of conversation lines."""

    result = Signal(str)
    error = Signal(str)

    def __init__(self, lines: list, parent=None):
        super().__init__(parent)
        self._lines = list(lines or [])
        self._is_running = True

    def _build_user_message(self) -> str:
        lines = "\n".join(
            f"[{source}] {text[:BULLET_MAX_LINE_CHARS]}"
            for source, text in self._lines
        )
        return f"Latest conversation lines:\n{lines}"

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()
            response = client.generate(
                SYSTEM_INSTRUCTION,
                [{"role": "user", "text": self._build_user_message()}],
                disable_reasoning=True,
            )

            if not self._is_running:
                return

            if response is None:
                self.error.emit("Empty response received from the AI provider")
            else:
                self.result.emit((response or "").strip())
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Last pickup error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
