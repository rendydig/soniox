"""Temp check: the auto-reply answer-quality contract — LIVE tier (real model).

The opt-in half of the auto-reply regression suite. It runs the REAL
``GeminiAutoReplyWorker`` against the provider configured in ``.env`` and asserts
the reply with deterministic keyword/regex contracts. This is the tier that
actually catches "the AI did not answer the Speaker's question" — the reported
symptom. It is non-deterministic by nature, so it is skipped unless explicitly
enabled, and the cheap offline gate (`_tmp_auto_reply_prompt_check.py`) stays the
merge gate.

Run from the repo root:
    AUTO_REPLY_LIVE_TESTS=1 venv/bin/python _tmp_auto_reply_live_check.py

It exits 0 with a notice when the flag is unset or the provider cannot be built
(missing key), so CI without credentials is a no-op. Each scenario prints the
actual reply so a human can judge it as well.
"""
import json
import os
import re
import sys
import time

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

if os.environ.get("AUTO_REPLY_LIVE_TESTS") != "1":
    print("SKIP: live tier disabled. Set AUTO_REPLY_LIVE_TESTS=1 to run it.")
    sys.exit(0)

import src.gemini_worker as gw  # noqa: E402
from src.config import AI_BASE_URL, AI_MODEL, AI_PROVIDER, DISABLE_MODEL_REASONING  # noqa: E402

failures = []
witnesses = []
n_pass = 0
latencies = []


def check(name, cond, detail=""):
    global n_pass
    ok = bool(cond)
    if ok:
        n_pass += 1
    else:
        failures.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


def witness(name, present, note=""):
    witnesses.append((name, bool(present), note))
    tag = "WITNESS-HIT" if present else "WITNESS-OK "
    print(tag + "  " + name + (f"  ({note})" if note else ""))


# --- provider ------------------------------------------------------------
try:
    gw.get_ai_client()  # force the config error (missing key) now, not mid-suite
except Exception as e:  # noqa: BLE001 - any config/build failure means "skip"
    print(f"SKIP: cannot build the provider client ({type(e).__name__}: {e})")
    sys.exit(0)

print(f"provider={AI_PROVIDER} model={AI_MODEL} base={AI_BASE_URL} "
      f"disable_reasoning={DISABLE_MODEL_REASONING}")
print()

# --- fixtures ------------------------------------------------------------
def read_file(*parts):
    try:
        with open(os.path.join(REPO, *parts), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


HELPY = read_file("docs", "helpy.context.txt")
MAYA = read_file("maya.context.txt") or "Her name is Maya."
CTX = {"host": HELPY or "HOSTCTX", "speaker": MAYA}

PRODUCT_TERMS = ["helpy", "brief", "gap", "gaps", "summary", "notes", "note",
                 "capture", "roadmap", "transcript", "both sides"]

# Generic SaaS words the model should NOT reach for when no Host profile is
# attached: their presence is a hallucinated product, not a grounded one.
INVENTION_TERMS = ["dashboard", "integrations", "integration", "platform", "api",
                   "subscription", "onboarding", "sign up", "account", "accounts",
                   "crm", "pipeline"]


def load_recorded_conversation():
    try:
        with open(os.path.join(REPO, "sessions", "current.json"), encoding="utf-8") as f:
            return (json.load(f) or {}).get("conversation") or []
    except (OSError, ValueError):
        return []


def live(text, history, *, context=None, purpose="consultation",
         host_role="consultant", target="English"):
    out = {"text": "", "error": "", "chunks": [], "skipped": ""}
    worker = gw.GeminiAutoReplyWorker(
        text, target, conversation_history=list(history),
        include_pronunciation=False, purpose=purpose, host_role=host_role,
        context=context,
    )
    worker.result.connect(lambda t: out.__setitem__("text", t))
    worker.error.connect(lambda t: out.__setitem__("error", t))
    worker.chunk.connect(lambda t: out["chunks"].append(t))
    worker.skipped.connect(lambda t: out.__setitem__("skipped", t))
    t0 = time.monotonic()
    worker.run()
    out["latency_ms"] = round((time.monotonic() - t0) * 1000)
    latencies.append(out["latency_ms"])
    if not out["text"] and not out["error"] and not out["skipped"]:
        out["error"] = "no result and no error"
    return out


def body_of(reply):
    """Drop the 'Speaker's move:' preamble and unwrap any '<Language> Text:' header.

    The model writes the reply on the SAME line as the header
    (``English Text: <reply>``), so the header is unwrapped, not dropped.
    """
    keep = []
    for line in reply.split("\n"):
        s = line.strip()
        if s.startswith("Speaker's move:"):
            continue
        m = re.match(r"^\w+ Text:\s*(.*)$", s)
        if m:
            keep.append(m.group(1))
            continue
        keep.append(line)
    return "\n".join(keep).strip()


def mentions(text, words):
    return sorted({w for w in words if re.search(rf"\b{re.escape(w)}\b", text, re.I)})


def first_sentence(text):
    m = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)
    return m[0] if m else text.strip()


def show(label, out):
    if out["error"]:
        print(f"  {label} ERROR: {out['error']}")
    else:
        print(f"  {label} ({out['latency_ms']} ms):")
        for line in out["text"].split("\n"):
            print("      | " + line)


# =====================================================================
print("[L1/headline] Replay the recorded question that failed")
recorded = load_recorded_conversation()
q_idx = -1
for i in range(len(recorded) - 1, -1, -1):
    if recorded[i].get("role") != "host" and \
            "stop that from happening" in (recorded[i].get("text") or "").lower():
        q_idx = i
        break
L1_REPEAT = max(1, int(os.environ.get("AUTO_REPLY_LIVE_REPEAT", "1") or "1"))
if q_idx < 0:
    print("  SKIP — no recorded question")
else:
    question = recorded[q_idx]["text"].strip()
    produced = 0
    grounded = 0
    for k in range(L1_REPEAT):
        out = live(question, recorded[: q_idx + 1], context=CTX)
        show(f"reply[{k + 1}/{L1_REPEAT}]", out)
        if out["text"] and not out["error"]:
            produced += 1
        hit = mentions(body_of(out["text"]), PRODUCT_TERMS)
        if hit:
            grounded += 1
        print("       matched=%s" % hit)
    check("a reply was produced", produced == L1_REPEAT, f"{produced}/{L1_REPEAT}")
    check("the reply names a product mechanism (brief/gaps/notes/...)",
          grounded == L1_REPEAT, f"{grounded}/{L1_REPEAT} grounded")
    witness("the answer is generic design-process advice, not the product",
            grounded < L1_REPEAT, f"{L1_REPEAT - grounded}/{L1_REPEAT} ungrounded")

# =====================================================================
print("\n[L2] Speaker asks a question — answer it, do not echo a question back")
out = live("How does your tool actually fix the handoffs?",
           [{"role": "speaker", "text": "How does your tool actually fix the handoffs?",
             "suggestion": ""}], context=CTX)
show("reply", out)
body = body_of(out["text"])
check("a reply was produced", bool(out["text"]) and not out["error"], out["error"])
check("the first sentence is not a question back", not first_sentence(body).endswith("?"),
      first_sentence(body))
check("it is not a bare acknowledgment",
      not re.match(r"^(thanks|thank you|great question|certainly|sure)\b", body, re.I))
check("the answer has substance (>= 10 words)", len(body.split()) >= 10, str(len(body.split())))

# =====================================================================
print("\n[L3] Product question is grounded in the Host profile")
out = live("How would your tool stop that constant back-and-forth?",
           [{"role": "speaker", "text": "How would your tool stop that constant back-and-forth?",
             "suggestion": ""}], context=CTX)
show("reply", out)
body = body_of(out["text"])
hit = mentions(body, PRODUCT_TERMS)
check("the reply mentions at least one product fact", bool(hit), "matched=%s" % hit)
witness("no product fact in the answer despite a 12 KB Host profile attached",
        not hit, "grounding decay")

# =====================================================================
print("\n[L4] Ack then a new question — stay in the Consultant voice")
out = live("How do we stop that from happening?", [
    {"role": "speaker", "text": "how exactly would your tool stop that back-and-forth?", "suggestion": ""},
    {"role": "host", "text": "Helpy captures both sides into a shared brief.", "suggestion": ""},
    {"role": "speaker", "text": "Exactly.", "suggestion": ""},
    {"role": "speaker", "text": "You nailed it.", "suggestion": ""},
    {"role": "speaker", "text": "How do we stop that from happening?", "suggestion": ""},
], context=CTX)
show("reply", out)
body = body_of(out["text"])
client_voice = bool(re.search(r"\bmy (concrete )?need\b|\bwhat I(?:'d| would) need\b", body, re.I))
check("no client-voice inversion", not client_voice, "matched" if client_voice else "")
witness("the reply switched to the Client's voice", client_voice, "role inversion")

# =====================================================================
print("\n[L5] Filler-only utterance — skipped without calling the model")
out = live("Okay.", [{"role": "speaker", "text": "Okay.", "suggestion": ""}], context=CTX)
show("reply", out)
check("no AI call is made for a filler", not out["text"] and not out["error"],
      out["error"] or "a reply was produced")
check("the skip is reported as a filler", out["skipped"] == "Filler utterance",
      repr(out["skipped"]))
witness("a filler ('Okay.') still gets a full AI suggestion", bool(out["text"]),
        "cause 6 / F6")

# =====================================================================
print("\n[L7] No Host context selected — do not invent product claims")
out = live("How does it work?", [{"role": "speaker", "text": "How does it work?", "suggestion": ""}],
           context={"host": "", "speaker": ""})
show("reply", out)
body = body_of(out["text"])
hit = mentions(body, PRODUCT_TERMS)
check("no helpy-specific claim is invented without a Host profile", not hit, "matched=%s" % hit)
invented = mentions(body, INVENTION_TERMS)
witness("the model invents generic product features when no Host profile is attached",
        bool(invented), "invented=%s" % invented)

# =====================================================================
print("\n[L10] Cross-language — Speaker in Indonesian")
out = live("Bagaimana caranya supaya brief tidak hilang saat serah terima?",
           [{"role": "speaker",
             "text": "Bagaimana caranya supaya brief tidak hilang saat serah terima?",
             "suggestion": ""}], context=CTX)
show("reply", out)
body = body_of(out["text"])
check("a reply was produced", bool(out["text"]) and not out["error"], out["error"])
check("the analysis preamble is still present (English)", "Speaker's move:" in out["text"])
check("the reply body is Indonesian",
      bool(mentions(body, ["tidak", "dengan", "untuk", "yang", "bisa", "kita", "brief",
                           "proses", "supaya", "saat", "dan", "kli\u00ebn", "klien"])),
      body[:80])
check("the reply declares the Indonesian header",
      bool(re.search(r"Indonesian Text:|Bahasa Indonesia", out["text"])))

# =====================================================================
print()
print("WITNESSES (known limitations):")
for name, present, note in witnesses:
    print(f"  {'PRESENT' if present else 'ABSENT '}  {name}" + (f"  ({note})" if note else ""))

if latencies:
    print()
    print(f"latency: min={min(latencies)} ms  max={max(latencies)} ms  "
          f"avg={sum(latencies) // len(latencies)} ms  (reasoning disabled="
          f"{DISABLE_MODEL_REASONING})")

print()
print(f"{n_pass} checks passed, {len(failures)} failed.")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
