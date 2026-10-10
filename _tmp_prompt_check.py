import sys

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

captured = {}


class FakeClient:
    def generate(self, system_instruction, messages):
        captured["si"] = system_instruction
        return "English Text: hello"


import src.gemini_worker as gw

gw.get_ai_client = lambda: FakeClient()

worker = gw.GeminiAutoReplyWorker(
    "Bagaimana cuaca hari ini?",
    "English",
    conversation_history=[
        {"role": "speaker", "text": "How are you?", "suggestion": ""},
        {"role": "host", "text": "Saya baik, terima kasih.", "suggestion": ""},
        {"role": "speaker", "text": "Bagaimana cuaca hari ini?", "suggestion": ""},
    ],
    include_pronunciation=False,
    purpose="consultation",
)
worker.run()

print(captured["si"])
