import os
from google import genai
from google.genai import types
from PySide6.QtCore import QThread, Signal
from src.config import GEMINI_API_KEY, SELF_CONTEXT_FILE, PRONUNCIATION_GUIDES, SAMPLE_TEXTS

DEFAULT_SELF_CONTEXT = "bahasa pemograman javascript, react , nextjs, python, docker, kubernetes, aws, gcp, azure, github, gitlab, bitbucket, jenkins, circleci, travis ci, aws lambda, aws s3, aws ec2, aws rds, aws lambda, aws s3, aws ec2, aws rds"


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
    
    def __init__(self, transcription_text: str, target_language: str, additional_context: str = "", conversation_history: list = None, parent=None):
        super().__init__(parent)
        self._transcription_text = transcription_text
        self._target_language = target_language
        self._additional_context = additional_context
        self._conversation_history = conversation_history or []
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
            
            # Build system instruction (static persona + format rules)
            system_instruction = f"""You are the Host in a live, two-person conversation.

- Your expertise areas: {self._self_context}.
- Messages with role 'user' are what the other person (Speaker) said.
- Messages with role 'model' are what you (the Host) have said previously.

Objective:
- Produce the next thing the Host should say.
- Directly address the LAST 'user' message. Do not change topic. If it is a question, answer it first.
- Keep it concise (1–4 sentences), natural, and conversational.
- Do not repeat the Speaker's words and do not mention being an AI.

Language:
- Write the Host's reply in {self._target_language}.

Format your response exactly as follows:
{self._target_language} Text: [Write your response using natural {self._target_language} script]
{_get_pronunciation_line(self._target_language)}
English Translation: [Provide the meaning in clear English]
Sample {self._target_language} text format: {_get_sample_text(self._target_language)}"""

            # Build multi-turn contents from conversation history
            contents = []
            print(f"[GeminiAutoReplyWorker] Contents ({len(self._conversation_history)} turns):")
            for i, turn in enumerate(self._conversation_history):
                print(f"  [{i}] role={turn['role']} | text={turn['text']} | suggestion={turn['suggestion']}")
                
            # Merge consecutive turns with the same role to reduce fragmentation/noise
            merged_history = []
            for t in self._conversation_history:
                role = t.get("role")
                text = (t.get("text") or "").strip()
                sugg = (t.get("suggestion") or "").strip()
                # Skip completely empty entries
                if not text and not sugg:
                    continue
                if merged_history and merged_history[-1].get("role") == role:
                    # Merge into previous entry
                    if text:
                        prev_text = merged_history[-1].get("text", "")
                        merged_history[-1]["text"] = (prev_text + " " + text).strip() if prev_text else text
                    # For speaker turns, keep the latest suggestion as the fallback
                    if sugg:
                        merged_history[-1]["suggestion"] = sugg
                else:
                    merged_history.append({
                        "role": role,
                        "text": text,
                        "suggestion": sugg
                    })

            # Normalize history into alternating user/model turns using merged history:
            # - 'speaker' -> role='user' with their text
            # - 'host'    -> role='model' with host's spoken text
            # If a 'speaker' turn has no following 'host' turn, use its 'suggestion' as the model reply
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

                    # Pair with the host reply if present next, otherwise fall back to the suggestion for this turn
                    host_reply_text = None
                    if idx + 1 < len(merged_history) and merged_history[idx + 1].get("role") == "host":
                        host_reply_text = (merged_history[idx + 1].get("text") or "").strip()
                        idx += 1  # consume the paired host turn
                    else:
                        host_reply_text = (turn.get("suggestion") or "").strip()

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

            # Build latest user input with optional additional context
            latest_input = f"{self._transcription_text}"
            if self._additional_context and self._additional_context.strip():
                latest_input += f"\n\nAdditional context from user input:\n{self._additional_context.strip()}"
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=latest_input)]
            ))
            
            if not self._is_running:
                return

            print(f"[GeminiAutoReplyWorker] Contents ({len(contents)} turns):")
            for i, c in enumerate(contents):
                print(f"  [{i}] role={c.role} | {c.parts[0].text[:200]!r}")

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
