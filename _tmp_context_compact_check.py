"""Temp check: Context compaction + the shared reference-context block.

Three layers, all offline (the AI client is stubbed — no network, no key):

  1. ``src/reference_context.py``: the renderer the interpreting workers share.
  2. The four interpretation workers (bullet points / KYC profile, Last Picked
     Up, objectives, summary) really carry the block — and, with no context,
     their prompt is byte-identical to the pre-feature one.
  3. ``ContextCompactWorker`` + ``ContextCompactController``: the one-shot
     "Compact" call behind the Context pane's button.

    venv/bin/python _tmp_context_compact_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import os
import sys
import time

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import src.bullet_points_worker as bpw  # noqa: E402
import src.context_compact_worker as ccw  # noqa: E402
import src.last_pickup_worker as lpw  # noqa: E402
import src.objective_worker as ow  # noqa: E402
import src.summarize_worker as sw  # noqa: E402
from src.config import (  # noqa: E402
    CONTEXT_COMPACT_MIN_CHARS,
    REFERENCE_CONTEXT_MAX_CHARS,
)
from src.controllers.context_compact_controller import ContextCompactController  # noqa: E402
from src.reference_context import (  # noqa: E402
    has_context,
    normalize,
    render_reference_context,
)

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


def wait_for(predicate, timeout_ms=5000):
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeClient:
    """Stand-in for ``AIClient``: records the call and returns a canned reply."""

    def __init__(self, reply="short version", fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = []

    def generate(self, system_instruction, messages, disable_reasoning=None):
        self.calls.append({
            "system": system_instruction,
            "messages": messages,
            "disable_reasoning": disable_reasoning,
        })
        if self.fail:
            raise RuntimeError("boom")
        return self.reply


CTX = {"host": "We sell Helpy, a consulting copilot.", "speaker": "Maya, VP Ops at Acme."}

# ---------------------------------------------------------------------------
print("[1] src/reference_context.py")
check("normalize tolerates None", normalize(None) == {"host": "", "speaker": ""})
check("normalize tolerates a non-dict", normalize(["nope"]) == {"host": "", "speaker": ""})
check("normalize strips and coerces",
      normalize({"host": "  a  ", "speaker": 7}) == {"host": "a", "speaker": ""})
check("has_context is False when empty", not has_context({"host": "", "speaker": "  "}))
check("has_context is True with one role", has_context({"host": "x", "speaker": ""}))
check("nothing renders for no context", render_reference_context(None) == "")
check("nothing renders for empty strings", render_reference_context({"host": "", "speaker": ""}) == "")

both = render_reference_context(CTX)
check("both roles are labelled",
      "Host (us): We sell Helpy" in both and "Speaker: Maya, VP Ops" in both, both[:80])
check("the block says reference-only", "do NOT copy or restate" in both)
check("the block ends with a blank line", both.endswith("\n\n"))
only_host = render_reference_context({"host": "H", "speaker": ""})
check("a single role omits the other", "Host (us): H" in only_host and "Speaker:" not in only_host)
check("the label is overridable",
      render_reference_context(CTX, label="Background").startswith("Background ("))

huge = render_reference_context({"host": "y" * (REFERENCE_CONTEXT_MAX_CHARS + 500), "speaker": ""})
check("a long role is clipped", str(REFERENCE_CONTEXT_MAX_CHARS) in huge and len(huge) < 7000,
      str(len(huge)))
check("the clip is marked", "…[truncated at" in huge)

# ---------------------------------------------------------------------------
print("\n[2] the four interpreting workers carry the block")
bullet_ctx = bpw.BulletPointsWorker([], {}, [("host", "hi")], context=CTX)
bullet_plain = bpw.BulletPointsWorker([], {}, [("host", "hi")])
bullet_msg = bullet_ctx._build_user_message()
check("bullet points prompt has the block",
      "Reference context" in bullet_msg)
check("bullet points prompt carries the HOST half", "We sell Helpy" in bullet_msg)
check("bullet points prompt omits the SPEAKER half",
      "Maya, VP Ops" not in bullet_msg and "Speaker:" not in bullet_msg,
      bullet_msg[:60].replace("\n", " "))
check("bullet points prompt is unchanged without context",
      bullet_plain._build_user_message()
      == bpw.BulletPointsWorker([], {}, [("host", "hi")])._build_user_message()
      and "Reference context" not in bullet_plain._build_user_message())
check("bullet points rebuild also has it",
      "Reference context" in bpw.BulletPointsWorker(
          [], {}, [("host", "hi")], rebuild=True, context=CTX)._build_user_message())
check("the system instruction tells it not to copy",
      "never copy or restate" in bpw.SYSTEM_INSTRUCTION)

pickup_ctx = lpw.LastPickupWorker([("speaker", "hi")], context=CTX)
pickup_plain = lpw.LastPickupWorker([("speaker", "hi")])
check("last pickup prompt has the block",
      "Reference context" in pickup_ctx._build_user_message())
check("last pickup prompt carries BOTH halves (unlike the KYC worker)",
      "We sell Helpy" in pickup_ctx._build_user_message()
      and "Maya, VP Ops" in pickup_ctx._build_user_message())
check("last pickup prompt is unchanged without context",
      "Reference context" not in pickup_plain._build_user_message()
      and pickup_plain._build_user_message() == "Latest conversation lines:\n[speaker] hi")

obj_ctx = ow.ObjectiveWorker([("speaker", "hi")], ["Ship it"], context=CTX)
obj_plain = ow.ObjectiveWorker([("speaker", "hi")], ["Ship it"])
check("objective prompt has the block",
      "Reference context" in obj_ctx._build_user_message())
check("objective prompt carries BOTH halves",
      "We sell Helpy" in obj_ctx._build_user_message()
      and "Maya, VP Ops" in obj_ctx._build_user_message())
check("objective prompt is unchanged without context",
      obj_plain._build_user_message()
      == "Objectives (JSON list, in order):\n[\"Ship it\"]\n\n"
         "Conversation window:\n[speaker] hi\n\nLatest utterance: hi")
check("the objective instruction forbids adding context items",
      "never\n  treat it as an objective" in ow.SYSTEM_INSTRUCTION)

sum_ctx = sw.SummarizeWorker([("speaker", "hi")], ["b"], {"name": "Maya"}, context=CTX)
sum_plain = sw.SummarizeWorker([("speaker", "hi")], ["b"], {"name": "Maya"})
check("summary prompt has the block",
      "Reference context" in sum_ctx._build_user_message())
check("summary prompt carries BOTH halves",
      "We sell Helpy" in sum_ctx._build_user_message()
      and "Maya, VP Ops" in sum_ctx._build_user_message())
check("summary prompt is unchanged without context",
      "Reference context" not in sum_plain._build_user_message())
check("the block comes before the transcript",
      sum_ctx._build_user_message().index("Reference context")
      < sum_ctx._build_user_message().index("Conversation transcript"))

# ---------------------------------------------------------------------------
print("\n[3] ContextCompactWorker")
fake = FakeClient(reply="  Helpy: a copilot.  ")
ccw.get_ai_client = lambda: fake
body = "z" * 900
worker = ccw.ContextCompactWorker("host", body, "ctx.md")
results = []
errors = []
worker.result.connect(lambda role, path, text: results.append((role, path, text)))
worker.error.connect(lambda role, msg: errors.append((role, msg)))
worker.start()
wait_for(lambda: results or errors)
check("one AI call", len(fake.calls) == 1, str(len(fake.calls)))
if fake.calls:
    call = fake.calls[0]
    check("the document rode in the user message", body in call["messages"][0]["text"])
    check("the call names the role", "Host context" in call["messages"][0]["text"])
    check("reasoning is off", call["disable_reasoning"] is True)
    check("the instruction demands fact completeness", "Keep EVERY fact" in call["system"])
    check("the instruction forbids invention", "Never invent" in call["system"])
check("the result carries role, path and stripped text",
      results and results[0] == ("host", "ctx.md", "Helpy: a copilot."), str(results))
check("no error", not errors)

print("\n[3b] ContextCompactWorker: an empty reply is an error")
fake_empty = FakeClient(reply="   ")
ccw.get_ai_client = lambda: fake_empty
worker2 = ccw.ContextCompactWorker("speaker", body, "ctx.md")
errors2 = []
worker2.error.connect(lambda role, msg: errors2.append((role, msg)))
worker2.start()
wait_for(lambda: errors2)
check("reported as an error", errors2 and errors2[0][0] == "speaker", str(errors2))

# ---------------------------------------------------------------------------
print("\n[4] ContextCompactController")
controller = ContextCompactController()
compacted = []
statuses = []
controller.compacted.connect(lambda role, path, text: compacted.append((role, path, text)))
controller.status_changed.connect(lambda role, status: statuses.append((role, status)))

check("an empty text does not spend a call",
      controller.trigger_now("host", "   ") is False and statuses[-1] == ("host", "no_input"))
short = "s" * (CONTEXT_COMPACT_MIN_CHARS - 1)
check("a short file does not spend a call",
      controller.trigger_now("host", short) is False and statuses[-1] == ("host", "too_short"))
check("no role is invalid",
      controller.trigger_now("", body) is False and statuses[-1] == ("", "invalid"))
check("nothing ran", not controller.is_busy() and not compacted)

fake3 = FakeClient(reply="compacted body")
ccw.get_ai_client = lambda: fake3
started = controller.trigger_now("host", body, "ctx.md")
check("started", started is True and ("host", "started") in statuses)
check("busy while running", controller.is_busy())
check("a second call is refused while busy", controller.trigger_now("speaker", body) is False)
wait_for(lambda: compacted)
check("result emitted", compacted[-1] == ("host", "ctx.md", "compacted body"), str(compacted))
check("complete status", ("host", "complete") in statuses)
check("no longer busy", wait_for(lambda: not controller.is_busy()))

print("\n[4b] ContextCompactController: the error path")
fake4 = FakeClient(fail=True)
ccw.get_ai_client = lambda: fake4
errors3 = []
controller.error_occurred.connect(errors3.append)
controller.trigger_now("speaker", body, "s.md")
wait_for(lambda: errors3)
check("the failure is reported", bool(errors3), str(errors3[:1]))
check("status carried the role", ("speaker", "error") in statuses, str(statuses[-2:]))

controller.reset()
check("reset clears the in-flight role", controller._role == "")
controller.cleanup()
check("cleanup leaves no thread", controller._worker is None)

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
