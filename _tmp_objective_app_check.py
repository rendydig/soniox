"""Temp check: the Objectives tab's app-side wiring.

Builds a real `MainWindow` and drives the four control messages the pane sends
(`add_objective`, `remove_objective`, `set_objective_lock`,
`trigger_objective_prediction`), asserting the tracker's state is broadcast,
persisted, mirrored into the reply prompt and restored on the next launch. The
prediction worker is stubbed, so no network call is made and no QThread is left
running.

Side-effect containment matches `_tmp_bullet_manual_check.py`: `ui_state.json`,
the session store and the purpose store are redirected to a temp dir, and the Go
hub is disabled.

    venv/bin/python _tmp_objective_app_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

TMP_DIR = tempfile.mkdtemp(prefix="objective-app-check-")
import src.config as config  # noqa: E402

config.SESSION_DIR = TMP_DIR
config.PURPOSES_PATH = os.path.join(TMP_DIR, "purposes.json")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import src.screen_permission as screen_permission  # noqa: E402

screen_permission.has_permission = lambda: True
screen_permission.request_permission = lambda: None

import src.controllers.translation_controller as tc  # noqa: E402
import src.ui as ui  # noqa: E402

ui.has_permission = lambda: True
ui.request_permission = lambda: None

UI_STATE = os.path.join(TMP_DIR, "ui_state.json")
ui.load_state = lambda: json.load(open(UI_STATE)) if os.path.exists(UI_STATE) else {}
ui.save_state = lambda state: json.dump(state, open(UI_STATE, "w"), indent=2)

import src.session_store as ss  # noqa: E402

# The writer threads debounce at 2 s by default; at 20 ms the checks below can
# read back what they just persisted without racing a writer.
ss.SESSION_WRITE_DEBOUNCE_MS = 20

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class _FakeSignal:
    def connect(self, *args, **kwargs):
        pass


class _CaptureWorker:
    """Records the kwargs the controller builds the reply worker with."""

    captured = {}

    def __init__(self, *args, **kwargs):
        _CaptureWorker.captured = dict(kwargs)
        self.result = self.error = self.chunk = self.skipped = self.status = _FakeSignal()
        self.objective_observed = _FakeSignal()

    def start(self):
        pass

    def isRunning(self):
        return False


window = None
try:
    window = ui.MainWindow()
    controller = window.objective_controller
    sent = []
    window.websocket_client.send_message = sent.append
    window.websocket_client.send_transcription = lambda *args, **kwargs: None

    def objective_frames():
        return [m for m in sent if m.get("type") == "objectives"]

    def statuses():
        return [m for m in sent if m.get("type") == "objectives_status"]

    print("[1] adding an objective broadcasts, persists and mirrors it")
    sent.clear()
    window._handle_webview_message({"type": "add_objective", "text": "Ship the pilot"})
    check("the pane gets an objectives frame", len(objective_frames()) >= 1,
          str(len(objective_frames())))
    frame = objective_frames()[-1]
    check("the frame carries the list", frame.get("items") == ["Ship the pilot"], str(frame))
    check("the frame carries the locks", frame.get("locks") == [False], str(frame))
    check("the frame carries the resolved focus (empty for now)", frame.get("active") == {},
          str(frame.get("active")))
    check("it is persisted to the session",
          window.session_store.snapshot()["objectives"] == ["Ship the pilot"])
    check("the reply prompt is mirrored",
          window.translation_controller.get_objectives()[0] == ["Ship the pilot"])

    sent.clear()
    window._handle_webview_message({"type": "add_objective", "text": "Ship the pilot"})
    check("a duplicate add is refused with a notice",
          not objective_frames()
          and any(m.get("status") == "no_input" for m in statuses()), str(statuses()))

    print("\n[2] locking an objective pins the focus everywhere")
    sent.clear()
    window._handle_webview_message({"type": "set_objective_lock", "index": 0,
                                    "text": "Ship the pilot", "locked": True})
    frame = objective_frames()[-1]
    check("the lock is echoed to the pane", frame.get("locks") == [True], str(frame))
    check("the pinned objective becomes the focus",
          frame.get("active", {}).get("index") == 0
          and frame.get("active", {}).get("source") == "lock", str(frame.get("active")))
    check("the lock is persisted", window.session_store.snapshot()["objective_locks"] == [True])
    check("the tracker meta is persisted",
          window.session_store.snapshot()["objective_meta"].get("source") == "lock")
    check("the reply prompt sees the lock",
          window.translation_controller.get_objectives()[1] == [True]
          and window.translation_controller.get_objectives()[2].get("source") == "lock")
    check("the commit is appended to the history timeline",
          len(window.session_store.snapshot()["objective_history"]) == 1)
    check("the timeline entry is broadcast",
          any(m.get("type") == "objectives_history" for m in sent), str(sent))

    print("\n[3] removing an objective updates list, locks and session")
    window._handle_webview_message({"type": "add_objective", "text": "Agree on pricing"})
    sent.clear()
    window._handle_webview_message({"type": "remove_objective", "index": 0})
    frame = objective_frames()[-1]
    check("the item is gone from the pane frame",
          frame.get("items") == ["Agree on pricing"] and frame.get("locks") == [False],
          str(frame))
    check("the session no longer carries it",
          window.session_store.snapshot()["objectives"] == ["Agree on pricing"])

    print("\n[4] a prediction request routes to the tracker")
    empty = ui.ObjectiveController()
    empty_status = []
    empty.status_changed.connect(empty_status.append)
    check("predict_now with no objectives reports no_input",
          empty.predict_now() is False and empty_status == ["no_input"], str(empty_status))

    started = []
    real_worker = tc.GeminiAutoReplyWorker
    tc.GeminiAutoReplyWorker = _CaptureWorker
    try:
        called = []
        controller._start_worker = lambda: called.append(True)
        sent.clear()
        window._handle_webview_message({"type": "trigger_objective_prediction"})
        check("the pane's Predict now reaches the tracker", len(called) == 1, str(called))
        controller._start_worker = lambda: None
        # The mirrored objectives must reach the reply worker (voice replies only).
        controller.set_objectives(["Ship the pilot", "Agree on pricing"], [False, True])
        controller._meta = {"active": 0, "confidence": 0.4, "source": "llm"}
        window._mirror_objectives()
        window.translation_controller._start_auto_reply_worker("hello")
        captured = _CaptureWorker.captured
        check("the reply worker receives the objectives",
              captured.get("objectives") == ["Ship the pilot", "Agree on pricing"],
              str(captured.get("objectives")))
        check("the reply worker receives the locks and tracker state",
              captured.get("objective_locks") == [False, True]
              and captured.get("objective_meta", {}).get("active") == 0,
              str(captured.get("objective_locks")))
        window.translation_controller._auto_reply_worker = None
        window.translation_controller._start_auto_reply_worker("", images=["data:,"], is_image=True)
        check("an image reply carries no objective state",
              _CaptureWorker.captured.get("objectives") is None
              and _CaptureWorker.captured.get("objective_meta") is None,
              str(_CaptureWorker.captured.get("objectives")))
        window.translation_controller._auto_reply_worker = None
    finally:
        tc.GeminiAutoReplyWorker = real_worker

    print("\n[5] finalized lines feed the tracker")
    controller._lines = []
    controller._timer.stop()
    window._on_transcription_update("kita butuh dua kandidat", True, "speaker")
    check("a speaker final enters the rolling window",
          [line[0] for line in controller._lines] == ["speaker"], str(controller._lines))
    check("a speaker final arms the prediction debounce", controller._timer.isActive())
    controller._timer.stop()
    checks_before = len(controller._lines)
    window._on_transcription_update("oke siap", True, "host")
    check("a host final is buffered too",
          len(controller._lines) == checks_before + 1, str(controller._lines))
    check("a host final does not arm the debounce", not controller._timer.isActive())

    print("\n[6] session_state carries the objectives and their focus")
    sent.clear()
    window._send_session_state()
    state = [m for m in sent if m.get("type") == "session_state"][-1]
    check("the list rides the session state", state.get("objectives") == ["Ship the pilot",
                                                                          "Agree on pricing"])
    check("the locks ride the session state", state.get("objective_locks") == [False, True])
    check("the history rides the session state", isinstance(state.get("objective_history"), list))
    check("the resolved focus is precomputed for the pane",
          state.get("objective_active", {}).get("locked") is True,
          str(state.get("objective_active")))

    print("\n[7] restore and New Session")
    window.session_store.flush()
    controller.reset()
    check("reset clears the tracker", controller.get_objectives() == [] and controller.get_active() == {})
    check("reset also empties the persisted list / locks / meta",
          window.session_store.snapshot()["objectives"] == []
          and window.session_store.snapshot()["objective_locks"] == []
          and window.session_store.snapshot()["objective_meta"] == {})
    # The stored timeline is cleared by New Session (which archives it first) —
    # see the checks at the end of this section, not by a bare reset().
    # Seed a session by hand (what a reloaded launch finds on disk), then restore.
    window.session_store.set_objectives(["Ship the pilot", "Agree on pricing"])
    window.session_store.set_objective_locks([False, True])
    window.session_store.set_objective_meta({"active": 1, "confidence": 0.7, "source": "llm"})
    window.session_store.append("objective_history", {
        "ts": "2026-10-17T00:00:00Z", "index": 1, "text": "Agree on pricing",
        "confidence": 0.7, "source": "llm",
    })
    _seeded = []
    controller.objectives_changed.connect(lambda items, locks: _seeded.append(1))
    window._restore_session()
    check("seeding does not broadcast a list change", _seeded == [], str(len(_seeded)))
    check("_restore_session seeds the objectives back",
          controller.get_objectives() == ["Ship the pilot", "Agree on pricing"])
    check("it seeds the locks", controller.get_locks() == [False, True])
    check("it seeds the history", len(controller.get_history()) >= 1)
    check("it re-mirrors the reply prompt",
          window.translation_controller.get_objectives()[0] == ["Ship the pilot",
                                                                "Agree on pricing"])

    archived_id = window.session_store.snapshot()["id"]
    ui.QMessageBox.exec = lambda self: ui.QMessageBox.StandardButton.Yes
    window._new_session()
    check("New Session clears the tracker", controller.get_objectives() == []
          and controller.get_history() == [] and controller.get_active() == {})
    check("New Session clears the session fields",
          window.session_store.snapshot()["objectives"] == []
          and window.session_store.snapshot()["objective_history"] == [])
    archived_path = os.path.join(TMP_DIR, f"{archived_id}.json")
    check("the previous session is archived", os.path.exists(archived_path),
          archived_path)
    if os.path.exists(archived_path):
        with open(archived_path, encoding="utf-8") as f:
            data = json.load(f)
        check("the archived session keeps the objectives",
              data["objectives"] == ["Ship the pilot", "Agree on pricing"]
              and len(data["objective_history"]) >= 1)

    print("\n[8] the reply worker's JEV observation reaches the tracker")
    controller.set_objectives(["Ship the pilot", "Agree on pricing"])
    controller._meta = {}
    sent.clear()
    window._on_objective_observed(1, 0.9, "jev")
    window._on_objective_observed(1, 0.9, "jev")
    check("two agreeing JEV observations commit the focus",
          controller.get_active().get("index") == 1, str(controller.get_active()))
    check("the commit is broadcast and persisted",
          any(m.get("type") == "objectives_history" for m in sent)
          and len(window.session_store.snapshot()["objective_history"]) >= 1)
    empty_tracker = ui.ObjectiveController()
    window._on_objective_observed(0, 0.9, "jev")
    check("with no objectives an observation is ignored (no crash)",
          empty_tracker.get_objectives() == [])

    print("\nthe tracker cleans up")
    controller.cleanup()
    check("cleanup leaves no worker behind", controller._worker is None)
finally:
    if window is not None:
        try:
            window.objective_controller.cleanup()
        except Exception:
            pass

print()
print("ALL PASS" if not failures else f"FAILURES: {failures}")
sys.exit(1 if failures else 0)
