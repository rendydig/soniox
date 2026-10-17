"""Temp check: the auto-reply (AI suggestion) prompt + trigger contract — OFFLINE tier.

Deterministic, no-network half of the auto-reply regression suite. It drives the
REAL ``GeminiAutoReplyWorker.run()`` with a stubbed provider client
(``generate_stream``) and asserts *the contract of what we send*: the system
instruction, the normalized message list, the controller's debounce, the history
cap, the trigger-drop guard and the image path. No model is ever called.

Two kinds of assertion:

  * ``check(...)``   — a hard assertion; a failure exits non-zero. This is the gate.
  * ``witness(...)`` — a *known* limitation observed on purpose (the ranked causes
                       in the flow review). It is always printed, never fails
                       unless ``AUTO_REPLY_STRICT=1``, so the suite can flip from
                       "characterize the bug" to "assert the fix" in one change.

Run from the repo root:
    venv/bin/python _tmp_auto_reply_prompt_check.py
    AUTO_REPLY_STRICT=1 venv/bin/python _tmp_auto_reply_prompt_check.py   # witnesses fail

The opt-in real-model half is ``_tmp_auto_reply_live_check.py``.
"""
import json
import os
import sys
import types

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.abspath(__file__))
# The .env fallback path is read relative to the CWD, so pin it to the repo root.
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import src.gemini_worker as gw  # noqa: E402  (import after Qt app + sys.path)
from src.config import (  # noqa: E402
    AUTO_REPLY_DEBOUNCE_MS,
    AUTO_REPLY_ENDPOINT_DEBOUNCE_MS,
    AUTO_REPLY_MAX_BRIEF_CHARS,
    AUTO_REPLY_MAX_BULLETS,
    AUTO_REPLY_MAX_BULLET_CHARS,
    AUTO_REPLY_MAX_PRIOR_SUGGESTIONS,
    AUTO_REPLY_MAX_PROFILE_ITEMS,
    SELF_CONTEXT_FILE,
)
import src.controllers.translation_controller as tc  # noqa: E402
from src.controllers.translation_controller import TranslationController  # noqa: E402
from src.purposes import BUILTIN_PURPOSES, purpose_roles  # noqa: E402

STRICT = os.environ.get("AUTO_REPLY_STRICT") == "1"
PURPOSE = BUILTIN_PURPOSES["consultation"]
ROLES = purpose_roles(PURPOSE)
ROLE = ROLES["consultant"]

failures = []
witnesses = []
n_pass = 0


def check(name, cond, detail=""):
    global n_pass
    ok = bool(cond)
    if ok:
        n_pass += 1
    else:
        failures.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def witness(name, present, note=""):
    """Record a known limitation. ``present=True`` means we observed the bug."""
    witnesses.append((name, bool(present), note))
    tag = "WITNESS-HIT" if present else "WITNESS-OK "
    print(tag + "  " + name + (f"  ({note})" if note else ""))
    if STRICT and present:
        failures.append("strict:" + name)


# --- stub provider client ------------------------------------------------
class FakeClient:
    """Captures what the worker sends and yields a canned reply."""

    def __init__(self, reply: str):
        self.reply = reply or ""
        self.calls = []

    def _record(self, kind, si, messages, disable_reasoning):
        self.calls.append({
            "kind": kind, "si": si, "messages": messages,
            "disable_reasoning": disable_reasoning,
        })

    def generate(self, system_instruction, messages, disable_reasoning=None):
        self._record("generate", system_instruction, messages, disable_reasoning)
        return self.reply

    def generate_stream(self, system_instruction, messages, disable_reasoning=None):
        self._record("generate_stream", system_instruction, messages, disable_reasoning)
        if self.reply:
            yield self.reply


def run_worker(text, history, *, context=None, purpose="consultation",
               host_role="consultant", jev=False, images=None, allow_filler=False,
               digest=None, objectives=None, locks=None, meta=None,
               reply="English Text: canned reply", target="English"):
    """Run the real worker synchronously against a stubbed client."""
    client = FakeClient(reply)
    gw.get_ai_client = lambda: client
    worker = gw.GeminiAutoReplyWorker(
        text, target, conversation_history=list(history),
        include_pronunciation=False, purpose=purpose,
        host_role=host_role, jev_enabled=jev, images=images, context=context,
        allow_filler=allow_filler, digest=digest,
        objectives=objectives, objective_locks=locks, objective_meta=meta,
    )
    skipped = []
    worker.skipped.connect(skipped.append)
    worker.run()
    worker.skipped_messages = skipped
    return worker, client


# --- fixtures ------------------------------------------------------------
def read_file(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def load_recorded_conversation():
    try:
        with open(os.path.join(REPO, "sessions", "current.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("conversation") or []
    except (OSError, ValueError):
        return []


HELPY = read_file("docs", "helpy.context.txt")
MAYA = read_file("maya.context.txt") or "Her name is Maya."
recorded = load_recorded_conversation()


def messages_of(client):
    return client.calls[0]["messages"] if client.calls else []


def si_of(client):
    return client.calls[0]["si"] if client.calls else ""


def role_of(m):
    return m.get("role")


# =====================================================================
# [1] Sample conversation — the recorded session, as the model saw it
# =====================================================================
print("[1] Sample conversation (replay of sessions/current.json)")
q_idx = -1
for i in range(len(recorded) - 1, -1, -1):
    if recorded[i].get("role") != "host" and \
            "stop that from happening" in (recorded[i].get("text") or "").lower():
        q_idx = i
        break

if q_idx < 0:
    print("     SKIP — sessions/current.json has no 'stop that from happening' turn")
else:
    question = recorded[q_idx]["text"].strip()
    history = recorded[: q_idx + 1]          # history as it was at trigger time
    _, client = run_worker(question, history,
                           context={"host": HELPY or "HOSTCTX", "speaker": MAYA},
                           host_role="consultant")
    si = si_of(client)
    messages = messages_of(client)

    check("exactly one AI call, on the streaming path",
          len(client.calls) == 1 and client.calls[0]["kind"] == "generate_stream")
    check("the recorded history is <= MAX_HISTORY_TURNS (25)", len(history) <= 25, str(len(history)))
    check("Host profile text is in the prompt",
          "Host profile (pre-identified):" in si and (not HELPY or HELPY[:60] in si))
    check("Speaker profile text is in the prompt",
          "Speaker profile: Her name is Maya" in si)
    check("Host identity is the pinned role (Consultant)",
          "You are acting as: Consultant." in si)
    check("Speaker identity is the counterpart (Client)",
          "The Speaker is acting as: Client." in si)
    check("the final message is the question, as a user turn",
          bool(messages) and role_of(messages[-1]) == "user"
          and messages[-1]["text"] == question)
    check("the question appears exactly once",
          sum(1 for m in messages if m.get("text") == question) == 1)

    _, c_lead = run_worker("How are you?",
                           [{"role": "host", "text": "Okay.", "suggestion": ""},
                            {"role": "speaker", "text": "How are you?", "suggestion": ""}])
    check("a single leading host turn is dropped (list starts with user)",
          role_of(messages_of(c_lead)[0]) == "user")
    witness("the real recorded history starts with an assistant turn (only ONE "
            "leading host turn is dropped, the rest merge)",
            bool(messages) and role_of(messages[0]) != "user",
            "cause 5 / _build_messages, first=%r" % (messages[0]["text"][:24] if messages else ""))

    # Strip the injected Host profile before searching: the 12 KB doc body itself
    # contains phrases like "source of truth" and would fool the detector.
    acc = si.replace(HELPY.strip(), "\u00abHOST_PROFILE\u00bb").lower()
    check("the grounding rule ties the Host profile to answering the question",
          any(p in acc for p in ("source of truth", "use the host profile",
                                 "from the host profile", "grounded in the host profile")))
    check("the grounding rule demands the product mechanism in the FIRST sentence",
          "name the concrete product mechanism in your first sentence" in acc)
    check("consultation/consultant instructs answer-first via its role style",
          bool((ROLE.get("style") or {}).get("answer_first"))
          and "answer it in your first sentence" in si)
    check("the rendered prompt carries a per-role Style block",
          "\nStyle:\n" in si and "- Tone:" in si and "- Length:" in si)
    # NOT a code path: the recorded session's `suggestion` field was never
    # populated, so this measures historical data. Kept as a documented fact
    # rather than a witness, because no code change can flip it.
    check("the recorded session carries no per-turn suggestions (historical data)",
          bool(recorded)
          and all(not (t.get("suggestion") or "").strip() for t in recorded))

# =====================================================================
# [2] Speaker asks a question — offline precondition (quality is live-only)
# =====================================================================
print("\n[2] Speaker asks a question — the question reaches the model as the target")
_, client = run_worker("How does your tool actually fix the handoffs?",
                       [{"role": "speaker", "text": "How does your tool actually fix the handoffs?",
                         "suggestion": ""}])
si = si_of(client)
messages = messages_of(client)
check("objective says to address the LAST 'user' message",
      "Directly address the LAST 'user' message" in si)
check("the question is the final user turn",
      bool(messages) and messages[-1]["role"] == "user"
      and messages[-1]["text"] == "How does your tool actually fix the handoffs?")

# =====================================================================
# [2b] Per-persona style — every role gets its own Style block
# =====================================================================
print("\n[2b] Per-persona style — distinct approach/tone per role, answer_first honored")
_, c_learn = run_worker("Hola, ¿cómo estás?",
                        [{"role": "speaker", "text": "Hola, ¿cómo estás?", "suggestion": ""}],
                        purpose="language_learning", host_role="learner")
si_learn = si_of(c_learn)
_, c_probe = run_worker("I'd use a hash map.",
                        [{"role": "speaker", "text": "I'd use a hash map.", "suggestion": ""}],
                        purpose="coding_interview", host_role="interviewer")
si_probe = si_of(c_probe)
check("the learner role renders its own Style block",
      "\nStyle:\n" in si_learn and "Tone: warm, patient, encouraging" in si_learn)
check("the interviewer role renders its own Style block",
      "Tone: probing, neutral, encouraging" in si_probe)
check("an interviewer role omits the answer-first directive (answer_first=False)",
      "answer it in your first sentence" not in si_probe)
check("two roles get genuinely different styles",
      si_learn != si_probe and "Keep the practice conversation moving" in si_learn
      and "Keep the practice conversation moving" not in si_probe)
check("a role with no style block falls back to DEFAULT_ROLE_STYLE",
      "Tone: natural, conversational" in gw._style_block({"label": "Legacy"}))
check("the coding candidate keeps its mermaid safety line",
      "```mermaid" in si_of(run_worker(
          "Draw the architecture.",
          [{"role": "speaker", "text": "Draw the architecture.", "suggestion": ""}],
          purpose="coding_interview", host_role="candidate")[1]))

# =====================================================================
# [4] Answer -> acknowledgment -> new question (role inversion guard)
# =====================================================================
print("\n[4] Ack then a new question — the reply must stay in the Consultant voice")
hist_ack = [
    {"role": "speaker", "text": "how exactly would your tool stop that back-and-forth?", "suggestion": ""},
    {"role": "host", "text": "Helpy would capture both sides into a shared brief.", "suggestion": ""},
    {"role": "speaker", "text": "Exactly.", "suggestion": ""},
    {"role": "speaker", "text": "You nailed it.", "suggestion": ""},
    {"role": "speaker", "text": "How do we stop that from happening?", "suggestion": ""},
]
_, client = run_worker("How do we stop that from happening?", hist_ack,
                       context={"host": HELPY or "HOSTCTX", "speaker": MAYA},
                       host_role="consultant")
si = si_of(client)
check("the prompt pins the Consultant role (not the Client)",
      "You are acting as: Consultant." in si
      and "You are acting as: Client." not in si)
check("the Client objective is NOT in the prompt",
      "State a concrete need" not in si)
witness("fillers/acks ('Exactly.', 'You nailed it.') are kept as separate user content",
        any("Exactly." in (m.get("text") or "") for m in messages_of(client)),
        "causes 5-6 (history hygiene)")

# =====================================================================
# [5] Filler-only utterance
# =====================================================================
print("\n[5] Filler-only utterance ('Okay.')")
worker, client = run_worker("Okay.", [{"role": "speaker", "text": "Okay.", "suggestion": ""}])
check("a filler produces no AI call", not client.calls, f"{len(client.calls)} call(s)")
check("the skip is reported as a filler",
      worker.skipped_messages == ["Filler utterance"], str(worker.skipped_messages))
_, c_filler_run = run_worker("Exactly. You nailed it.",
                             [{"role": "speaker", "text": "Exactly. You nailed it.", "suggestion": ""}])
check("a run of acknowledgments is a filler too", not c_filler_run.calls)
_, c_manual = run_worker("Okay.", [{"role": "speaker", "text": "Okay.", "suggestion": ""}],
                         allow_filler=True)
check("an explicit request (manual 'Reply now') still answers a filler", len(c_manual.calls) == 1)
_, c_real = run_worker("Right, but the brief still gets lost.",
                       [{"role": "speaker", "text": "Right, but the brief still gets lost.",
                         "suggestion": ""}])
check("a short-but-real answer is not mistaken for a filler", len(c_real.calls) == 1)
witness("no filler/debounce filter: 'Okay.' triggers a full AI suggestion",
        bool(client.calls), "cause 6 / F6")

# =====================================================================
# [6] Host turn AFTER the question (trailing host turn)
# =====================================================================
print("\n[6] A host turn lands after the question before the debounce fires")
hist_trailing = [
    {"role": "speaker", "text": "How are you?", "suggestion": ""},
    {"role": "host", "text": "Saya baik, terima kasih.", "suggestion": ""},
    {"role": "speaker", "text": "How do we stop that from happening?", "suggestion": ""},
    {"role": "host", "text": "Okay.", "suggestion": ""},
]
_, client = run_worker("How do we stop that from happening?", hist_trailing)
messages = messages_of(client)
q_occurrences = sum(1 for m in messages if m.get("text") == "How do we stop that from happening?")
check("the latest utterance is the final message",
      bool(messages) and messages[-1]["role"] == "user"
      and messages[-1]["text"] == "How do we stop that from happening?")
check("the intervening host turn is preserved as an assistant turn",
      any(m.get("role") == "assistant" and m.get("text") == "Okay." for m in messages))
witness("the question is sent TWICE when a host turn follows it",
        q_occurrences == 2, "cause 5 / _build_messages re-append, N=%d" % q_occurrences)

# =====================================================================
# [7] No Host context selected
# =====================================================================
print("\n[7] context={'host': '', 'speaker': ''} — user selected no context")
_, client = run_worker("How does it work?", [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
                       context={"host": "", "speaker": ""})
si = si_of(client)
check("the Host profile line is omitted", "Host profile" not in si)
check("the Speaker falls back to 'unknown'", "- The Speaker profile is unknown" in si)
check("no .env/default context leaks in", gw.DEFAULT_SELF_CONTEXT not in si
      and (not HELPY or HELPY[:60] not in si))
check("the objective is still present", "Directly address the LAST 'user' message" in si)
check("with no context the prompt forbids inventing product specifics",
      "do not invent product" in si and "say so briefly or ask" in si)
check("the no-context rule never mentions 'Host profile'", "Host profile" not in si)

# =====================================================================
# [8] Context not delivered yet (None) -> .env fallback
# =====================================================================
print("\n[8] context=None — nothing arrived yet, fall back to SELF_CONTEXT_FILE")
worker, client = run_worker("How does it work?",
                            [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
                            context=None)
si = si_of(client)
check("the worker reads the .env fallback", worker._self_context == gw._load_self_context())
expected_host = os.path.exists(SELF_CONTEXT_FILE or "") and SELF_CONTEXT_FILE or ""
check("SELF_CONTEXT_FILE is a real file in this checkout", bool(expected_host),
      SELF_CONTEXT_FILE or "unset")
if expected_host:
    check("the fallback file (context_sample.txt), not DEFAULT_SELF_CONTEXT, is used",
          gw.DEFAULT_SELF_CONTEXT not in si)
check("the host line is present from the fallback",
      "Host profile (pre-identified):" in si)

# =====================================================================
# [9] Speaker context vs the extracted KYC profile
# =====================================================================
print("\n[9] Speaker context (maya.context.txt) vs the extracted profile")
_, client = run_worker("How does it work?", [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
                       context={"host": "HOSTCTX", "speaker": MAYA})
si = si_of(client)
check("the selected Speaker context is what the model sees",
      ("Speaker profile: " + MAYA.split("\n")[0].strip()) in si)
try:
    with open(os.path.join(REPO, "sessions", "current.json"), encoding="utf-8") as f:
        recorded_speaker = (json.load(f) or {}).get("speaker") or {}
except (OSError, ValueError):
    recorded_speaker = {}
# Flipped contract (P1): the profile is still out while the digest is OFF, but it
# now *is* part of the prompt once the digest is enabled (asserted in [18]). The
# digest is built from the LOCKED session record and injected explicitly here, so
# passing it does not bypass the feature flag.
from src.decision_client import build_questions  # noqa: E402  (section-local imports)
from src.reply_context import build_digest  # noqa: E402
_recorded_digest = build_digest(
    ["Brief gets lost at handoff", "Helpy captures both sides"], [False, True],
    recorded_speaker, "Confirmed: cut handoff loss by half.", [],
)
_, c_digest_off = run_worker(
    "How does it work?", [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
    context={"host": "HOSTCTX", "speaker": MAYA}, digest=_recorded_digest)
check("the extracted KYC profile is NOT in the prompt while the digest is off",
      bool(recorded_speaker)
      and (recorded_speaker.get("occupation") or "") not in si
      and (recorded_speaker.get("occupation") or "") not in si_of(c_digest_off))
witness("selected Speaker context contradicts the extracted profile",
        bool(recorded_speaker) and "Architect" in MAYA
        and "Head of Operations" in (recorded_speaker.get("occupation") or ""),
        "data fix: maya.context.txt vs speaker.occupation")

# =====================================================================
# [10] Cross-language — structure only offline (the reply itself is live)
# =====================================================================
print("\n[10] Indonesian utterance — the analysis line stays English")
_, client = run_worker("Bagaimana caranya supaya brief tidak hilang saat serah terima?",
                       [{"role": "speaker",
                         "text": "Bagaimana caranya supaya brief tidak hilang saat serah terima?",
                         "suggestion": ""}])
si = si_of(client)
check("the detected language is Indonesian", "appears to be speaking Indonesian" in si)
check("the 'Speaker's move' line is required in English",
      'Write the "Speaker\'s move" line in English' in si)

# =====================================================================
# [11] <end> endpoint final — debounce wiring
# =====================================================================
print("\n[11] endpoint final — the debounce delay is wired through the controller")
controller = TranslationController()
check("the timer is single-shot", controller._auto_reply_timer.isSingleShot())
controller.schedule_auto_reply("first", "speaker")
check("a plain final uses AUTO_REPLY_DEBOUNCE_MS",
      controller._auto_reply_timer.interval() == AUTO_REPLY_DEBOUNCE_MS,
      str(controller._auto_reply_timer.interval()))
controller.schedule_auto_reply("second", "speaker",
                               delay_ms=AUTO_REPLY_ENDPOINT_DEBOUNCE_MS)
check("an <end> final uses AUTO_REPLY_ENDPOINT_DEBOUNCE_MS",
      controller._auto_reply_timer.interval() == AUTO_REPLY_ENDPOINT_DEBOUNCE_MS,
      str(controller._auto_reply_timer.interval()))
check("re-scheduling replaces the pending utterance (one reply per pause)",
      controller._pending_transcription == "second")
witness("AGENTS.md documents 1200 but src/config.py is 1500",
        "AUTO_REPLY_DEBOUNCE_MS` (1200)" in read_file("AGENTS.md"),
        "doc drift")

# =====================================================================
# [12] Long conversation — the 25-turn cap
# =====================================================================
print("\n[12] Long conversation — only the last MAX_HISTORY_TURNS are kept")
controller2 = TranslationController()
long_history = [{"role": "speaker", "text": f"turn {i}", "suggestion": ""} for i in range(40)]
controller2.load_conversation_history(long_history)
loaded = controller2.get_conversation_history()
check("load trims to 25", len(loaded) == 25, str(len(loaded)))
check("load keeps the tail", loaded[0]["text"] == "turn 15" and loaded[-1]["text"] == "turn 39")
for i in range(40):
    controller2.append_to_history(f"append {i}", "", "speaker")
appended = controller2.get_conversation_history()
check("append trims to 25", len(appended) == 25, str(len(appended)))
check("append keeps the newest", appended[-1]["text"] == "append 39")

# =====================================================================
# [13] A new final while a reply is already streaming
# =====================================================================
print("\n[13] A new utterance arrives while an auto-reply worker is running")


class _RunningWorker:
    def isRunning(self):
        return True


controller3 = TranslationController()
running = _RunningWorker()
controller3._auto_reply_worker = running
controller3.schedule_auto_reply("the next utterance", "speaker")
controller3._trigger_auto_reply()          # simulate the debounce firing
check("no new worker is created while one is running",
      controller3._auto_reply_worker is running)
check("the refused utterance is left pending",
      controller3._pending_transcription == "the next utterance")
check("the refused utterance is queued for one rerun", controller3._rerun_pending is True)

# The queue must actually drain: finishing the in-flight worker re-runs the
# queued utterance instead of leaving it with no suggestion at all.
started = []


def _record_start(text, images=None, is_image=False, allow_filler=False):
    started.append(text)
    return True


controller3._start_auto_reply_worker = _record_start
controller3._auto_reply_worker = None
controller3._on_auto_reply_result("done")
check("finishing the worker re-runs the queued utterance",
      started == ["the next utterance"], str(started))
check("the rerun flag is consumed (no repeat)", controller3._rerun_pending is False)
witness("the dropped trigger is never re-run — that utterance gets no suggestion",
        not started, "cause 7 / F7")

# =====================================================================
# [14] Manual 'Reply now' picks the last Speaker turn
# =====================================================================
print("\n[14] Manual reply uses the last Speaker turn, not the Host's")
import src.ui as ui  # noqa: E402  (heavy Qt import; only needed here)

calls = []
stub = types.SimpleNamespace(
    translation_controller=types.SimpleNamespace(
        get_conversation_history=lambda: [
            {"role": "host", "text": "Okay.", "suggestion": ""},
            {"role": "speaker", "text": "How do we stop that from happening?", "suggestion": ""},
            {"role": "host", "text": "Right.", "suggestion": ""},
        ],
        trigger_reply_now=lambda text, source: calls.append((text, source)),
    ),
    _last_final_transcription="FALLBACK",
)
ui.MainWindow._manual_reply(stub)
check("manual reply picks the last speaker turn",
      calls == [("How do we stop that from happening?", "speaker")], str(calls))

calls.clear()
stub_host_only = types.SimpleNamespace(
    translation_controller=types.SimpleNamespace(
        get_conversation_history=lambda: [{"role": "host", "text": "Okay.", "suggestion": ""}],
        trigger_reply_now=lambda text, source: calls.append((text, source)),
    ),
    _last_final_transcription="FALLBACK",
)
ui.MainWindow._manual_reply(stub_host_only)
check("manual reply falls back to the last final when there is no speaker turn",
      calls == [("FALLBACK", "speaker")], str(calls))

# The manual path must carry allow_filler all the way to the worker, or Ctrl+R on a
# filler would be silently refused by the F6 filter.
controller4 = TranslationController()
seen = {}


def _record_start(text, images=None, is_image=False, allow_filler=False):
    seen.update(text=text, allow_filler=allow_filler)
    return True


controller4._start_auto_reply_worker = _record_start
controller4.trigger_reply_now("Okay.", "speaker")
check("the manual path reaches the worker with allow_filler=True",
      seen == {"text": "Okay.", "allow_filler": True}, str(seen))

# =====================================================================
# [15] Screenshot reply — no analysis preamble, profiles still attached
# =====================================================================
print("\n[15] Image reply (no utterance)")
_, client = run_worker("", [{"role": "speaker", "text": "hi", "suggestion": ""}],
                       images=["data:image/jpeg;base64,AAAA"],
                       context={"host": "HOSTCTX image", "speaker": "SPEAKERCTX image"})
si = si_of(client)
messages = messages_of(client)
check("no 'Speaker's move' preamble for an image reply", "Speaker's move:" not in si)
check("the Host profile is still attached", "HOSTCTX image" in si)
check("the Speaker profile is still attached", "SPEAKERCTX image" in si)
check("the screenshot is attached to the final user turn",
      bool(messages) and messages[-1]["role"] == "user"
      and len(messages[-1].get("images") or []) == 1)

# =====================================================================
# [16] Pinned role with JEV on — the pin is never overridden
# =====================================================================
print("\n[16] JEV would pick a different role, but the pin wins")
DECISION = {
    "should_reply": {"type": "noul", "noul": 0.95},
    "host_role": {"type": "choice", "choice": "client", "confidence": 0.99},
    "speaker_act": {"type": "choice", "choice": "directive", "confidence": 0.99},
    "speech_act": {"type": "choice", "choice": "directive", "confidence": 0.99},
    "reply_language": {"type": "choice", "choice": "English", "confidence": 0.99},
}

client = FakeClient("English Text: canned")
gw.get_ai_client = lambda: client
pinned = gw.GeminiAutoReplyWorker(
    "How do we stop that from happening?", "English",
    conversation_history=[{"role": "speaker", "text": "How do we stop that from happening?",
                           "suggestion": ""}],
    include_pronunciation=False, purpose="consultation", host_role="consultant", jev_enabled=True,
)
pinned._run_decision = lambda *a, **k: DECISION
pinned.run()
si_pinned = si_of(client)
check("the pinned Consultant role survives the JEV choice",
      "You are acting as: Consultant." in si_pinned
      and "You are acting as: Client." not in si_pinned)
check("the JEV speaker_act is pinned into the analysis line",
      "Speaker's move: [Directive — " in si_pinned)

client2 = FakeClient("English Text: canned")
gw.get_ai_client = lambda: client2
smart = gw.GeminiAutoReplyWorker(
    "How do we stop that from happening?", "English",
    conversation_history=[{"role": "speaker", "text": "How do we stop that from happening?",
                           "suggestion": ""}],
    include_pronunciation=False, purpose="consultation", host_role="smart", jev_enabled=True,
)
smart._run_decision = lambda *a, **k: DECISION
smart.run()
check("a 'smart' role IS adopted from JEV (proves the pin is the guard)",
      "You are acting as: Client." in si_of(client2))

# =====================================================================
# [17] Purpose store — the seed is authoritative (schema 2)
# =====================================================================
print("\n[17] PurposeStore — the seed wins; purposes.json only adds non-built-ins")
import json as _json  # noqa: E402  (already imported; alias keeps the section local)
import shutil  # noqa: E402
import tempfile  # noqa: E402

from src.purpose_store import PurposeStore  # noqa: E402

_tmpdir = tempfile.mkdtemp(prefix="purposes-check-")
_path = os.path.join(_tmpdir, "purposes.json")
# A legacy flat file holding a stale built-in copy (the old whole-dict dump) and
# one AI-learned entry. This is exactly the shape that used to shadow the seed.
_legacy = {
    "consultation": {
        "label": "Consultation",
        "default_role": "consultant",
        "roles": {"consultant": {"label": "Consultant", "persona": "stale",
                                "objective": ["old objective"]}},
    },
    "learned_thing": {
        "label": "Learned Thing (auto)", "dynamic": True, "default_role": "learned_thing",
        "roles": {"learned_thing": {"label": "Learned Thing", "persona": "P",
                                     "objective": ["o"]}},
    },
}
with open(_path, "w", encoding="utf-8") as f:
    _json.dump(_legacy, f)
_store = PurposeStore(path=_path)
_seed_consultant = BUILTIN_PURPOSES["consultation"]["roles"]["consultant"]
check("a stale built-in copy no longer shadows the seed",
      _store.get("consultation")["roles"]["consultant"]["objective"]
      == _seed_consultant["objective"])
check("the seed's per-role style survives",
      "style" in _store.get("consultation")["roles"]["consultant"])
check("a non-built-in entry still loads", _store.exists("learned_thing"))
check("the runtime objective answers first",
      bool(_store.get("consultation")["roles"]["consultant"].get("style", {})
           .get("answer_first")))
_registered = _store.register({"label": "Dry Persona", "style": {"tone": "dry, clipped"}})
_registered_role = next(iter(purpose_roles(_store.get(_registered)).values()))
check("a synthesized role carries its own tone and inherits the default",
      _registered_role["style"]["tone"] == "dry, clipped"
      and _registered_role["style"]["length"] == gw.DEFAULT_ROLE_STYLE["length"])
_store.flush()
_written = _json.load(open(_path, encoding="utf-8"))
check("the file is schema 2", _written.get("schema_version") == 2)
check("the file carries only non-built-in entries",
      set(_written.get("purposes", {})) == {"learned_thing", _registered},
      str(sorted(_written.get("purposes", {}))))
check("no built-in is written back to disk",
      not (set(_written.get("purposes", {})) & set(BUILTIN_PURPOSES)))
_store.close()
shutil.rmtree(_tmpdir, ignore_errors=True)

# =====================================================================
# [18] Session digest in the auto-reply prompt (P1)
# =====================================================================
print("\n[18] Session digest — off by default, capped, opt-in")

_UTTER = "How do we stop that from happening?"
_HIST = [{"role": "speaker", "text": _UTTER, "suggestion": ""}]
_DIGEST = build_digest(
    ["Brief gets lost at handoff", "Helpy captures both sides into a shared brief"],
    [False, True],
    {"name": "Maya", "occupation": "Head of Operations",
     "goals": ["cut handoff loss"], "pain_points": ["brief lost in Slack"],
     "facts": ["three teams"]},
    "## Goals\nCut handoff loss by half.",
    [{"role": "speaker", "text": "q1", "suggestion": "Name the capture step first."},
     {"role": "host", "text": "a1", "suggestion": ""},
     {"role": "speaker", "text": "q2", "suggestion": "Talk about the shared brief."}],
)

# The flag is patched explicitly rather than read from the environment, so this
# section is deterministic whether or not .env turns the digest on.
_prev_flag = gw.AUTO_REPLY_CONTEXT_DIGEST
try:
    gw.AUTO_REPLY_CONTEXT_DIGEST = False
    _, c_plain = run_worker(_UTTER, _HIST)
    _, c_off = run_worker(_UTTER, _HIST, digest=_DIGEST)
    check("the digest is not rendered while the flag is off",
          "Context digest:" not in si_of(c_off))
    check("with the flag off the prompt is byte-identical to today's",
          si_of(c_off) == si_of(c_plain))

    gw.AUTO_REPLY_CONTEXT_DIGEST = True
    _, c_on = run_worker(_UTTER, _HIST, digest=_DIGEST)
    si_on = si_of(c_on)
    check("the digest renders a Context digest section", "Context digest:" in si_on)
    # ``Speaker profile`` (no colon) so the anchor is the real profile line, not
    # the digest's own "Extracted Speaker profile:" heading.
    check("the section sits after the profile lines and before Objective:",
          0 < si_on.find("Context digest:") < si_on.find("Objective:")
          and 0 < si_on.find("Speaker profile") < si_on.find("Context digest:")),
    check("the rolling bullets are listed", "- Brief gets lost at handoff" in si_on)
    check("locked bullets carry the [locked] marker",
          "- [locked] Helpy captures both sides into a shared brief" in si_on)
    check("the extracted KYC profile is in the prompt with the digest on",
          "- Occupation: Head of Operations" in si_on
          and "- Goals: cut handoff loss" in si_on
          and "- Pain points: brief lost in Slack" in si_on)
    check("the confirmed brief is in the prompt",
          "Confirmed client brief:" in si_on and "Cut handoff loss by half." in si_on)
    check("the app's own prior suggestions are in the prompt",
          "Already suggested (do not repeat these):" in si_on
          and "Name the capture step first." in si_on
          and "Talk about the shared brief." in si_on)
    check("an empty suggestion adds no line",
          si_on.count("Already suggested") == 1 and "- a1" not in si_on)
    _, c_empty = run_worker(_UTTER, _HIST, digest={})
    check("an empty digest renders no section at all",
          "Context digest:" not in si_of(c_empty))
finally:
    gw.AUTO_REPLY_CONTEXT_DIGEST = _prev_flag

# Caps — asserted on the pure builder, so they hold regardless of the flag.
_many = build_digest([f"bullet {i}" for i in range(25)], [False] * 25, {}, "", [])
check("only the most recent bullets are sent",
      len(_many["bullets"]) == AUTO_REPLY_MAX_BULLETS == 20
      and _many["bullets"][0] == "bullet 5" and _many["bullets"][-1] == "bullet 24")
_long = build_digest(["word " * 100], [], {}, "", [])
check("each bullet is truncated",
      len(_long["bullets"][0]) <= AUTO_REPLY_MAX_BULLET_CHARS
      and _long["bullets"][0].endswith("…"))
_profiled = build_digest([], [], {"goals": [f"g{i}" for i in range(9)]}, "", [])
check("each KYC list field is capped",
      len(_profiled["speaker"]["goals"]) == AUTO_REPLY_MAX_PROFILE_ITEMS == 5)
_suggs = build_digest([], [], {}, "", [{"role": "speaker", "suggestion": f"s{i}"} for i in range(5)])
check("only the last few prior suggestions are shown",
      _suggs["prior_suggestions"] == ["s2", "s3", "s4"]
      and AUTO_REPLY_MAX_PRIOR_SUGGESTIONS == 3)
check("the brief is truncated",
      len(build_digest([], [], {}, "b" * 5000, [])["brief"]) <= AUTO_REPLY_MAX_BRIEF_CHARS)
check("an all-empty input builds an empty digest",
      build_digest([], [], {}, "", []) == {}
      and build_digest(["  "], [True], {}, "", [{"role": "speaker", "suggestion": " "}]) == {})

# The finished reply is recorded on the turn it answered, without the analysis
# preamble, and without mutating the shared history objects in place.
ctrl_sugg = TranslationController()
ctrl_sugg.load_conversation_history([
    {"role": "speaker", "text": "q1", "suggestion": ""},
    {"role": "host", "text": "a1", "suggestion": ""},
])
before = ctrl_sugg.get_conversation_history()
ctrl_sugg._record_suggestion("Speaker's move: Assertive — they asked how.\n\nIndonesian Text: Halo.")
after = ctrl_sugg.get_conversation_history()
check("the reply lands on the turn it answered",
      after[0]["suggestion"] == "Indonesian Text: Halo.")
check("the analysis preamble is stripped from the suggestion",
      "Speaker's move" not in after[0]["suggestion"])
check("the host turn is left alone", after[1]["suggestion"] == "")
check("the previous history objects are not mutated in place",
      before[0]["suggestion"] == "" and before[1]["suggestion"] == "")
check("the recorded suggestion feeds the digest",
      build_digest([], [], {}, "", after)["prior_suggestions"]
      == ["Indonesian Text: Halo."])
ctrl_img = TranslationController()
ctrl_img.load_conversation_history([{"role": "speaker", "text": "q", "suggestion": ""}])
ctrl_img._auto_reply_is_image = True
ctrl_img._on_auto_reply_result("image answer")
check("an image reply is not recorded as a suggestion",
      ctrl_img.get_conversation_history()[0]["suggestion"] == "")

# Controller plumbing: the digest reaches the voice worker, never the image one.
ctrl_wire = TranslationController()
ctrl_wire.set_session_digest({"bullets": ["x"]})
captured = {}
# The controller imported the worker class by value, so patch *its* module global
# (patching src.gemini_worker would leave a real worker — and a real AI call —
# running in this offline gate).
_RealWorker = tc.GeminiAutoReplyWorker


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass


class _CaptureWorker:
    """Not a QThread: it only records the kwargs the controller builds."""

    def __init__(self, *args, **kwargs):
        captured.clear()
        captured.update(kwargs)
        self.result = self.error = self.chunk = self.skipped = self.status = _FakeSignal()

    def start(self):
        pass

    def isRunning(self):
        return False


tc.GeminiAutoReplyWorker = _CaptureWorker
try:
    ctrl_wire._start_auto_reply_worker("hi")
    voice_digest = captured.get("digest")
    ctrl_wire._auto_reply_worker = None
    ctrl_wire._start_auto_reply_worker("", images=["data:image/jpeg;base64,AA"], is_image=True)
    image_digest = captured.get("digest")
    ctrl_wire._auto_reply_worker = None
finally:
    tc.GeminiAutoReplyWorker = _RealWorker
check("the digest reaches the voice worker", voice_digest == {"bullets": ["x"]})
check("the image reply path still carries no digest (follow-up)", image_digest is None)
check("get_session_digest mirrors what was set",
      ctrl_wire.get_session_digest() == {"bullets": ["x"]})

# MainWindow._rebuild_reply_digest — assembled from session state, confirmed brief only.


class _DigestStub:
    _consulting_reference = ui.MainWindow._consulting_reference

    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.seen = []
        self.session_store = types.SimpleNamespace(snapshot=lambda: dict(self._snapshot))
        self.translation_controller = types.SimpleNamespace(
            get_conversation_history=lambda: self._snapshot.get("conversation") or [],
            set_session_digest=lambda d: self.seen.append(d),
        )


_snapshot = {
    "bullets": ["locked one"],
    "bullet_locks": [True],
    "speaker": {"occupation": "Ops"},
    "brief": "Draft brief",
    "brief_meta": {"confirmed": False},
    "conversation": [{"role": "speaker", "text": "q", "suggestion": "s1"}],
}
_stub = _DigestStub(_snapshot)
ui.MainWindow._rebuild_reply_digest(_stub)
check("the digest is assembled from the session state",
      len(_stub.seen) == 1 and _stub.seen[0]["locked"] == ["locked one"]
      and _stub.seen[0]["speaker"] == {"occupation": "Ops"}
      and _stub.seen[0]["prior_suggestions"] == ["s1"])
check("an unconfirmed brief is kept out of the digest", _stub.seen[0]["brief"] == "")
_snapshot["brief_meta"] = {"confirmed": True}
_stub.seen.clear()
ui.MainWindow._rebuild_reply_digest(_stub)
check("a confirmed brief is carried into the digest",
      _stub.seen[0]["brief"] == "Draft brief")

# =====================================================================
# [19] Objective focus in the auto-reply prompt (P2)
# =====================================================================
print("\n[19] Objective focus — the tracked objective reaches the prompt")

_OBJS = ["Ship the pilot", "Agree on pricing"]
_missing = si_of(run_worker(_UTTER, _HIST)[1])
check("no objectives means no Objective focus section",
      "Objective focus:" not in _missing)
_untracked = si_of(run_worker(_UTTER, _HIST, objectives=_OBJS, locks=[False, False], meta={})[1])
check("objectives without a tracked focus add nothing", "Objective focus:" not in _untracked)

_tracked = si_of(run_worker(
    _UTTER, _HIST, objectives=_OBJS, locks=[False, False],
    meta={"active": 1, "confidence": 0.82, "source": "jev"})[1])
check("the tracked objective is rendered",
      "Objective focus:" in _tracked
      and "- Working towards: Agree on pricing" in _tracked)
check("the focus names its confidence and source",
      "confidence 0.82, from jev" in _tracked)
check("the focus sits before the persona Objective: section",
      0 < _tracked.find("Objective focus:") < _tracked.find("Objective:"))
check("an unlocked objective is not marked as locked",
      "locked by the user" not in _tracked)

_pinned = si_of(run_worker(
    _UTTER, _HIST, objectives=_OBJS, locks=[True, False],
    meta={"active": 1, "confidence": 0.99, "source": "jev"})[1])
check("a locked objective beats the prediction in the prompt",
      "- Working towards: Ship the pilot" in _pinned
      and "Agree on pricing" not in _pinned)
check("a locked objective is marked and the reply is told to serve it",
      "- This objective is locked by the user; serve it." in _pinned)

# The prediction itself: the reply's own decision call answers current_objective.
_captured = {}


class _CaptureDecision:
    available = True

    def decide(self, state, questions):
        _captured["questions"] = questions
        _captured["state"] = state
        return {}


_obj_worker = gw.GeminiAutoReplyWorker(
    _UTTER, "English", conversation_history=list(_HIST), include_pronunciation=False,
    purpose="consultation", host_role="consultant", objectives=_OBJS,
    objective_locks=[False, True], objective_meta={"active": 0, "confidence": 0.6})
_obj_worker._decision_client = _CaptureDecision()
_obj_worker._run_decision(_obj_worker._resolve_purpose(), ROLES, "consultant")
check("the decision call asks which objective is current",
      _captured["questions"]["current_objective"]["type"] == "choice"
      and set(_captured["questions"]["current_objective"]["criteria"].values()) == set(_OBJS))
check("the decision state carries the objectives and the resolved focus",
      _captured["state"]["objectives"] == _OBJS
      and _captured["state"]["active_objective"]["index"] == 1)
check("with no objectives the decision asks nothing about them",
      "current_objective" not in build_questions({}, {}, [], False, [], None))

_DECISION_OBJ = {
    "current_objective": {"type": "choice", "choice": "agree_on_pricing", "confidence": 0.91},
    "speech_act": {"type": "choice", "choice": "directive", "confidence": 0.9},
}
_obs_worker_client = FakeClient("English Text: canned")
gw.get_ai_client = lambda: _obs_worker_client
_obs_worker = gw.GeminiAutoReplyWorker(
    _UTTER, "English", conversation_history=list(_HIST), include_pronunciation=False,
    purpose="consultation", host_role="consultant", jev_enabled=True, objectives=_OBJS)
_obs_worker._run_decision = lambda *a, **k: _DECISION_OBJ
observed = []
_obs_worker.objective_observed.connect(
    lambda index, confidence, source: observed.append((index, confidence, source)))
_obs_worker.run()
check("the reply's JEV answer is emitted as an observation",
      observed == [(1, 0.91, "jev")], str(observed))
check("the observation does not disturb the reply itself",
      len(_obs_worker_client.calls) == 1)

_low_worker = gw.GeminiAutoReplyWorker(
    _UTTER, "English", conversation_history=list(_HIST), include_pronunciation=False,
    purpose="consultation", host_role="consultant", objectives=_OBJS)
check("an unconfident objective answer is ignored",
      _low_worker._run_objective_decision({
          "current_objective": {"type": "choice", "choice": "agree_on_pricing",
                                "confidence": 0.2}})
      == (None, 0.0))
check("an unknown objective key is ignored",
      _low_worker._run_objective_decision({
          "current_objective": {"type": "choice", "choice": "nope", "confidence": 0.99}})
      == (None, 0.0))
check("a worker with no objectives never predicts one",
      gw.GeminiAutoReplyWorker(
          _UTTER, "English", conversation_history=list(_HIST),
          include_pronunciation=False)._run_objective_decision({
              "current_objective": {"type": "choice", "choice": "x", "confidence": 1.0}})
      == (None, 0.0))

# =====================================================================
# summary
# =====================================================================
print()
if STRICT:
    print("STRICT mode: witnesses are treated as failures.")
print("WITNESSES (known limitations; pass unless AUTO_REPLY_STRICT=1):")
for name, present, note in witnesses:
    print(f"  {'PRESENT' if present else 'ABSENT '}  {name}" + (f"  ({note})" if note else ""))

print()
print(f"{n_pass} checks passed, {len(failures)} failed.")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
