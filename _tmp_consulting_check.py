"""Temp check: the Consulting tab's worker + controller (AIClient stubbed).

Exercises ``ConsultingWorker`` (per-mode prompt shape) and
``ConsultingController`` (per-mode trigger contract, status flow, seed/reset,
busy guard, error path) with the AI client stubbed — no network call, no real
API. Also asserts the ``brief`` / ``gaps`` / ``roadmap`` / ``brief_meta`` session
fields round-trip through ``current.json`` and survive archiving on New Session.

    venv/bin/python _tmp_consulting_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import sys
import tempfile
import time

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import src.consulting_worker as cw  # noqa: E402
from src.controllers.consulting_controller import ConsultingController  # noqa: E402
from src.config import CONSULTING_MAX_LINE_CHARS  # noqa: E402
from src.session_store import SessionStore  # noqa: E402

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

    def __init__(self, reply="## Goals\n\n- Grow the team", fail=False):
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


class FakeRunningWorker:
    """A stand-in that reports itself as running, for the busy-guard check."""

    def isRunning(self):
        return True


LINES = [
    ("host", "Ceritakan tantangan tim Anda"),
    ("speaker", "Kami butuh dua kandidat dan ingin performa lebih baik"),
    ("host", "x" * (CONSULTING_MAX_LINE_CHARS + 50)),
]
SPEAKER = {"name": "Budi", "goals": ["Grow the team"]}
CONTEXT = {"host": "Host notes", "speaker": "Speaker is a CTO in Jakarta"}

print("[1] the brief prompt carries transcript + speaker profile + context")
worker = cw.ConsultingWorker("brief", LINES, speaker=SPEAKER, context=CONTEXT)
message = worker._build_user_message()
check("[host] line rendered", "[host] Ceritakan tantangan tim Anda" in message)
check("[speaker] line rendered",
      "[speaker] Kami butuh dua kandidat dan ingin performa lebih baik" in message)
check("speaker JSON present",
      json.dumps(SPEAKER, ensure_ascii=False) in message)
check("speaker context present", "Speaker context:" in message and "CTO in Jakarta" in message)
check("long line truncated to CONSULTING_MAX_LINE_CHARS",
      ("x" * CONSULTING_MAX_LINE_CHARS) in message
      and ("x" * (CONSULTING_MAX_LINE_CHARS + 1)) not in message)
check("labelled blocks present",
      "Conversation transcript:" in message and "Speaker profile (JSON):" in message)
check("brief system prompt defines the six sections",
      all(section in cw.SYSTEM_INSTRUCTIONS["brief"] for section in (
          "## Goals", "## Pain Points", "## Constraints", "## Success Metrics",
          "## Scope", "## Open Questions")))

print("\n[2] the gaps prompt carries the confirmed brief, else the profile")
gaps_with_ref = cw.ConsultingWorker(
    "gaps", LINES, reference="## Goals\n\n- Grow the team", speaker=SPEAKER, context=CONTEXT)
msg = gaps_with_ref._build_user_message()
check("transcript present", "[speaker]" in msg)
check("confirmed brief block present", "Reference brief (confirmed):" in msg
      and "- Grow the team" in msg)
check("profile NOT used when a brief is confirmed", "Speaker profile (JSON):" not in msg)
check("Ask-shape defined in the gaps prompt", "Ask:" in cw.SYSTEM_INSTRUCTIONS["gaps"])

gaps_without_ref = cw.ConsultingWorker("gaps", LINES, speaker=SPEAKER, context=CONTEXT)
msg = gaps_without_ref._build_user_message()
check("profile block present when no brief", "Speaker profile (JSON):" in msg)
check("context present in the fallback", "Speaker context:" in msg and "CTO in Jakarta" in msg)
check("no confirmed-brief block in the fallback", "Reference brief (confirmed):" not in msg)

print("\n[3] the roadmap prompt carries the brief + flagged gaps")
roadmap = cw.ConsultingWorker(
    "roadmap", LINES,
    reference="## Goals\n\n- Grow the team",
    gaps="**Undefined metric** — what does faster mean?\nAsk: \"faster how?\"",
    speaker=SPEAKER, context=CONTEXT)
msg = roadmap._build_user_message()
check("reference block present", "Reference brief (confirmed):" in msg and "- Grow the team" in msg)
check("flagged gaps block present", "Flagged gaps:" in msg and "Undefined metric" in msg)
check("roadmap prompt orders discovery before build",
      "discovery/validation" in cw.SYSTEM_INSTRUCTIONS["roadmap"].lower()
      or "BEFORE build" in cw.SYSTEM_INSTRUCTIONS["roadmap"])

print("\n[4] an empty transcript returns False and emits no_input for every mode")
for mode, call in (
        ("brief", lambda c: c.draft_brief([], {}, None)),
        ("gaps", lambda c: c.analyze_gaps([], "", {}, None)),
        ("roadmap", lambda c: c.generate_roadmap([], "", "", {}, None))):
    controller = ConsultingController()
    seen = []
    controller.status_changed.connect(lambda m, s: seen.append((m, s)))
    started = call(controller)
    check(f"{mode}: returns False", started is False)
    check(f"{mode}: no_input emitted", (mode, "no_input") in seen, str(seen))

print("\n[5] a brief run emits started -> updated(mode, text) -> complete")
fake = FakeClient(reply="## Goals\n\n- Grow the team")
cw.get_ai_client = lambda: fake
controller = ConsultingController()
events = []
controller.status_changed.connect(lambda m, s: events.append(("status", m, s)))
controller.updated.connect(lambda m, t: events.append(("updated", m, t)))
started = controller.draft_brief(LINES, SPEAKER, CONTEXT)
check("returns True", started is True)
check("'started' emitted synchronously",
      events and events[0] == ("status", "brief", "started"), str(events))
finished = wait_for(lambda: any(e[0] == "updated" for e in events))
check("finished", finished)
updated = [e for e in events if e[0] == "updated"]
check("updated carries (brief, text)", updated and updated[-1][1:] == ("brief", "## Goals\n\n- Grow the team"),
      str(updated))
statuses = [e[2] for e in events if e[0] == "status"]
check("'complete' emitted", "complete" in statuses, str(statuses))
check("exactly one AI call", len(fake.calls) == 1)
check("reasoning disabled", fake.calls[0]["disable_reasoning"] is True)
check("system prompt is the brief one", fake.calls[0]["system"] == cw.SYSTEM_INSTRUCTIONS["brief"])
check("idle after completion", controller.is_busy() is False)
check("internal brief field stored", controller._brief == "## Goals\n\n- Grow the team")

print("\n[6] the busy guard rejects a second call without a notice")
controller = ConsultingController()
seen = []
controller.status_changed.connect(lambda m, s: seen.append((m, s)))
controller._worker = FakeRunningWorker()
started = controller.analyze_gaps(LINES, "## Goals", SPEAKER, CONTEXT)
check("second call returns False", started is False)
check("no no_input notice while busy", ("gaps", "no_input") not in seen, str(seen))
controller._worker = None

print("\n[7] load_state seeds without broadcasting")
controller = ConsultingController()
seen = []
controller.updated.connect(lambda m, t: seen.append((m, t)))
controller.load_state("b", "g", "r")
check("brief seeded", controller._brief == "b")
check("gaps seeded", controller._gaps == "g")
check("roadmap seeded", controller._roadmap == "r")
check("nothing broadcast", seen == [], str(seen))

print("\n[8] reset() clears all three and emits '' for each mode")
controller = ConsultingController()
seen = []
controller.updated.connect(lambda m, t: seen.append((m, t)))
controller.load_state("b", "g", "r")
controller.reset()
check("emits '' for brief", ("brief", "") in seen, str(seen))
check("emits '' for gaps", ("gaps", "") in seen, str(seen))
check("emits '' for roadmap", ("roadmap", "") in seen, str(seen))
check("fields cleared", controller._brief == "" and controller._gaps == "" and controller._roadmap == "")

print("\n[9] a failed call emits error + status_changed(mode, 'error')")
fake = FakeClient(fail=True)
cw.get_ai_client = lambda: fake
controller = ConsultingController()
errors = []
statuses = []
controller.error_occurred.connect(errors.append)
controller.status_changed.connect(lambda m, s: statuses.append((m, s)))
controller.generate_roadmap(LINES, "## Goals", "gaps", SPEAKER, CONTEXT)
errored = wait_for(lambda: ("roadmap", "error") in statuses)
check("finished", errored)
check("error_occurred emitted", bool(errors), str(errors))
check("status 'error' emitted", ("roadmap", "error") in statuses, str(statuses))
check("no updated emitted", controller._roadmap == "")

print("\n[10] brief/gaps/roadmap/brief_meta round-trip and archive")
tmp_dir = tempfile.mkdtemp(prefix="consulting-session-")
store = SessionStore(directory=tmp_dir)
store.update("brief", "## Goals\n\n- Grow")
store.update("gaps", "- undefined metric")
store.update("roadmap", "1. Discovery")
store.update("brief_meta", {"confirmed": True, "confirmed_at": "T"})
store.flush()
with open(store.path, "r", encoding="utf-8") as f:
    current = json.load(f)
check("current.json has brief", current.get("brief") == "## Goals\n\n- Grow")
check("current.json has gaps", current.get("gaps") == "- undefined metric")
check("current.json has roadmap", current.get("roadmap") == "1. Discovery")
check("current.json has brief_meta.confirmed",
      (current.get("brief_meta") or {}).get("confirmed") is True)
archived_path = store.new_session()
check("New Session archived a file", bool(archived_path), str(archived_path))
with open(archived_path, "r", encoding="utf-8") as f:
    archived = json.load(f)
check("archived file keeps the brief", archived.get("brief") == "## Goals\n\n- Grow")
check("archived file keeps brief_meta",
      (archived.get("brief_meta") or {}).get("confirmed") is True)
with open(store.path, "r", encoding="utf-8") as f:
    fresh = json.load(f)
check("fresh current.json cleared brief", fresh.get("brief") == "")
check("fresh current.json cleared brief_meta", fresh.get("brief_meta") == {})
store.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
