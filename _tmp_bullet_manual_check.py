"""Temp check: the Bullet Points "Fetch new" button (incremental manual catch-up).

Builds a real `MainWindow` and drives the webview control message the pane's
button sends (`{"type": "trigger_bullet_points"}`), asserting it starts an
*incremental* update (never a rebuild), that the buffered window and the existing
list are what reach the worker, and that an empty buffer yields a feedback notice
instead of a silent no-op. The AI worker start is stubbed, so no network call is
made and no QThread is left running.

Side-effect containment matches `_tmp_context_app_check.py`: `ui_state.json`, the
session store and the purpose store are redirected to a temp dir, and the Go hub
is disabled.

    venv/bin/python _tmp_bullet_manual_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

TMP_DIR = tempfile.mkdtemp(prefix="bullet-manual-check-")
import src.config as config  # noqa: E402

config.SESSION_DIR = TMP_DIR
config.PURPOSES_PATH = os.path.join(TMP_DIR, "purposes.json")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import src.screen_permission as screen_permission  # noqa: E402

screen_permission.has_permission = lambda: True
screen_permission.request_permission = lambda: None

import src.ui as ui  # noqa: E402

ui.has_permission = lambda: True
ui.request_permission = lambda: None

UI_STATE = os.path.join(TMP_DIR, "ui_state.json")
ui.load_state = lambda: json.load(open(UI_STATE)) if os.path.exists(UI_STATE) else {}
ui.save_state = lambda state: json.dump(state, open(UI_STATE, "w"), indent=2)

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


window = None
try:
    window = ui.MainWindow()
    controller = window.bullet_points_controller

    sent = []
    window.websocket_client.send_message = sent.append

    calls = []

    def fake_start_worker(current_bullets, current_speaker, lines, rebuild=False):
        calls.append({"bullets": list(current_bullets), "lines": list(lines), "rebuild": rebuild})
        # Mirror the real method's progress broadcast (the worker itself is not run).
        controller.status_changed.emit("started")

    controller._start_worker = fake_start_worker

    def bullet_statuses():
        return [m for m in sent if m.get("type") == "bullet_points_status"]

    print("[1] an empty buffer yields a feedback notice, not a silent no-op")
    sent.clear()
    calls.clear()
    controller._buffer = []
    window._handle_webview_message({"type": "trigger_bullet_points"})
    check("no worker was started", calls == [], str(calls))
    check("a no_new status was sent", any(m.get("status") == "no_new" for m in bullet_statuses()),
          str(bullet_statuses()))
    check("the notice carries a message",
          any(m.get("status") == "no_new" and m.get("message") == "Nothing new yet"
              for m in bullet_statuses()), str(bullet_statuses()))

    print("\n[2] buffered lines -> an incremental update, never a rebuild")
    sent.clear()
    calls.clear()
    controller.add_line("speaker", "kita butuh dua kandidat")
    controller.add_line("host", "oke siap")
    controller._bullets = ["existing point"]
    window._handle_webview_message({"type": "trigger_bullet_points"})
    check("exactly one worker was started", len(calls) == 1, str(calls))
    check("the update is incremental (rebuild=False)", calls and calls[0]["rebuild"] is False)
    check("the whole buffered window was sent", calls and len(calls[0]["lines"]) == 2, str(calls))
    check("the existing list reaches the prompt", calls and calls[0]["bullets"] == ["existing point"],
          str(calls))
    check("a 'started' status was broadcast",
          any(m.get("status") == "started" for m in bullet_statuses()), str(bullet_statuses()))
    check("no spurious no_new notice",
          not any(m.get("status") == "no_new" for m in bullet_statuses()), str(bullet_statuses()))

    print("\n[3] _send_bullet_status forwards an optional message")
    sent.clear()
    window._send_bullet_status("saved", message="Hello")
    check("message included", bullet_statuses() and bullet_statuses()[0].get("message") == "Hello",
          str(bullet_statuses()))
    sent.clear()
    window._send_bullet_status("complete")
    check("no message key when empty",
          bullet_statuses() and "message" not in bullet_statuses()[0], str(bullet_statuses()))

    print("\n[4] Rebuild still routes to a rebuild (unchanged)")
    sent.clear()
    calls.clear()
    window.session_store.update("transcriptions", [
        {"source": "speaker", "text": "hello", "timestamp": "2026-10-12T10:00:00.0"},
        {"source": "host", "text": "hi", "timestamp": "2026-10-12T10:00:05.0"},
    ])
    window._handle_webview_message({"type": "regenerate_bullet_points"})
    check("a rebuild worker was started", calls and calls[0]["rebuild"] is True, str(calls))
    check("a rebuild starts from an empty list", calls and calls[0]["bullets"] == [], str(calls))
    check("a rebuild passes the transcript lines", calls and len(calls[0]["lines"]) == 2, str(calls))

    print("\n[5] is_busy reflects the worker state")
    check("idle with the stubbed start", controller.is_busy() is False)
finally:
    if window is not None:
        window.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
