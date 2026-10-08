import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Platform flags. The audio backends differ significantly: Windows captures
# system audio through WASAPI loopback (PyAudioWPatch), while macOS has no
# loopback API and instead requires a virtual input device such as BlackHole.
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

SONIOX_API_KEY = os.environ.get("SONIOX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SELF_CONTEXT_FILE = os.environ.get("SELF_CONTEXT_FILE")
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

# AI provider selection. "gemini" uses the google-genai SDK; "openai" targets any
# OpenAI-compatible endpoint (OpenRouter, x.ai, OpenAI, local servers).
AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
AI_MODEL = os.environ.get("AI_MODEL") or os.environ.get("GEMINI_MODEL")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL")

DEFAULT_AI_MODELS = {
    "gemini": "gemini-2.5-flash",
}

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

PRONUNCIATION_GUIDES = {
    "English": {
        "instruction": "Provide the pronunciation as-is since English already uses the Latin alphabet. Separate words with spaces.",
        "example": "How are you doing today?"
    },
    "Indonesian": {
        "instruction": "Provide the pronunciation as-is since Indonesian already uses the Latin alphabet. Separate words with spaces.",
        "example": "Apa kabar hari ini?"
    },
    "Spanish": {
        "instruction": "Provide the pronunciation in Latin alphabet with Indonesian spelling conventions. Separate words with spaces.",
        "example": "¿Komo esta oí?"
    },
    "French": {
        "instruction": "Provide the pronunciation in Latin alphabet with Indonesian spelling conventions. Silent letters should be omitted. Separate words with spaces.",
        "example": "Koman tale vu?"
    },
    "German": {
        "instruction": "Provide the pronunciation in Latin alphabet with Indonesian spelling conventions. Separate words with spaces.",
        "example": "Vi geet es dir?"
    },
    "Chinese": {
        "instruction": "Provide the pronunciation in Pinyin with tone marks. Separate words with spaces.",
        "example": "Nǐ hǎo ma?"
    },
    "Japanese": {
        "instruction": "Provide the pronunciation in Latin alphabet (Romaji) with Indonesian spelling. Separate words with spaces.",
        "example": "Don'na tori ga hebi o tabe raremasu ka?"
    },
    "Korean": {
        "instruction": "Provide the pronunciation in Romanized Korean (Revised Romanization). Separate words with spaces.",
        "example": "Annyeonghaseyo?"
    }
}

SAMPLE_TEXTS = {
    "English": "Hello, how are you today?",
    "Indonesian": "Halo, apa kabar hari ini?",
    "Spanish": "Hola, ¿cómo estás hoy?",
    "French": "Bonjour, comment allez-vous aujourd'hui?",
    "German": "Hallo, wie geht es dir heute?",
    "Chinese": "你好，今天怎么样？",
    "Japanese": "こんにちは、今日はどうですか？",
    "Korean": "안녕하세요, 오늘 어떻게 지내세요?",
    "Arabic": "مرحبا، كيف حالك اليوم؟"
}

MAX_TRANSCRIPTION_LINES = 500
MAX_GEMINI_LINES = 300
CLEANUP_CHECK_INTERVAL = 50

# Bullet points (rolling conversation summary). Tuned for token efficiency:
# the AI receives the current list + only the new lines, batched on an interval.
BULLET_MAX_ITEMS = 12
BULLET_FLUSH_INTERVAL_MS = 15000
BULLET_MAX_BUFFER_LINES = 12
BULLET_PAUSED_BUFFER_MAX = 40
BULLET_MAX_LINE_CHARS = 300

# Session persistence. The current session is written to SESSION_DIR/current.json
# by a background thread (debounced); New Session archives it and starts fresh.
SESSION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions"
)
SESSION_WRITE_DEBOUNCE_MS = 2000
SESSION_MAX_TRANSCRIPT_LINES = 500
SESSION_MAX_GEMINI = 100
SESSION_MAX_SCREENSHOTS = 20
