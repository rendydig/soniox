"""Temp check: the Summary tab's app-side wiring in a real `MainWindow`.

Drives the webview control message the pane's Summarize button sends
(`{"type": "summarize"}`) and asserts the transcript/bullet/speaker inputs reach
the controller, that an empty transcript shows the "Nothing to summarize yet"
notice instead of starting a call, that the finished text is broadcast AND
persisted to the session, that restore seeds the tab, and that New Session clears
it (archiving the previous summary). The AI worker start is stubbed, so no
network call is made and no QThread is left running.

Side-effect containment matches `_tmp_bullet_manual_check.py`: `ui_state.json`,
the session store and the purpose store are redirected to a temp dir, and the Go
hub is disabled.

    venv/bin/python _tmp_summary_app_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import glob
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

TMP_DIR = tempfile.mkdtemp(prefix="summary-app-check-")
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
    controller = window.summarize_controller
    sent = []
    window.websocket_client.send_message = sent.append

    def summaries():
        return [m for m in sent if m.get("type") == "summary"]

    def statuses():
        return [m for m in sent if m.get("type") == "summary_status"]

    print("[1] _on_summary_updated broadcasts and persists the text")
    sent.clear()
    window._on_summary_updated("## Overview\n\nAll good.")
    check("summary frame sent",
          summaries() and summaries()[0].get("text") == "## Overview\n\nAll good.", str(summaries()))
    check("persisted to the session",
          window.session_store.snapshot().get("summary") == "## Overview\n\nAll good.")

    print("\n[2] an empty transcript shows a notice, not a dead button")
    sent.clear()
    window.session_store.update("transcriptions", [])
    window._handle_webview_message({"type": "summarize"})
    check("no_input status sent", any(s.get("status") == "no_input" for s in statuses()),
          str(statuses()))
    check("notice carries the message",
          any(s.get("status") == "no_input" and s.get("message") == "Nothing to summarize yet"
              for s in statuses()), str(statuses()))

    print("\n[3] a populated session feeds the transcript/bullets/speaker to the worker")
    sent.clear()
    captured = {}
    controller._start_worker = lambda lines, bullets, speaker: captured.update(
        lines=list(lines), bullets=list(bullets), speaker=dict(speaker))
    window.session_store.update("transcriptions", [
        {"source": "speaker", "text": "Kami butuh kandidat", "timestamp": "T1"},
        {"source": "host", "text": "", "timestamp": "T2"},
        {"source": "host", "text": "Oke siap", "timestamp": "T3"},
    ])
    window.session_store.set_bullets(["existing point"])
    window.session_store.set_speaker({"name": "Budi"})
    window._handle_webview_message({"type": "summarize"})
    check("only non-empty lines mapped (source, text, timestamp)",
          captured.get("lines") == [("speaker", "Kami butuh kandidat", "T1"),
                                    ("host", "Oke siap", "T3")], str(captured.get("lines")))
    check("bullet list passed", captured.get("bullets") == ["existing point"], str(captured))
    check("speaker profile passed", captured.get("speaker") == {"name": "Budi"}, str(captured))

    print("\n[4] restore seeds the tab from the session snapshot")
    window.session_store.update("summary", "restored summary text")
    controller.load_summary("")
    window._restore_session()
    check("controller seeded", controller._summary == "restored summary text",
          repr(controller._summary))

    print("\n[5] New Session clears the tab and archives the previous summary")
    sent.clear()
    window.session_store.update("summary", "to be archived")
    ui.QMessageBox.exec = lambda self: ui.QMessageBox.StandardButton.Yes
    window._new_session()
    check("controller reset", controller._summary == "", repr(controller._summary))
    check("fresh session summary empty",
          window.session_store.snapshot().get("summary") == "")
    archived = sorted(glob.glob(os.path.join(TMP_DIR, "*.json")))
    archived = [p for p in archived if os.path.basename(p) != "current.json"]
    found = any(json.load(open(p, encoding="utf-8")).get("summary") == "to be archived"
                for p in archived)
    check("archived file keeps the summary", found, str([os.path.basename(p) for p in archived]))

    print("\n[6] a manual edit (summary_save) persists and is echoed back")
    sent.clear()
    window._handle_webview_message({"type": "summary_save", "text": "## Overview\n\nEdited by hand."})
    check("persisted to the session",
          window.session_store.snapshot().get("summary") == "## Overview\n\nEdited by hand.")
    check("echoed as a summary frame",
          summaries() and summaries()[-1].get("text") == "## Overview\n\nEdited by hand.",
          str(summaries()))
finally:
    if window is not None:
        window.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
