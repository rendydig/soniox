import os
import time
import logging
from PySide6.QtCore import QThread, Signal
from src.ai_client import get_ai_client, IMAGE_CONTEXT_PROMPT
from src.config import (
    AI_STREAM_CHUNK_INTERVAL_MS,
    SELF_CONTEXT_FILE,
    PRONUNCIATION_GUIDES,
    SAMPLE_TEXTS,
)
from src.purposes import PURPOSES, DEFAULT_PURPOSE

logger = logging.getLogger(__name__)

DEFAULT_SELF_CONTEXT = "bahasa pemograman javascript, react , nextjs, python, docker, kubernetes, aws, gcp, azure, github, gitlab, bitbucket, jenkins, circleci, travis ci, aws lambda, aws s3, aws ec2, aws rds, aws lambda, aws s3, aws ec2, aws rds"


def _build_messages(conversation_history: list, latest_text: str, images: list = None) -> list:
    """Normalize conversation history into provider-neutral messages.

    Returns a list of ``{"role": "user" | "assistant", "text": str, "images": [...]}``
    dicts. Consecutive same-role turns are merged, a leading host turn is dropped
    (so the list starts with a user turn), the latest transcription is appended
    unless already present, and screenshots are attached to the final user turn.
    """
    logger.debug("Contents Length (%d turns):", len(conversation_history))
    for i, turn in enumerate(conversation_history):
        logger.debug("  [%d] role=%s | text=%s | suggestion=%s", i, turn['role'], turn['text'], turn['suggestion'])

    # Merge consecutive turns with the same role to reduce fragmentation/noise
    merged_history = []
    for t in conversation_history:
        role = t.get("role")
        text = (t.get("text") or "").strip()
        # Skip completely empty entries
        if not text:
            continue
        if merged_history and merged_history[-1].get("role") == role:
            # Merge into previous entry
            prev_text = merged_history[-1].get("text", "")
            merged_history[-1]["text"] = (prev_text + "\n" + text).strip() if prev_text else text
        else:
            merged_history.append({
                "role": role,
                "text": text
            })

    # The list must start with a 'user' turn, so drop any leading unpaired host turn.
    if merged_history and merged_history[0].get("role") == "host":
        merged_history.pop(0)

    messages = []
    idx = 0
    while idx < len(merged_history):
        turn = merged_history[idx]
        role = turn.get("role")
        if role == "speaker":
            # The other person's utterance becomes a user message
            speaker_text = turn.get("text", "").strip()
            if speaker_text:
                messages.append({"role": "user", "text": speaker_text})

            # Pair with the host reply if present next
            host_reply_text = None
            if idx + 1 < len(merged_history) and merged_history[idx + 1].get("role") == "host":
                host_reply_text = (merged_history[idx + 1].get("text") or "").strip()
                idx += 1  # consume the paired host turn

            if host_reply_text:
                messages.append({"role": "assistant", "text": host_reply_text})

        elif role == "host":
            # Unpaired host utterance (e.g., manual speech) as an assistant message
            host_text = turn.get("text", "").strip()
            if host_text:
                messages.append({"role": "assistant", "text": host_text})

        idx += 1

    # Build latest user input, but don't duplicate it if the caller already
    # appended the current transcription as the most recent speaker turn.
    latest_input = (latest_text or "").strip()
    already_latest_speaker = (
        merged_history
        and merged_history[-1].get("role") == "speaker"
        and merged_history[-1].get("text", "").strip() == latest_input
    )
    if latest_input and not already_latest_speaker:
        messages.append({"role": "user", "text": latest_input})

    # Attach screenshots to the final user turn, or append a new user turn when
    # the conversation ends with an assistant turn (or is empty).
    if images:
        if messages and messages[-1].get("role") == "user":
            messages[-1]["images"] = list(messages[-1].get("images") or []) + list(images)
        else:
            messages.append({
                "role": "user",
                "text": IMAGE_CONTEXT_PROMPT,
                "images": list(images)
            })
        logger.debug("Attached %d screenshot(s)", len(images))

    return messages


def _get_pronunciation_line(target_language: str) -> str:
    """Build the Syllables/Pronunciation instruction line based on target language."""
    guide = PRONUNCIATION_GUIDES.get(target_language, PRONUNCIATION_GUIDES["Japanese"])
    return f"Syllables/Pronunciation: [{guide['instruction']} Example format: \"{guide['example']}\"]"


def _get_sample_text(target_language: str) -> str:
    """Get a sample text in the target language to show expected output format."""
    return SAMPLE_TEXTS.get(target_language, SAMPLE_TEXTS["Japanese"])


def _load_self_context() -> str:
    """Load self context from SELF_CONTEXT_FILE if configured, otherwise use default."""
    if not SELF_CONTEXT_FILE or not os.path.exists(SELF_CONTEXT_FILE):
        return DEFAULT_SELF_CONTEXT
    with open(SELF_CONTEXT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip() or DEFAULT_SELF_CONTEXT


class GeminiWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    
    def __init__(self, text: str, target_language: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._target_language = target_language
        self._is_running = True
    
    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()

            system_instruction = f"""You are a professional translator. Translate the given text to {self._target_language}.

Format your response exactly as follows:
{self._target_language} Text: [Write the sentence using natural {self._target_language} script]
{_get_pronunciation_line(self._target_language)}
----------------
English Translation: [Provide the meaning in clear English]
----------------
Sample {self._target_language} text format: {_get_sample_text(self._target_language)}"""

            if not self._is_running:
                return

            response = client.generate(
                system_instruction,
                [{"role": "user", "text": f"Text to translate: {self._text}"}]
            )

            if self._is_running and response:
                self.result.emit(response)
            elif self._is_running:
                self.error.emit("Empty response received from the AI provider")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Translation error: {str(e)}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False


class GeminiAutoReplyWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    chunk = Signal(str)
    
    def __init__(self, transcription_text: str, target_language: str, conversation_history: list = None, include_pronunciation: bool = True, purpose: str = DEFAULT_PURPOSE, images: list = None, parent=None):
        super().__init__(parent)
        self._transcription_text = transcription_text
        self._target_language = target_language
        self._conversation_history = conversation_history or []
        self._include_pronunciation = include_pronunciation
        self._purpose = purpose
        self._images = images or []
        self._is_running = True
        self._self_context = _load_self_context()
    
    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()

            # Resolve the selected purpose (persona + objective)
            purpose = PURPOSES.get(self._purpose, PURPOSES[DEFAULT_PURPOSE])
            persona = purpose["persona"]
            objective = "\n".join(f"- {line}" for line in purpose["objective"])

            # Build the shared output format block (plus optional purpose extras)
            format_lines = [
                f"{self._target_language} Text: [Write your response using natural {self._target_language} script]"
            ]
            if self._include_pronunciation:
                format_lines.append(_get_pronunciation_line(self._target_language))
                format_lines.append("English Translation: [Provide the meaning in clear English]")
            format_lines.extend(purpose.get("extra_format", []))
            format_lines.append(
                f"Sample {self._target_language} text format: {_get_sample_text(self._target_language)}"
            )
            format_block = "\n".join(format_lines)

            if self._include_pronunciation:
                output_rule = ""
            else:
                output_rule = ("\nOutput only the sections shown above "
                               "(no pronunciation, no English translation).")

            system_instruction = f"""{persona}

- Messages with role 'user' are what the other person (Speaker) said.
- Messages with role 'assistant' are what you (the Host) have said previously.
- Your expertise areas: {self._self_context}.

Objective:
{objective}

Language:
- Default to writing the Host's reply in {self._target_language}.
- If the Host is already speaking a different language in the conversation (check your previous 'assistant' messages), reply in the language the Host is currently using instead of {self._target_language}.
- If the Host has not spoken yet, use {self._target_language}.
- Whichever language you use, label the first line with that language's name (e.g. "Indonesian Text:" instead of "{self._target_language} Text:").
- Adapt the syllables/pronunciation to the language you actually use, and ignore the sample text below when it is not in that language.

Format your response exactly as follows:
{format_block}{output_rule}"""

            messages = _build_messages(
                self._conversation_history,
                self._transcription_text,
                self._images
            )

            if not self._is_running:
                return

            logger.debug("Messages (%d turns):", len(messages))
            for i, m in enumerate(messages):
                logger.debug("  [%d] role=%s | images=%d | %r", i, m['role'], len(m.get('images') or []), m.get('text', '')[:200])

            # Stream the reply: emit coalesced partial text so the panes update
            # word-by-word, then emit the final result once the stream ends.
            parts = []
            last_emit = 0.0
            interval_s = AI_STREAM_CHUNK_INTERVAL_MS / 1000.0
            for piece in client.generate_stream(system_instruction, messages):
                if not self._is_running:
                    return
                if not piece:
                    continue
                parts.append(piece)
                now = time.monotonic()
                if now - last_emit >= interval_s:
                    last_emit = now
                    self.chunk.emit("".join(parts))

            response = "".join(parts)

            if self._is_running and response:
                self.result.emit(response)
            elif self._is_running:
                self.error.emit("Empty response received from the AI provider")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"AI auto-reply error: {str(e)}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
