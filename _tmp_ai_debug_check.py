"""Temp check: the DEBUG-gated AI prompt dump (``src/ai_debug.py``).

Offline, deterministic, no network: every AI call site is driven with a stubbed
provider client (and a stubbed JEV POST) while the dump is redirected to a temp
file. Asserts:

  * with logging at DEBUG, one block per label is written, containing the label,
    the full system instruction, the messages and the reply;
  * the auto-reply block reports ``digest_flag=true|false`` matching
    ``AUTO_REPLY_CONTEXT_DIGEST`` and ``digest_block=off|on`` matching the
    rendered prompt;
  * with the logger forced to INFO, **nothing** is written (the toggle);
  * no image data URL ever reaches the file (images are counted).

Run from the repo root:
    venv/bin/python _tmp_ai_debug_check.py
"""
import json
import os
import sys
import tempfile

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import logging  # noqa: E402

import src.ai_debug as ai_debug  # noqa: E402

failures = []
n_pass = 0


def check(name, cond, detail=""):
    global n_pass
    ok = bool(cond)
    if ok:
        n_pass += 1
    else:
        failures.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# --- redirect the dump to a temp file ------------------------------------
_tmpdir = tempfile.mkdtemp(prefix="ai-debug-")
DUMP = os.path.join(_tmpdir, "ai-prompt.log")
ai_debug._LOG_PATH = DUMP


def read_dump():
    try:
        with open(DUMP, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def dump_after(fn):
    """Clear the dump, run ``fn()``, return what was appended."""
    open(DUMP, "w").close()
    fn()
    return read_dump()


# --- stub provider client ------------------------------------------------
class FakeClient:
    def __init__(self, reply=""):
        self.reply = reply or ""
        self.calls = []

    def generate(self, system_instruction, messages, disable_reasoning=None):
        self.calls.append({"kind": "generate", "si": system_instruction,
                           "messages": messages})
        return self.reply

    def generate_stream(self, system_instruction, messages, disable_reasoning=None):
        self.calls.append({"kind": "generate_stream", "si": system_instruction,
                           "messages": messages})
        if self.reply:
            yield self.reply


class UnavailableDecision:
    available = False


# --- imports after the temp path is set -----------------------------------
import src.gemini_worker as gw  # noqa: E402
import src.bullet_points_worker as bpw  # noqa: E402
import src.last_pickup_worker as lpw  # noqa: E402
import src.objective_worker as ow  # noqa: E402
import src.summarize_worker as sw  # noqa: E402
import src.consulting_worker as cw  # noqa: E402
import src.decision_client as dc  # noqa: E402
from src.config import AUTO_REPLY_CONTEXT_DIGEST  # noqa: E402
from src.purposes import BUILTIN_PURPOSES, purpose_roles  # noqa: E402

PURPOSE = BUILTIN_PURPOSES["consultation"]
ROLE = purpose_roles(PURPOSE)["consultant"]
UTTER = "Tell me how your pricing works."
HIST = [{"role": "speaker", "text": UTTER, "suggestion": ""}]

# The dump is on whenever the root logger is at DEBUG.
logging.getLogger().setLevel(logging.DEBUG)
assert ai_debug.enabled(), "the dump must be enabled at DEBUG"

# =====================================================================
# [1] one block per label, with label + system instruction + messages + reply
# =====================================================================
print("[1] one block per AI call label")
REPLY = "English Text: the canned reply."
seen = {}


def auto_reply(**kw):
    factory = kw.pop("client_factory", None)
    gw.get_ai_client = factory or (lambda: FakeClient(REPLY))
    worker = gw.GeminiAutoReplyWorker(
        UTTER, "English", conversation_history=list(HIST),
        include_pronunciation=False, purpose="consultation",
        host_role="consultant", context={"host": "", "speaker": ""},
        **kw,
    )
    worker.run()
    return worker


content = dump_after(auto_reply)
seen["auto_reply"] = content
check("auto_reply block: label present", "label=auto_reply" in content)
check("auto_reply block: reply block present", "--- reply    auto_reply-" in content)
check("auto_reply block: the reply text is written", REPLY in content)
check("auto_reply block: the full system instruction is written",
      "You are a conversation analyst" in content or "Objective:" in content)
check("auto_reply block: the message list is written",
      "--- messages (1) ---" in content and UTTER in content)

content = dump_after(
    lambda: gw.GeminiAutoReplyWorker._synthesize(
        gw.GeminiAutoReplyWorker(UTTER, "English", conversation_history=[]),
        FakeClient("{}"), PURPOSE, ROLE,
    )
)
seen["other_flow"] = content
check("other_flow block: label present", "label=other_flow" in content)
check("other_flow block: its instruction is written",
      "conversation analyst" in content)

gw.get_ai_client = lambda: FakeClient("English Text: hi")
content = dump_after(lambda: gw.GeminiWorker("Halo", "English").run())
seen["translation"] = content
check("translation block: label present", "label=translation" in content)
check("translation block: the translator instruction is written",
      "professional translator" in content)
check("translation block: the input text is written", "Text to translate: Halo" in content)

bpw.get_ai_client = lambda: FakeClient('{"bullets": [], "speaker": {}}')
content = dump_after(
    lambda: bpw.BulletPointsWorker([], {}, [("speaker", "hi")]).run()
)
seen["bullet_points"] = content
check("bullet_points block: label present", "label=bullet_points" in content)
check("bullet_points block: mode meta present", "mode=incremental" in content)

lpw.get_ai_client = lambda: FakeClient("pickup")
content = dump_after(lambda: lpw.LastPickupWorker([("speaker", "hi")]).run())
seen["last_pickup"] = content
check("last_pickup block: label present", "label=last_pickup" in content)
check("last_pickup block: lines meta present", "lines=1" in content)

ow.DecisionClient = lambda *a, **k: UnavailableDecision()
ow.get_ai_client = lambda: FakeClient('{"objective": "Grow revenue", "confidence": 0.9}')
content = dump_after(
    lambda: ow.ObjectiveWorker(
        [("speaker", "hi")], ["Grow revenue"]
    ).run()
)
seen["objective"] = content
check("objective block: label present", "label=objective" in content)
check("objective block: count meta present", "count=1" in content)

sw.get_ai_client = lambda: FakeClient("## Overview\ntext")
content = dump_after(
    lambda: sw.SummarizeWorker([("speaker", "hi")], ["a point"], {}).run()
)
seen["summary"] = content
check("summary block: label present", "label=summary" in content)
check("summary block: lines/bullets meta present",
      "lines=1" in content and "bullets=1" in content)

cw.get_ai_client = lambda: FakeClient("## Goals\n- x")
content = dump_after(lambda: cw.ConsultingWorker("brief", [("speaker", "hi")]).run())
seen["consulting"] = content
check("consulting block: label present", "label=consulting" in content)
check("consulting block: mode meta present", "mode=brief" in content)

# JEV decision: a stub URL that answers with a small ``answers`` dict.
class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(
            {"answers": {"should_reply": {"type": "noul", "noul": 0.9}}}
        ).encode("utf-8")


_real_urlopen = dc.urllib.request.urlopen
dc.urllib.request.urlopen = lambda *a, **k: _FakeResp()
try:
    jev_client = dc.DecisionClient(
        api_key="k", base_url="http://jev.test", model="jev-x", enabled=True
    )
    content = dump_after(
        lambda: jev_client.decide({"latest_utterance": "hi"}, {"should_reply": {}})
    )
finally:
    dc.urllib.request.urlopen = _real_urlopen
seen["jev_decision"] = content
check("jev_decision block: label present", "label=jev_decision" in content)
check("jev_decision block: the payload JSON is rendered",
      '"model": "jev-x"' in content and '"state"' in content and '"questions"' in content)
check("jev_decision block: the answers are written as the reply",
      '"noul": 0.9' in content)
check("jev_decision block: model meta present", "model=jev-x" in content)

missing = [lbl for lbl, text in seen.items() if f"label={lbl}" not in text]
check("all nine call labels wrote a block", not missing, str(missing))

# =====================================================================
# [2] digest flag / rendered block (independent values)
# =====================================================================
print("[2] auto-reply digest flag vs rendered block")
# No digest provided: the flag is whatever the config says, but the block can
# only render when there is a digest to render.
content = dump_after(auto_reply)
check("digest flag is written as true|false",
      "digest_flag=true" in content or "digest_flag=false" in content)
check("digest flag matches AUTO_REPLY_CONTEXT_DIGEST",
      ("digest_flag=true" in content) == bool(AUTO_REPLY_CONTEXT_DIGEST),
      f"config={bool(AUTO_REPLY_CONTEXT_DIGEST)}")
check("an empty digest leaves digest_block=off (independent of the flag)",
      "digest_block=off" in content)

digest = {"bullets": ["Budget is the blocker"], "locked": [],
          "speaker": {}, "brief": "", "prior_suggestions": []}

gw.AUTO_REPLY_CONTEXT_DIGEST = True
try:
    content = dump_after(lambda: auto_reply(digest=digest))
    check("digest_flag=true when the flag is on", "digest_flag=true" in content)
    check("digest_block=on when the digest renders", "digest_block=on" in content)
    check("the digest text really is in the dumped prompt",
          "Context digest:" in content and "Budget is the blocker" in content)
finally:
    gw.AUTO_REPLY_CONTEXT_DIGEST = False

# Flag off even with a digest to render: the block stays out, the flag reports false.
content = dump_after(lambda: auto_reply(digest=digest))
check("digest_flag=false when the flag is off", "digest_flag=false" in content)
check("digest_block=off when the flag is off", "digest_block=off" in content)
check("the digest text is absent from the prompt when the flag is off",
      "Context digest:" not in content)

# =====================================================================
# [3] the toggle: LOG_LEVEL=INFO writes nothing
# =====================================================================
print("[3] the toggle (logger at INFO)")
logging.getLogger().setLevel(logging.INFO)
check("enabled() is false at INFO", not ai_debug.enabled())
content = dump_after(auto_reply)
check("nothing is written while at INFO", content == "", repr(content[:80]))
logging.getLogger().setLevel(logging.DEBUG)
content = dump_after(auto_reply)
check("the dump resumes at DEBUG", "label=auto_reply" in content)

# =====================================================================
# [4] images are counted, never dumped
# =====================================================================
print("[4] images")
DATA_URL = "data:image/jpeg;base64," + ("A" * 2048)
content = dump_after(lambda: auto_reply(images=[DATA_URL]))
check("the image data URL never appears in the dump", DATA_URL not in content)
check("only the image count is written", "images=1" in content)
check("the base64 payload does not leak", "A" * 64 not in content)

# =====================================================================
# [5] the exact request payload is attached to its request
# =====================================================================
print("[5] exact request payload")
from src.ai_client import GeminiClient, OpenAICompatibleClient  # noqa: E402


def _bare(cls, model):
    """Build a provider client without its __init__ (no keys, no network)."""
    client = object.__new__(cls)
    client._model = model
    return client


# A client that logs its payload like the real ones do, then answers.
class PayloadClient(FakeClient):
    def _emit(self, system_instruction, messages):
        ai_debug.log_payload({
            "model": "stub-model",
            "messages": [{"role": "user", "content": "hello"}],
            "images": messages[0].get("images") if messages else [],
        })

    def generate(self, system_instruction, messages, disable_reasoning=None):
        self._emit(system_instruction, messages)
        return super().generate(system_instruction, messages, disable_reasoning)

    def generate_stream(self, system_instruction, messages, disable_reasoning=None):
        self._emit(system_instruction, messages)
        yield from super().generate_stream(system_instruction, messages, disable_reasoning)


gw.get_ai_client = lambda: FakeClient(REPLY)
content = dump_after(lambda: auto_reply(client_factory=lambda: PayloadClient(REPLY)))
check("the payload section is written on the request",
      "--- payload (exact request) ---" in content)
check("the payload carries the exact model", '"model": "stub-model"' in content)
check("the payload sits before the reply",
      0 < content.index("--- payload (exact request) ---")
      < content.index("--- reply    auto_reply-"))
check("the payload is inside its own request block",
      content.index("REQUEST  auto_reply-") < content.index("--- payload"))

content = dump_after(lambda: auto_reply(client_factory=lambda: PayloadClient(REPLY), images=[DATA_URL]))
check("a data URL in the payload is elided, not dumped",
      DATA_URL not in content and "chars elided>" in content)

# OpenAI-compatible body: model + messages + the reasoning extra body.
openai_payload = _bare(OpenAICompatibleClient, "openai/x")._payload(
    "SYS", [{"role": "user", "text": "hi"}] + [{"role": "user", "text": "hi", "images": [DATA_URL]}]
)
check("openai payload: model + messages + extra body",
      openai_payload["model"] == "openai/x"
      and openai_payload["messages"][0] == {"role": "system", "content": "SYS"}
      and openai_payload["messages"][1] == {"role": "user", "content": "hi"}
      and openai_payload["messages"][2]["content"][1]["image_url"]["url"] == DATA_URL)
check("openai payload: streaming adds stream=true",
      _bare(OpenAICompatibleClient, "m")._payload("s", [], stream=True).get("stream") is True)

# Gemini body: model + contents (text/inline_data parts) + thinking config.
gem_payload = _bare(GeminiClient, "gemini/x")._payload(
    "SYS", [{"role": "user", "text": "hi", "images": [DATA_URL]}]
)
check("gemini payload: model + contents + system instruction",
      gem_payload["model"] == "gemini/x"
      and gem_payload["config"]["system_instruction"] == "SYS"
      and gem_payload["contents"][0]["parts"][0] == {"text": "hi"}
      and gem_payload["contents"][0]["parts"][1]["inline_data"]["data"] == DATA_URL)
check("gemini payload: reasoning off pins thinking_budget=0",
      gem_payload["config"].get("thinking_config", {}).get("thinking_budget") == 0
      or "thinking_config" not in gem_payload["config"])
check("gemini payload: streaming adds stream=true",
      _bare(GeminiClient, "m")._payload("s", [], stream=True).get("stream") is True)

# A request with no payload (a stubbed client) still writes its block at reply time.
gw.get_ai_client = lambda: FakeClient("English Text: hi")
content = dump_after(lambda: gw.GeminiWorker("Halo", "English").run())
check("a request without a payload is still flushed by log_reply",
      "label=translation" in content and "--- reply    translation-" in content)
check("no payload section when the client did not report one",
      "--- payload (exact request) ---" not in content)

# =====================================================================
# summary
# =====================================================================
print()
print(f"{n_pass} checks passed, {len(failures)} failed.")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
