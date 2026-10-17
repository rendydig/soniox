import json
import logging

from PySide6.QtCore import QThread, Signal

from src import ai_debug
from src.ai_client import get_ai_client
from src.config import SUMMARY_MAX_LINE_CHARS
from src.reference_context import render_reference_context

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You write a concise, structured summary of a live two-person \
conversation that has just finished.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- Capture meaning, not narration: explicitly IGNORE greetings, filler, acknowledgements,
  and turn-by-turn narration ("host pauses", "speaker agrees", "they continue talking").
- Merge aggressively into dense, standalone points; never pad to one point per line.
- Write the summary in the same language as the conversation. Keep proper nouns as-is.
- REFERENCE CONTEXT: when the user message carries a "Reference context" block it is
  background about the two participants. Use it to interpret the conversation; never add
  anything from it as a finding. A pre-identified profile is not something the speaker said.
- Return GitHub-flavoured Markdown with EXACTLY these section headings, in this order, and
  nothing else (no preamble, no closing remarks, no code fences):
  ## Overview
  ## Key Points
  ## Decisions
  ## Open Questions
  ## Next Steps
  ## Speaker Highlights
- "## Overview" is one short paragraph. The other sections are bullet lists when there is
  more than one item, a single sentence otherwise.
- "## Speaker Highlights" summarises who the [speaker] is and what matters to them, drawing
  on the speaker profile and their own lines.
- OMIT a section entirely when the conversation produced nothing for it — do not write
  "N/A", "None", or an empty bullet list.
- If the whole conversation has no substance, return only "## Overview" with one sentence."""


class SummarizeWorker(QThread):
    """Summarise a whole session: transcript + bullet list + speaker profile."""

    result = Signal(str)
    error = Signal(str)

    def __init__(self, lines: list, bullets: list, speaker: dict, parent=None,
                 context: dict = None):
        super().__init__(parent)
        self._lines = list(lines or [])
        self._bullets = list(bullets or [])
        self._speaker = dict(speaker or {})
        # Host/Speaker reference context (the Context pane's file, or its
        # compacted variant): interpretation only, per the system instruction.
        self._context = context if isinstance(context, dict) else {}
        self._is_running = True

    def _build_user_message(self) -> str:
        # Lines are ``(source, text)`` or ``(source, text, timestamp)``; only the
        # first two fields matter to the prompt. Each line is truncated for token
        # safety (the transcript itself is already capped by the session store).
        rendered = []
        for entry in self._lines:
            try:
                source, text = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            rendered.append(f"[{source}] {str(text)[:SUMMARY_MAX_LINE_CHARS]}")
        transcript = "\n".join(rendered)
        bullets_json = json.dumps(self._bullets, ensure_ascii=False)
        speaker_json = json.dumps(self._speaker, ensure_ascii=False)
        return (
            f"{render_reference_context(self._context)}"
            f"Conversation transcript:\n{transcript}\n\n"
            f"Bullet points (JSON): {bullets_json}\n\n"
            f"Speaker profile (JSON): {speaker_json}"
        )

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()
            user_message = self._build_user_message()
            call_id = ai_debug.log_request(
                "summary", SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                meta={"lines": len(self._lines), "bullets": len(self._bullets)},
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
                self.error.emit(f"Summarize error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
