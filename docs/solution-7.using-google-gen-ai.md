The **`google-genai`** library is the better choice for current and future development. It is the new, unified SDK designed to support the latest models (like Gemini 2.0) and consolidates features from both Google AI Studio and Vertex AI into a single client. [ai.google](https://ai.google.dev/api/generate-content)

The older library, `google-generativeai`, is now considered legacy for newer models.

### Why `google-genai` is better
| Feature | `google-generativeai` (Legacy) | `google-genai` (Recommended) |
| :--- | :--- | :--- |
| **Status** | Maintenance mode; legacy high-level SDK. | **Active development**; the new standard. |
| **Model Support** | Slower updates for features like Multimodal Live API. | Native support for **Gemini 2.0**, WebSockets, and real-time streaming. |
| **Architecture** | Global configuration (`genai.configure`). | Client-based (`client = genai.Client()`), which is cleaner for threading. |
| **Flexibility** | Limited to AI Studio backend. | Unified support for both **AI Studio** and **Vertex AI** backends. |

***

### Migration Guide for `gemini_worker.py`

To migrate your worker thread, you need to make three key changes:
1.  **Import**: Change `import google.generativeai` to `from google import genai`.
2.  **Client**: Instead of global `genai.configure()`, create a `genai.Client` instance.
3.  **Generation**: Use `client.models.generate_content` instead of `model.generate_content`.

Here is your updated `gemini_worker.py` file using the new library.

#### Updated Code (`gemini_worker.py`)

```python
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

            # INITIALIZATION CHANGE:
            # Create a client instance instead of using global configuration.
            # This is safer for threading as it keeps the configuration local.
            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = f"""Translate the following text to {self._target_language}. Provide the response in this exact format:

{self._target_language} Text: [Write the sentence using natural {self._target_language} script]
Syllables/Pronunciation: [Provide the pronunciation in Latin alphabet with Indonesian spelling. Group particles and grammatical elements together with their related words using forward slashes (/). Separate major phrase boundaries with spaces. Example format: "ko-do-mo-ta-chi/to/a-son-da/ba-ka-ri/na-no-de, i-ma, u-re-shi-i/de-su"]
English Translation: [Provide the meaning in clear English]

Text to translate: {self._text}"""

            # GENERATION CHANGE:
            # Call generate_content from the client.models accessor.
            # 'contents' replaces the direct argument usage.
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt
            )

            # Response structure is similar (response.text works for text parts)
            if response.text:
                self.result.emit(response.text)
            else:
                self.error.emit("Empty response received from Gemini")

        except Exception as e:
            self.error.emit(f"Gemini error: {str(e)}")
```

### Key Implementation Details
- **Installation**: Ensure you install the new library with `pip install google-genai` (do not confuse it with the old `google-generativeai`). [discuss.ai.google](https://discuss.ai.google.dev/t/google-generativeai-vs-python-genai/53873)
- **Client Instantiation**: The `client = genai.Client(...)` line handles authentication directly. This is generally more robust for concurrent operations (like in `QThread`) compared to the global state used in the old library.
- **Model Call**: The method signature changes slightly to `client.models.generate_content(model='...', contents=...)`. [ai.google](https://ai.google.dev/gemini-api/docs/migrate)