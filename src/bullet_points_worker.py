import json
import logging

from PySide6.QtCore import QThread, Signal

from src.ai_client import get_ai_client
from src.config import BULLET_MAX_ITEMS, BULLET_MAX_LINE_CHARS

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = f"""You maintain a concise, running bullet-point list of the SUBSTANCE of a \
live two-person conversation. Extract meaning, not narration.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- You receive the CURRENT bullet list and NEW conversation lines.
- Capture only topics, decisions, facts, numbers, open questions, and action items.
- Explicitly IGNORE greetings, filler, acknowledgements, and turn-by-turn narration
  ("host pauses", "speaker agrees", "they continue talking").
- Merge aggressively: prefer FEWER, DENSER bullets over many thin ones. Never pad the
  list to one bullet per line. For pure small talk an empty or very short list is correct.
- Return the full UPDATED list: keep existing points that are still valid, merge/refine
  related ones, drop duplicates, and add points for the new lines.
- Each bullet is a short standalone phrase (max ~12 words). No numbering, no sub-bullets.
- Keep at most {BULLET_MAX_ITEMS} of the most important points.
- Write the bullets in clear English.
- Return ONLY a JSON array of strings, e.g. ["First point", "Second point"].
  Do not include prose, explanations, or code fences."""


def _parse_bullet_json(text: str):
    """Parse the model's reply into a list of bullet strings.

    Tolerates code fences and surrounding prose by slicing the first ``[`` to the
    last ``]``. Returns ``None`` when no valid list can be recovered, so the
    caller can keep the previous list instead of clearing it.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (and optional language) and the closing fence.
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    items = [str(item).strip() for item in data if str(item).strip()]
    return items or None


class BulletPointsWorker(QThread):
    """Recompute the rolling bullet list from the current list + new lines."""

    result = Signal(list)
    error = Signal(str)

    def __init__(self, current_bullets: list, new_lines: list, parent=None, rebuild: bool = False):
        super().__init__(parent)
        self._current_bullets = list(current_bullets or [])
        self._new_lines = list(new_lines or [])
        self._rebuild = rebuild
        self._is_running = True

    def _build_user_message(self) -> str:
        lines = "\n".join(
            f"[{source}] {text[:BULLET_MAX_LINE_CHARS]}"
            for source, text in self._new_lines
        )
        if self._rebuild:
            # Whole-transcript rebuild: no inherited list, summarise from scratch.
            return f"Full conversation transcript:\n{lines}"
        bullets_json = json.dumps(self._current_bullets, ensure_ascii=False)
        return (
            f"Current bullet list (JSON): {bullets_json}\n\n"
            f"New conversation lines:\n{lines}"
        )

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

            items = _parse_bullet_json(response)
            if items is None:
                self.error.emit("Could not parse bullet points from the AI response")
            else:
                self.result.emit(items[:BULLET_MAX_ITEMS])
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Bullet points error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
