"""Compact a Host/Speaker context file with one AI call.

The Context pane's **Compact** button runs this once: it rewrites a long context
file as a shorter version of itself, keeping every fact the reply path could
need, and the result is stored beside the real file as `<file>.compacted` (see
``websocket-server/context-store.js``). It is manual only — one press, one call —
so the cost is bounded per click, and the compacted copy is *chosen* by the user
(``context_set_variant``), never silently substituted.
"""

import logging

from PySide6.QtCore import QThread, Signal

from src import ai_debug
from src.ai_client import get_ai_client

logger = logging.getLogger(__name__)

ROLE_LABELS = {"host": "Host", "speaker": "Speaker"}

SYSTEM_INSTRUCTION = """You compress a reference document so a live assistant can still \
carry it in full on every AI call.

Rules:
- Keep EVERY fact, name, number, date, price, constraint, commitment, offer,
  integration, terminology, and stated preference. Losing a fact is the one
  failure that matters.
- Cut only what is redundant: repetition, pleasantries, marketing adjectives,
  examples that add no new information, and prose that can be a bullet list
  instead.
- Preserve the document's own structure and language: if it is English, answer in
  English; if it is a bullet list, keep it a bullet list; keep headings that group
  the content.
- Never invent, generalise, or add anything that is not in the source.
- Aim for roughly half the original length or less, but never at the cost of a
  fact.
- Return ONLY the compacted document: no preamble, no explanation, no code
  fences, no commentary about what you did."""


class ContextCompactWorker(QThread):
    """Rewrite one role's context text as a shorter, fact-complete version."""

    result = Signal(str, str, str)   # role, source_path, compacted text
    error = Signal(str, str)         # role, message

    def __init__(self, role: str, text: str, source_path: str = "", parent=None):
        super().__init__(parent)
        self._role = str(role or "")
        self._text = str(text or "")
        self._source_path = str(source_path or "")
        self._is_running = True

    def run(self):
        try:
            if not self._is_running:
                return
            client = get_ai_client()
            label = ROLE_LABELS.get(self._role, self._role or "context")
            user_message = (
                f"The document below is the {label} context used by a live assistant.\n"
                f"Compact it.\n\n"
                f"--- begin document ---\n{self._text}\n--- end document ---"
            )
            call_id = ai_debug.log_request(
                "context_compact", SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                meta={"role": self._role, "chars": len(self._text)},
            )
            response = client.generate(
                SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                disable_reasoning=True,
            )
            ai_debug.log_reply(call_id, response)

            if not self._is_running:
                return

            text = (response or "").strip()
            if not text:
                self.error.emit(self._role, "The AI returned nothing to compact")
                return
            logger.info("Context compacted: role=%s %d -> %d chars",
                        self._role, len(self._text), len(text))
            self.result.emit(self._role, self._source_path, text)
        except Exception as e:
            if self._is_running:
                self.error.emit(self._role, f"Compaction error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
