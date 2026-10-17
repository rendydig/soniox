import logging

from PySide6.QtCore import QThread, Signal

from src import ai_debug
from src.ai_client import get_ai_client
from src.config import BULLET_MAX_LINE_CHARS
from src.reference_context import render_reference_context

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You listen to a live two-person conversation and pick up the LATEST \
thing the speaker is trying to convey.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- Focus on the most recent [speaker] message(s): what they are trying to say, asking, or confirming.
- Ignore greetings, filler, and small talk with no substance.
- Answer with one or two paragraphs separated by a blank line:
  1. First paragraph: detailed sentence(s) in natural, everyday Bahasa Indonesia that capture
     that latest topic/intent.
  2. Second paragraph: the SAME meaning written in the language the Speaker is actually using,
     prefixed with that language's English name and a colon (e.g. "English: ..."). Include this
     paragraph ONLY when the Speaker's language is not Indonesian; if the Speaker is speaking
     Indonesian, output only the first paragraph.
- No preamble, no quotes, no reasoning. The only label allowed is the language name on the
  second paragraph.
- If there is nothing meaningful to pick up, return an empty string.
- REFERENCE CONTEXT: when the user message carries a "Reference context" block it is
  background about the two participants (jargon, acronyms, what a product or project is).
  Use it to interpret what the speaker means; never read the block back out as the pickup."""


class LastPickupWorker(QThread):
    """Extract the latest speaker topic/intent from a window of conversation lines."""

    result = Signal(str)
    error = Signal(str)

    def __init__(self, lines: list, parent=None, context: dict = None):
        super().__init__(parent)
        self._lines = list(lines or [])
        # Host/Speaker reference context (the Context pane's file, or its
        # compacted variant): interpretation only, per the system instruction.
        self._context = context if isinstance(context, dict) else {}
        self._is_running = True

    def _build_user_message(self) -> str:
        lines = "\n".join(
            f"[{source}] {text[:BULLET_MAX_LINE_CHARS]}"
            for source, text in self._lines
        )
        reference = render_reference_context(self._context)
        return f"{reference}Latest conversation lines:\n{lines}"

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()
            user_message = self._build_user_message()
            call_id = ai_debug.log_request(
                "last_pickup", SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                meta={"lines": len(self._lines)},
            )
            response = client.generate(
                SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                disable_reasoning=True,
            )
            ai_debug.log_reply(call_id, response)

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
