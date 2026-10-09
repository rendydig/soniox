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

# Soniox real-time endpoint detection tuning. Aggressive preset: endpoints are
# emitted sooner at some cost to word-recognition accuracy and to how finely
# long speech is split. Ranges: max_endpoint_delay_ms 500-3000 (default 2000),
# endpoint_latency_adjustment_level 0-3 (default 0), endpoint_sensitivity
# -1.0..1.0 (default 0.0, v5 model only).
SONIOX_MAX_ENDPOINT_DELAY_MS = 800
SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL = 2
SONIOX_ENDPOINT_SENSITIVITY = 0.4

# AI provider selection. "gemini" uses the google-genai SDK; "openai" targets any
# OpenAI-compatible endpoint (OpenRouter, x.ai, OpenAI, local servers).
AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
AI_MODEL = os.environ.get("AI_MODEL") or os.environ.get("GEMINI_MODEL")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL")


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var (1/true/yes/on), falling back to ``default``."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# When true, request no "thinking"/reasoning tokens from the model for faster
# replies. Set DISABLE_MODEL_REASONING=false in .env to re-enable reasoning.
DISABLE_MODEL_REASONING = _env_bool("DISABLE_MODEL_REASONING", True)

# Auto-reply streaming. The AI response is read incrementally and broadcast to
# the panes as it is produced (word-by-word), instead of waiting for the full
# reply. Partial text is coalesced to at most one WebSocket message per interval
# to avoid flooding the socket with per-token frames.
AI_STREAM_CHUNK_INTERVAL_MS = 60

# Auto-reply debounce. A final WITHOUT Soniox's <end> endpoint marker waits
# AUTO_REPLY_DEBOUNCE_MS; a final WITH <end> is the true end of the utterance
# (endpoint detection has already waited out the silence), so it fires after
# only AUTO_REPLY_ENDPOINT_DEBOUNCE_MS.
AUTO_REPLY_DEBOUNCE_MS = 1200
AUTO_REPLY_ENDPOINT_DEBOUNCE_MS = 0

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

# "Last Picked Up": extracts the latest topic/intent the speaker is expressing.
# The whole rolling window (last N finalized lines) is sent on each call, and the
# answer is always in Indonesian with reasoning disabled (cheap, fast capture).
LAST_PICKUP_MAX_LINES = 40
LAST_PICKUP_DEBOUNCE_MS = 1200
LAST_PICKUP_ENDPOINT_DEBOUNCE_MS = 0

# Session persistence. The current session is written to SESSION_DIR/current.json
# by a background thread (debounced); New Session archives it and starts fresh.
SESSION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sessions"
)
SESSION_WRITE_DEBOUNCE_MS = 2000
SESSION_MAX_TRANSCRIPT_LINES = 500
SESSION_MAX_GEMINI = 100
SESSION_MAX_SCREENSHOTS = 20
