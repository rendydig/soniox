from google import genai
from PySide6.QtCore import QThread, Signal
from src.config import GEMINI_API_KEY


class GeminiWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    
    def __init__(self, text: str, target_language: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._target_language = target_language
    
    def run(self):
        try:
            if not GEMINI_API_KEY:
                self.error.emit("GEMINI_API_KEY not found in .env file")
                return
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            
            prompt = f"""Translate the following text to {self._target_language}. Provide the response in this exact format:

{self._target_language} Text: [Write the sentence using natural {self._target_language} script]
Syllables/Pronunciation: [Provide the pronunciation in Latin alphabet with Indonesian spelling. Group particles and grammatical elements together with their related words using forward slashes (/). Separate major phrase boundaries with spaces. Example format: "kodomotachi/to/asonda/bakari/nanode, ima, ureshii/desu"]
English Translation: [Provide the meaning in clear English]

Text to translate: {self._text}"""
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )
            
            if response.text:
                self.result.emit(response.text)
            else:
                self.error.emit("Empty response received from Gemini")
        except Exception as e:
            self.error.emit(f"Gemini error: {str(e)}")
