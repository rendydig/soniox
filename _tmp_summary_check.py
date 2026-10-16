"""Temp check: the Bullet Points "Summary" tab (one-shot whole-session summary).

Exercises ``SummarizeWorker`` (prompt shape + AI call) and
``SummarizeController`` (trigger contract, status flow, seed/reset, error path)
with the AI client stubbed — no network call, no real API. Also asserts the
``summary`` session field is written to ``current.json`` and carried into the
archived session file on New Session.

    venv/bin/python _tmp_summary_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import os
import sys
import tempfile
import time

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

import src.summarize_worker as sw  # noqa: E402
from src.controllers.summarize_controller import SummarizeController  # noqa: E402
from src.config import SUMMARY_MAX_LINE_CHARS  # noqa: E402
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

    def __init__(self, reply="## Overview\n\nAll good.", fail=False):
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


print("[1] _build_user_message carries the transcript, bullets JSON and speaker JSON")
long_line = "x" * (SUMMARY_MAX_LINE_CHARS + 50)
worker = sw.SummarizeWorker(
    [("host", "Hello there"), ("speaker", "Kami butuh dua kandidat"), ("host", long_line)],
    ["point one", "point two"],
    {"name": "Budi", "goals": ["Grow the team"]},
)
message = worker._build_user_message()
check("[host] line rendered", "[host] Hello there" in message)
check("[speaker] line rendered", "[speaker] Kami butuh dua kandidat" in message)
check("bullets JSON present",
      json.dumps(["point one", "point two"], ensure_ascii=False) in message)
check("speaker JSON present",
      json.dumps({"name": "Budi", "goals": ["Grow the team"]}, ensure_ascii=False) in message)
check("long line truncated to SUMMARY_MAX_LINE_CHARS",
      ("x" * SUMMARY_MAX_LINE_CHARS) in message and ("x" * (SUMMARY_MAX_LINE_CHARS + 1)) not in message)
check("labelled blocks present",
      "Conversation transcript:" in message and "Bullet points (JSON):" in message
      and "Speaker profile (JSON):" in message)
check("system prompt defines the fixed sections",
      all(section in sw.SYSTEM_INSTRUCTION for section in (
          "## Overview", "## Key Points", "## Decisions", "## Open Questions",
          "## Next Steps", "## Speaker Highlights")))

print("\n[2] trigger_now([]) returns False and emits no_input")
controller = SummarizeController()
statuses = []
controller.status_changed.connect(statuses.append)
started = controller.trigger_now([], [], {})
check("returns False", started is False)
check("no_input emitted", "no_input" in statuses, str(statuses))

print("\n[3] a normal run emits started -> updated and calls the AI once")
fake = FakeClient(reply="## Overview\n\nEverything is fine.")
sw.get_ai_client = lambda: fake
controller = SummarizeController()
events = []
controller.status_changed.connect(lambda s: events.append(("status", s)))
controller.updated.connect(lambda t: events.append(("updated", t)))
started = controller.trigger_now([("host", "hi")], ["a point"], {"name": "Budi"})
check("returns True", started is True)
check("'started' emitted synchronously", events and events[0] == ("status", "started"), str(events))
finished = wait_for(lambda: any(e[0] == "updated" for e in events))
check("finished", finished)
status_list = [v for tag, v in events if tag == "status"]
check("'complete' emitted", "complete" in status_list, str(status_list))
updated = [v for tag, v in events if tag == "updated"]
check("updated carries the AI reply", updated and updated[-1] == "## Overview\n\nEverything is fine.",
      str(updated))
check("exactly one AI call", len(fake.calls) == 1)
check("reasoning disabled", fake.calls[0]["disable_reasoning"] is True)
check("system prompt is the summarize one", fake.calls[0]["system"] == sw.SYSTEM_INSTRUCTION)
check("idle after completion", controller.is_busy() is False)

print("\n[4] load_summary seeds without broadcasting")
controller = SummarizeController()
seen = []
controller.updated.connect(seen.append)
controller.load_summary("previously saved summary")
check("_summary seeded", controller._summary == "previously saved summary")
check("nothing broadcast", seen == [], str(seen))

print("\n[5] reset() clears and emits ''")
controller = SummarizeController()
seen = []
controller.updated.connect(seen.append)
controller.load_summary("old")
controller.reset()
check("emits empty string", seen == [""], str(seen))
check("_summary cleared", controller._summary == "")

print("\n[6] a failed call emits error + status_changed('error')")
fake = FakeClient(fail=True)
sw.get_ai_client = lambda: fake
controller = SummarizeController()
errors = []
statuses = []
controller.error_occurred.connect(errors.append)
controller.status_changed.connect(statuses.append)
controller.trigger_now([("host", "hi")], [], {})
errored = wait_for(lambda: "error" in statuses)
check("finished", errored)
check("error_occurred emitted", bool(errors), str(errors))
check("status 'error' emitted", "error" in statuses, str(statuses))
check("no updated emitted", controller._summary == "")

print("\n[7] the summary is persisted to current.json and archived on New Session")
tmp_dir = tempfile.mkdtemp(prefix="summary-session-")
store = SessionStore(directory=tmp_dir)
store.update("summary", "Hello summary")
store.flush()
with open(store.path, "r", encoding="utf-8") as f:
    current = json.load(f)
check("current.json has the summary field", current.get("summary") == "Hello summary",
      repr(current.get("summary")))
archived_path = store.new_session()
check("New Session archived a file", bool(archived_path), str(archived_path))
with open(archived_path, "r", encoding="utf-8") as f:
    archived = json.load(f)
check("archived file keeps the summary", archived.get("summary") == "Hello summary",
      repr(archived.get("summary")))
with open(store.path, "r", encoding="utf-8") as f:
    fresh = json.load(f)
check("fresh current.json cleared the summary", fresh.get("summary") == "", repr(fresh.get("summary")))
store.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
