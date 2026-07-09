import os
from google import genai
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
            
            prompt = f"""Translate the following text to {self._target_language}. Provide the response in this exact format:

{self._target_language} Text: [Write the sentence using natural {self._target_language} script]
{_get_pronunciation_line(self._target_language)}
----------------
English Translation: [Provide the meaning in clear English]
----------------
Sample {self._target_language} text format: {_get_sample_text(self._target_language)}

Text to translate: {self._text}"""
            
            if not self._is_running:
                return
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
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
            
            # Build conversation history section
            history_section = ""
            if self._conversation_history:
                history_lines = []
                for i, turn in enumerate(self._conversation_history, 1):
                    role_label = "YOU (host)" if turn["role"] == "host" else "THE OTHER PERSON (speaker)"
                    history_lines.append(f"  Turn {i}:")
                    history_lines.append(f"    {role_label} said: {turn['text']}")
                    history_lines.append(f"    Suggested reply was: {turn['suggestion']}")
                history_section = f"\n\nPrevious conversation history (most recent last):\n" + "\n".join(history_lines)

            # Build prompt with optional additional context
            context_section = ""
            if self._additional_context and self._additional_context.strip():
                context_section = f"\n\nAdditional context from user input:\n{self._additional_context.strip()}"
            
            prompt = f"""You are a {self._self_context} professional engaged in a live conversation. You are the HOST (the user). You are listening to transcribed speech and suggesting what you should say next. Use the conversation history to understand the flow and direction of the conversation. Your suggestion should be a natural continuation that makes sense given what has already been said. Provide a natural, contextual response in {self._target_language}. Format your response exactly as follows and keep it concise:

{self._target_language} Text: [Write your response using natural {self._target_language} script]
{_get_pronunciation_line(self._target_language)}
English Translation: [Provide the meaning in clear English]
{history_section}{context_section}

Latest transcribed speech: {self._transcription_text}"""
            
            if not self._is_running:
                return
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
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
