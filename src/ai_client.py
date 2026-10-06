import base64

from src.config import (
    AI_API_KEY,
    AI_BASE_URL,
    AI_MODEL,
    AI_PROVIDER,
    DEFAULT_AI_MODELS,
    GEMINI_API_KEY,
)

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


def resolve_model(provider: str) -> str:
    """Pick the model for ``provider``: AI_MODEL, then the provider default."""
    if AI_MODEL:
        return AI_MODEL
    default = DEFAULT_AI_MODELS.get(provider)
    if not default:
        raise ValueError(
            f"AI_MODEL not found in .env file (required when AI_PROVIDER={provider})"
        )
    return default


class AIClient:
    """Provider-neutral interface.

    ``messages`` is a list of dicts shaped as::

        {"role": "user" | "assistant", "text": str, "images": [data_url, ...]}

    ``images`` is optional. Each client adapts this to its own SDK format.
    """

    def generate(self, system_instruction: str, messages: list) -> str:
        raise NotImplementedError


class GeminiClient(AIClient):
    """Google Gemini via the google-genai SDK."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not found in .env file")
        from google import genai

        self._client = genai.Client(api_key=GEMINI_API_KEY)
        self._model = resolve_model("gemini")

    def _to_contents(self, messages: list):
        from google.genai import types

        contents = []
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "model"
            parts = []
            text = (msg.get("text") or "").strip()
            if text:
                parts.append(types.Part(text=text))
            for data_url in msg.get("images") or []:
                data, mime_type = _decode_data_url(data_url)
                if data:
                    parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        return contents

    def generate(self, system_instruction: str, messages: list) -> str:
        from google.genai import types

        response = self._client.models.generate_content(
            model=self._model,
            contents=self._to_contents(messages),
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return response.text


class OpenAICompatibleClient(AIClient):
    """Any OpenAI-compatible chat completions endpoint (OpenRouter, x.ai, ...)."""

    def __init__(self):
        if not AI_API_KEY:
            raise ValueError(
                "AI_API_KEY not found in .env file (required when AI_PROVIDER=openai)"
            )
        if not AI_BASE_URL:
            raise ValueError(
                "AI_BASE_URL not found in .env file (required when AI_PROVIDER=openai)"
            )
        from openai import OpenAI

        self._client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        self._model = resolve_model("openai")

    def _to_messages(self, system_instruction: str, messages: list):
        out = [{"role": "system", "content": system_instruction}]
        for msg in messages:
            role = "user" if msg.get("role") == "user" else "assistant"
            text = msg.get("text") or ""
            images = msg.get("images") or []
            if images:
                content = []
                if text.strip():
                    content.append({"type": "text", "text": text})
                for data_url in images:
                    content.append({"type": "image_url", "image_url": {"url": data_url}})
                out.append({"role": role, "content": content})
            else:
                out.append({"role": role, "content": text})
        return out

    def generate(self, system_instruction: str, messages: list) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=self._to_messages(system_instruction, messages),
        )
        return response.choices[0].message.content


def get_ai_client() -> AIClient:
    """Build the client for the provider selected in .env."""
    if AI_PROVIDER == "openai":
        return OpenAICompatibleClient()
    return GeminiClient()
