import os
from dotenv import load_dotenv

load_dotenv()

SONIOX_API_KEY = os.environ.get("SONIOX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

LANGUAGES = {
    "English": "en",
    "Indonesian": "id",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko"
}

MAX_TRANSCRIPTION_LINES = 500
MAX_GEMINI_LINES = 300
CLEANUP_CHECK_INTERVAL = 50
