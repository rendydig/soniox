import base64
import os
from google import genai
from google.genai import types
from PySide6.QtCore import QThread, Signal
from src.config import GEMINI_API_KEY, SELF_CONTEXT_FILE, PRONUNCIATION_GUIDES, SAMPLE_TEXTS
from src.purposes import PURPOSES, DEFAULT_PURPOSE

DEFAULT_SELF_CONTEXT = "bahasa pemograman javascript, react , nextjs, python, docker, kubernetes, aws, gcp, azure, github, gitlab, bitbucket, jenkins, circleci, travis ci, aws lambda, aws s3, aws ec2, aws rds, aws lambda, aws s3, aws ec2, aws rds"

IMAGE_CONTEXT_PROMPT = "Here is a screenshot of the current context. Continue the conversation based on it."


def _decode_data_url(data_url: str):
    """Split a ``data:<mime>;base64,<payload>`` URL into (bytes, mime_type)."""
    if not data_url or "," not in data_url:
        return None, "image/jpeg"
    header, payload = data_url.split(",", 1)
    mime_type = "image/jpeg"
    if header.startswith("data:") and ";" in header:
        mime_type = header[5:].split(";", 1)[0] or mime_type
    try:
        return base64.b64decode(payload), mime_type
    except Exception:
        return None, mime_type


def _attach_images(contents: list, images: list) -> list:
    """Attach screenshots (data URLs) to the conversation contents.

    Images are added to the final user turn, or a new user turn is appended
    when the conversation ends with a model turn (or is empty).
    """
    if not images:
        return contents

    parts = []
    for data_url in images:
        data, mime_type = _decode_data_url(data_url)
        if data:
            parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

    if not parts:
        return contents

    if contents and contents[-1].role == "user":
        contents[-1].parts = list(contents[-1].parts) + parts
    else:
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=IMAGE_CONTEXT_PROMPT), *parts]
        ))
    return contents


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
                
            if not GEMINI_API_KEY:
                self.error.emit("GEMINI_API_KEY not found in .env file")
                return
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            
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
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=f"Text to translate: {self._text}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
            
            if self._is_running and response.text:
                self.result.emit(response.text)
            elif self._is_running:
                self.error.emit("Empty response received from Gemini")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Gemini error: {str(e)}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False


class GeminiAutoReplyWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    
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
                
            if not GEMINI_API_KEY:
                self.error.emit("GEMINI_API_KEY not found in .env file")
                return
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            
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
- Messages with role 'model' are what you (the Host) have said previously.
- Your expertise areas: {self._self_context}.

Objective:
{objective}

Language:
- Write the Host's reply in {self._target_language}.

Format your response exactly as follows:
{format_block}{output_rule}"""

            # Build multi-turn contents from conversation history
            contents = []
            print(f"[GeminiAutoReplyWorker] Contents Length ({len(self._conversation_history)} turns):")
            for i, turn in enumerate(self._conversation_history):
                print(f"  [{i}] role={turn['role']} | text={turn['text']} | suggestion={turn['suggestion']}")
                
            # Merge consecutive turns with the same role to reduce fragmentation/noise
            merged_history = []
            for t in self._conversation_history:
                role = t.get("role")
                text = (t.get("text") or "").strip()
                # Skip completely empty entries
                if not text:
                    continue
                if merged_history and merged_history[-1].get("role") == role:
                    # Merge into previous entry
                    if text:
                        prev_text = merged_history[-1].get("text", "")
                        merged_history[-1]["text"] = (prev_text + "\n" + text).strip() if prev_text else text
                else:
                    merged_history.append({
                        "role": role,
                        "text": text
                    })

            # Normalize history into alternating user/model turns using merged history:
            # - 'speaker' -> role='user' with their text
            # - 'host'    -> role='model' with host's spoken text
            # Gemini requires the contents list to start with a 'user' turn, so drop
            # any leading unpaired host turn before building the context.
            if merged_history and merged_history[0].get("role") == "host":
                merged_history.pop(0)

            idx = 0
            while idx < len(merged_history):
                turn = merged_history[idx]
                role = turn.get("role")
                if role == "speaker":
                    # Add the other person's utterance as a user message
                    speaker_text = turn.get("text", "").strip()
                    if speaker_text:
                        contents.append(types.Content(
                            role="user",
                            parts=[types.Part(text=speaker_text)]
                        ))

                    # Pair with the host reply if present next
                    host_reply_text = None
                    if idx + 1 < len(merged_history) and merged_history[idx + 1].get("role") == "host":
                        host_reply_text = (merged_history[idx + 1].get("text") or "").strip()
                        idx += 1  # consume the paired host turn

                    if host_reply_text:
                        contents.append(types.Content(
                            role="model",
                            parts=[types.Part(text=host_reply_text)]
                        ))

                elif role == "host":
                    # Unpaired host utterance (e.g., manual speech) as a model message
                    host_text = turn.get("text", "").strip()
                    if host_text:
                        contents.append(types.Content(
                            role="model",
                            parts=[types.Part(text=host_text)]
                        ))

                idx += 1

            # Build latest user input, but don't duplicate it if the caller already
            # appended the current transcription as the most recent speaker turn.
            latest_input = self._transcription_text.strip()
            already_latest_speaker = (
                merged_history
                and merged_history[-1].get("role") == "speaker"
                and merged_history[-1].get("text", "").strip() == latest_input
            )
            if latest_input and not already_latest_speaker:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=latest_input)]
                ))

            if self._images:
                contents = _attach_images(contents, self._images)
                print(f"[GeminiAutoReplyWorker] Attached {len(self._images)} screenshot(s)")

            if not self._is_running:
                return

            print(f"[GeminiAutoReplyWorker] Contents ({len(contents)} turns):")
            for i, c in enumerate(contents):
                first_text = (c.parts[0].text or "") if c.parts else ""
                print(f"  [{i}] role={c.role} | parts={len(c.parts)} | {first_text[:200]!r}")

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
            
            if self._is_running and response.text:
                self.result.emit(response.text)
            elif self._is_running:
                self.error.emit("Empty response received from Gemini")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Gemini auto-reply error: {str(e)}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
