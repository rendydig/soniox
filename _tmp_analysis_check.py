"""Temp check: the auto-reply analysis preamble (Speaker's move + how to respond)."""
import re
import sys

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

import src.gemini_worker as gw
from src.decision_client import build_questions
from src.purposes import BUILTIN_PURPOSES, purpose_roles
from src.text_formatter import format_gemini_result

purpose = BUILTIN_PURPOSES["consultation"]
roles = purpose_roles(purpose)
role = roles["consultant"]

HISTORY = [
    {"role": "speaker", "text": "How are you?", "suggestion": ""},
    {"role": "host", "text": "Saya baik, terima kasih.", "suggestion": ""},
    {"role": "speaker", "text": "Bagaimana cuaca hari ini?", "suggestion": ""},
]

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def build(text, speaker_act=None):
    w = gw.GeminiAutoReplyWorker(text, "English", conversation_history=HISTORY,
                                 include_pronunciation=False, purpose="consultation")
    return w._build_system_instruction(purpose, role, None, None, speaker_act)


# 1. JEV off: the model is told to classify the Speaker's move itself.
si = build("Bagaimana cuaca hari ini?")
check("analysis header present", "Speaker's move: [" in si)
check("no how-to-respond line", "How to respond" not in si)
check("classify-one-of instruction", "Classify the Speaker's latest utterance as one of: "
      "Assertive, Directive, Commissive, Expressive, Declarative." in si)
check("analysis written in English", "line in English" in si)
check("reply header follows a blank line",
      re.search(r"Speaker's move: \[.*?\]\n\n\w+ Text: \[Write your response", si) is not None)

# 2. JEV decided the Speaker's act: it is pinned into the prompt.
si = build("Bagaimana cuaca hari ini?", speaker_act="directive")
check("pinned act label", "Speaker's move: [Directive — " in si)
check("pinned act named in instructions", "is a Directive speech act; name it" in si)

# 3. Image-only reply (no utterance): no analysis block.
si = build("")
check("no analysis without an utterance", "Speaker's move:" not in si)

# 4. JEV questions include the new speaker_act choice, distinct from speech_act.
questions = build_questions(purpose, roles, [], True, ["Indonesian", "English"], "English")
check("speaker_act question present", questions.get("speaker_act", {}).get("type") == "choice")
check("speaker_act asks about the Speaker",
      "Speaker perform" in questions["speaker_act"]["instructions"])
check("speech_act still asks about the Host",
      "Host perform" in questions["speech_act"]["instructions"])
check("speaker_act criteria are Speaker-framed",
      questions["speaker_act"]["criteria"]["commissive"].startswith("The Speaker commits"))

# 5. Other flow: the analysis rides in front of the synthesized reply.
check("other-flow analysis text",
      gw._analysis_text("Directive — asks about the weather.")
      == "Speaker's move: Directive — asks about the weather.\n\n")
check("other-flow empty analysis", gw._analysis_text(None) == "")

# 6. Formatter: blank line before the reply, none at the very start.
sample = ("Speaker's move: Directive — asks about the weather.\n"
          "English Text: Hari ini cerah.\n"
          "English Translation: It is sunny today.\n")
out = format_gemini_result(sample)
check("formatter keeps the first line flush", not out.startswith("\n"), repr(out[:20]))
check("formatter separates the reply header", "\n\nEnglish Text:" in out)
check("formatter separates the translation header", "\n\nEnglish Translation:" in out)

print()
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
