import json
import logging

from PySide6.QtCore import QThread, Signal

from src.ai_client import get_ai_client
from src.config import (
    BULLET_MAX_ITEMS,
    BULLET_MAX_LINE_CHARS,
    SPEAKER_MAX_LIST_ITEMS,
)

logger = logging.getLogger(__name__)

# Profile schema: three labelled scalar rows + four short lists.
SPEAKER_SCALAR_FIELDS = ("name", "location", "occupation")
SPEAKER_LIST_FIELDS = ("interests", "goals", "pain_points", "facts")
SPEAKER_FIELDS = SPEAKER_SCALAR_FIELDS + SPEAKER_LIST_FIELDS

SYSTEM_INSTRUCTION = f"""You maintain a concise, running bullet-point list of the SUBSTANCE of a \
live two-person conversation, AND a short structured "Know Your Customer" profile of the \
[speaker]. Extract meaning, not narration.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- You receive the CURRENT bullet list, the CURRENT speaker profile, and NEW conversation lines.
- Capture only topics, decisions, facts, numbers, open questions, and action items.
- Explicitly IGNORE greetings, filler, acknowledgements, and turn-by-turn narration
  ("host pauses", "speaker agrees", "they continue talking").
- Merge aggressively: prefer FEWER, DENSER bullets over many thin ones. Never pad the
  list to one bullet per line. For pure small talk an empty or very short list is correct.
- Return the full UPDATED list: keep existing points that are still valid, merge/refine
  related ones, drop duplicates, and add points for the new lines.
- Each bullet is a short standalone phrase (max ~12 words). No numbering, no sub-bullets.
- Keep at most {BULLET_MAX_ITEMS} of the most important points.
- Write each bullet in the same language as the conversation it summarises. Keep proper nouns as-is.

Speaker profile (JSON object):
- The host is "us"; the [speaker] is the customer. Only the [speaker] is profiled.
- Fields: "name", "location", "occupation" (strings) and "interests", "goals",
  "pain_points", "facts" (arrays of short strings).
- "facts" are only extracted from [speaker] lines: who they are, where from, what they
  do, life/context details worth remembering.
- "pain_points" are problems, frustrations, complaints, and unmet needs the speaker
  mentions mid-conversation.
- Update a field ONLY when the speaker actually reveals it. NEVER guess or infer a
  value that was not said. Keep an unknown field as "" / [].
- For lists: merge with what you already have, drop duplicates, keep each entry a short
  standalone phrase (max ~10 words), at most {SPEAKER_MAX_LIST_ITEMS} entries per list
  (keep the most important), and write them in the conversation's language.
- When nothing new is revealed, return the profile unchanged.

Return ONLY a JSON object with this exact shape and no prose, explanations, or code fences:
{{"bullets": ["First point", "Second point"],
  "speaker": {{"name": "", "location": "", "occupation": "",
               "interests": [], "goals": [], "pain_points": [], "facts": []}}}}"""


def _clean_text(value) -> str:
    """Coerce a scalar profile value to a stripped string (``""`` when unusable)."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _clean_list(value) -> list:
    """Coerce a profile list field to a list of non-empty strings, capped."""
    if not isinstance(value, list):
        return []
    items = []
    for entry in value:
        text = _clean_text(entry)
        if text:
            items.append(text)
        if len(items) >= SPEAKER_MAX_LIST_ITEMS:
            break
    return items


def _sanitize_speaker(data) -> dict:
    """Keep only the known profile fields, coerced to the right types."""
    if not isinstance(data, dict):
        return {}
    speaker = {}
    for field in SPEAKER_SCALAR_FIELDS:
        speaker[field] = _clean_text(data.get(field))
    for field in SPEAKER_LIST_FIELDS:
        speaker[field] = _clean_list(data.get(field))
    return speaker


def _parse_result_json(text: str):
    """Parse the model's reply into ``{"items": [...], "speaker": {...}}``.

    Tolerates code fences and surrounding prose by slicing the first ``{`` to the
    last ``}`` (falling back to ``[``..``]`` for a bare JSON array — a model that
    ignores the new object format still yields bullets with an empty profile).
    Returns ``None`` when nothing valid can be recovered, so the caller can keep
    the previous state instead of clearing it.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Drop the opening fence (and optional language) and the closing fence.
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    def _loads(fragment):
        try:
            return json.loads(fragment)
        except (ValueError, TypeError):
            return None

    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        data = _loads(cleaned[start:end + 1])
        if isinstance(data, dict):
            bullets = data.get("bullets")
            # Tolerate a bare object of speaker fields (model dropped "bullets").
            if not isinstance(bullets, list):
                bullets = []
            items = [str(item).strip() for item in bullets if str(item).strip()]
            return {"items": items, "speaker": _sanitize_speaker(data.get("speaker"))}

    # Fallback: a plain JSON array of bullets, profile left empty.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    data = _loads(cleaned[start:end + 1])
    if not isinstance(data, list):
        return None
    items = [str(item).strip() for item in data if str(item).strip()]
    return {"items": items, "speaker": {}}


class BulletPointsWorker(QThread):
    """Recompute the rolling bullet list + speaker profile from state + new lines."""

    result = Signal(dict)
    error = Signal(str)

    def __init__(self, current_bullets: list, current_speaker: dict, new_lines: list,
                 parent=None, rebuild: bool = False):
        super().__init__(parent)
        self._current_bullets = list(current_bullets or [])
        self._current_speaker = dict(current_speaker or {})
        self._new_lines = list(new_lines or [])
        self._rebuild = rebuild
        self._is_running = True

    def _build_user_message(self) -> str:
        lines = "\n".join(
            f"[{source}] {text[:BULLET_MAX_LINE_CHARS]}"
            for source, text in self._new_lines
        )
        if self._rebuild:
            # Whole-transcript rebuild: no inherited list/profile, start from scratch.
            return f"Full conversation transcript:\n{lines}"
        bullets_json = json.dumps(self._current_bullets, ensure_ascii=False)
        speaker_json = json.dumps(self._current_speaker, ensure_ascii=False)
        return (
            f"Current bullet list (JSON): {bullets_json}\n\n"
            f"Current speaker profile (JSON): {speaker_json}\n\n"
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

            parsed = _parse_result_json(response)
            if parsed is None:
                self.error.emit("Could not parse bullet points from the AI response")
            else:
                self.result.emit({
                    "items": parsed["items"][:BULLET_MAX_ITEMS],
                    "speaker": parsed["speaker"],
                })
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Bullet points error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
