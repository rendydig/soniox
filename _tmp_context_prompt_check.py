"""Temp check: the Host/Speaker context reaches the auto-reply prompt.

The Context pane pushes the context text over the WebSocket
(`TranslationController.set_context` -> `GeminiAutoReplyWorker(context=...)`);
this asserts the three states the worker must keep apart:

  context=None  -> nothing arrived yet, fall back to the .env files
  context=""    -> the user picked no context for that role: omit the line
  context=text  -> use the text as the pre-identifier
"""
import os
import sys

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

# The .env fallback is read relative to the CWD, so run from the repo root.
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import src.gemini_worker as gw
from src.purposes import BUILTIN_PURPOSES, purpose_roles

PURPOSE = BUILTIN_PURPOSES["consultation"]
ROLES = purpose_roles(PURPOSE)
ROLE = ROLES["consultant"]

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


def build(context, text="Bagaimana cuaca hari ini?"):
    worker = gw.GeminiAutoReplyWorker(
        text, "English", conversation_history=HISTORY,
        include_pronunciation=False, purpose="consultation", context=context,
    )
    return worker, worker._build_system_instruction(PURPOSE, ROLE, None, None, None)


print("[1] context=text -> both profiles are pinned into the prompt")
worker, si = build({"host": "HOSTCTX ten years of Go", "speaker": "SPEAKERCTX a hiring manager"})
check("host line present", "- Host profile (pre-identified): HOSTCTX ten years of Go" in si)
check("speaker line present", "- Speaker profile: SPEAKERCTX a hiring manager" in si)
check("no default fallback", gw.DEFAULT_SELF_CONTEXT not in si)
check("JEV state gets the same host text", worker._self_context == "HOSTCTX ten years of Go")
check("JEV state gets the same speaker text", worker._speaker_context == "SPEAKERCTX a hiring manager")

print("\n[2] context='' (user picked none) -> the host line is omitted")
_, si = build({"host": "", "speaker": ""})
check("no host line", "Host profile" not in si)
check("speaker stays 'unknown'", "- The Speaker profile is unknown" in si)
check("no default fallback", gw.DEFAULT_SELF_CONTEXT not in si)

print("\n[3] host only -> the speaker line keeps its unknown fallback")
_, si = build({"host": "HOSTCTX only", "speaker": ""})
check("host line present", "- Host profile (pre-identified): HOSTCTX only" in si)
check("speaker unknown", "- The Speaker profile is unknown" in si)

print("\n[4] context=None -> today's .env behaviour (fallback, not an error)")
worker, si = build(None)
check("falls back to the .env file", worker._self_context == gw._load_self_context())
check("uses SELF_CONTEXT_FILE, not the default", gw.DEFAULT_SELF_CONTEXT not in si, worker._self_context[:40])
check("host line present", "- Host profile (pre-identified):" in si)

print("\n[5] image reply (no utterance) still carries the profiles")
_, si = build({"host": "HOSTCTX image", "speaker": "SPEAKERCTX image"}, text="")
check("host line present", "- Host profile (pre-identified): HOSTCTX image" in si)
check("speaker line present", "- Speaker profile: SPEAKERCTX image" in si)
check("no analysis preamble for an image reply", "Speaker's move:" not in si)

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
