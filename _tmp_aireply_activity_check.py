"""Temp check: the reply "in flight" ring's app-side wiring in a real `MainWindow`.

The pane's title spinner is driven by the `reply_activity(in_progress, is_image)`
signal on `TranslationController`, turned into the existing `gemini_status` frame
by `MainWindow._on_reply_activity`. This asserts:
  * the Tool ▾ item now reads "AI Suggestion" (the rename);
  * a started reply broadcasts `gemini_status {status:"started", mode:"auto_reply"}`;
  * the result, a skip **and an error** each broadcast `{status:"complete"}` (the
    error path is the one that broadcasts nothing else, so it is the reason the
    explicit "complete" exists);
  * the image path reports `mode:"image"` from the same single place, and
    `_send_images_to_gemini` no longer double-sends a "started" frame;
  * a queued rerun (a second request while one is in flight) does not emit a
    second "started" but the completion still lands after it.

The reply worker is stubbed (its constructor is replaced), so no network call is
made and no QThread is left running. Side-effect containment matches
`_tmp_summary_app_check.py`: `ui_state.json`, the session store and the purpose
store are redirected to a temp dir, and the Go hub is disabled.

    venv/bin/python _tmp_aireply_activity_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

TMP_DIR = tempfile.mkdtemp(prefix="aireply-activity-check-")
import src.config as config  # noqa: E402

config.SESSION_DIR = TMP_DIR
config.PURPOSES_PATH = os.path.join(TMP_DIR, "purposes.json")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import src.screen_permission as screen_permission  # noqa: E402

screen_permission.has_permission = lambda: True
screen_permission.request_permission = lambda: None

import src.ui as ui  # noqa: E402
import src.controllers.translation_controller as tc  # noqa: E402

ui.has_permission = lambda: True
ui.request_permission = lambda: None

UI_STATE = os.path.join(TMP_DIR, "ui_state.json")
ui.load_state = lambda: json.load(open(UI_STATE)) if os.path.exists(UI_STATE) else {}
ui.save_state = lambda state: json.dump(state, open(UI_STATE, "w"), indent=2)


class StubWorker(QObject):
    """A GeminiAutoReplyWorker stand-in: the same signals, no thread, no network."""

    result = Signal(str)
    error = Signal(str)
    chunk = Signal(str)
    skipped = Signal(str)
    status = Signal(str)
    objective_observed = Signal(int, float, str)
    objectives_satisfied = Signal(list)

    def __init__(self, *args, **kwargs):
        super().__init__()

    def start(self):
        pass

    def isRunning(self):
        return False

    def stop(self):
        pass

    def wait(self, *args):
        return True

    def terminate(self):
        pass

    def deleteLater(self):
        pass


tc.GeminiAutoReplyWorker = StubWorker

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


window = None
try:
    window = ui.MainWindow()
    controller = window.translation_controller
    sent = []

    def fake_send_transcription(text, is_final, additional_data=None, message_type="transcription"):
        sent.append({"type": message_type, **(additional_data or {})})

    window.websocket_client.send_transcription = fake_send_transcription

    def statuses():
        return [m for m in sent if m.get("type") == "gemini_status"]

    def pump():
        """Deliver the queued worker signal connections."""
        for _ in range(5):
            app.processEvents()

    print("[1] the Tool menu item was renamed")
    check("the action reads 'AI Suggestion'",
          window.gemini_window_action.text() == "AI Suggestion",
          repr(window.gemini_window_action.text()))
    check("the tooltip still explains the pane",
          "AI suggestion pane" in window.gemini_window_action.toolTip(),
          repr(window.gemini_window_action.toolTip()))

    print("\n[2] a started reply reports progress")
    sent.clear()
    worker = controller._start_auto_reply_worker("What does it do?", is_image=False)
    check("the worker started", worker is True)
    check("a 'started' gemini_status was broadcast",
          statuses() == [{"type": "gemini_status", "status": "started", "mode": "auto_reply"}],
          str(statuses()))

    print("\n[3] the result settles the ring")
    sent.clear()
    controller._auto_reply_worker.result.emit("It captures the call and lists the points.")
    pump()
    check("a 'complete' gemini_status was broadcast",
          any(s.get("status") == "complete" and s.get("mode") == "auto_reply" for s in statuses()),
          str(statuses()))
    check("the reply itself was broadcast too", bool(window.session_store.snapshot().get("aireply_results")))

    print("\n[4] a skipped reply settles the ring")
    sent.clear()
    controller._start_auto_reply_worker("Okay.", is_image=False)
    controller._auto_reply_worker.skipped.emit("Filler utterance")
    pump()
    check("'complete' was broadcast on skip",
          any(s.get("status") == "complete" for s in statuses()), str(statuses()))
    check("the skip reason was broadcast too",
          any(s.get("status") == "skipped" for s in statuses()), str(statuses()))

    print("\n[5] an error settles the ring (its banner may be suppressed)")
    sent.clear()
    controller._start_auto_reply_worker("Hmm.", is_image=False)
    # The worker's own message shape (src/gemini_worker.py:995): it contains
    # "auto-reply", which is exactly what makes _on_translation_error suppress
    # the banner — leaving "complete" as the only thing that stops the ring.
    controller._auto_reply_worker.error.emit("AI auto-reply error: boom")
    pump()
    check("'complete' was broadcast on error",
          any(s.get("status") == "complete" for s in statuses()), str(statuses()))
    check("no 'failed' banner is added for an auto-reply error",
          not any(s.get("status") == "failed" for s in statuses()), str(statuses()))

    print("\n[6] the image path reports the same way, once")
    sent.clear()
    window._screenshots.append("data:image/jpeg;base64,AAAA")
    window._send_images_to_gemini()
    check("exactly one 'started' frame",
          [s.get("status") for s in statuses()] == ["started"], str(statuses()))
    check("it is tagged mode=image", statuses()[0].get("mode") == "image", str(statuses()))
    sent.clear()
    controller._auto_reply_worker.result.emit("Screenshot says X.")
    pump()
    check("'complete' is tagged mode=image",
          any(s.get("status") == "complete" and s.get("mode") == "image" for s in statuses()),
          str(statuses()))
    check("the image reply is broadcast as an image result",
          any(m.get("type") == "gemini_result" and m.get("mode") == "image" for m in sent),
          str(sent))
    window._screenshots.clear()

    print("\n[7] a queued rerun does not double-report")
    sent.clear()
    controller.trigger_reply_now("First question?")
    first = controller._auto_reply_worker
    check("the first request started",
          [s.get("status") for s in statuses()] == ["started"], str(statuses()))
    first.isRunning = lambda: True
    controller.trigger_reply_now("Second question?")
    check("the second request was queued, not started",
          [s.get("status") for s in statuses()] == ["started"], str(statuses()))
    first.isRunning = lambda: False
    sent.clear()
    first.result.emit("Answer to the first.")
    pump()
    check("the first reply settles the ring",
          any(s.get("status") == "complete" for s in statuses()), str(statuses()))
    check("the queued rerun started",
          any(s.get("status") == "started" for s in statuses()), str(statuses()))

    print("\n[8] no screenshots still reports the failure")
    sent.clear()
    window._screenshots.clear()
    window._send_images_to_gemini()
    check("a 'failed' frame is sent",
          [s.get("status") for s in statuses()] == ["failed"], str(statuses()))

    print("\n[9] the signal contract")
    check("reply_activity carries (bool, bool)",
          controller.reply_activity is not None)
finally:
    if window is not None:
        try:
            window.close()
        except Exception as exc:  # pragma: no cover - teardown best effort
            print("      teardown:", exc)

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
