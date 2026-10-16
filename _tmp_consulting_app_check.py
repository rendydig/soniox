"""Temp check: the Consulting tab's app-side wiring in a real `MainWindow`.

Drives the webview control messages the pane sends (`draft_brief`,
`analyze_gaps`, `generate_roadmap`, `confirm_brief`, `consulting_save`) and
asserts the right inputs reach the controller, that the reference is the
confirmed brief when present and empty (profile fallback) when not, that an empty
transcript shows a `no_input` notice, that `confirm_brief` sets
`brief_meta.confirmed`, that `consulting_save` persists + echoes, that restore
seeds the controller, and that New Session clears + archives. The AI worker start
is stubbed, so no network call is made and no QThread is left running.

Side-effect containment matches `_tmp_summary_app_check.py`: `ui_state.json`, the
session store and the purpose store are redirected to a temp dir, and the Go hub
is disabled.

    venv/bin/python _tmp_consulting_app_check.py

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

TMP_DIR = tempfile.mkdtemp(prefix="consulting-app-check-")
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
    controller = window.consulting_controller
    sent = []
    window.websocket_client.send_message = sent.append

    def consulting_frames():
        return [m for m in sent if m.get("type") == "consulting"]

    def statuses():
        return [m for m in sent if m.get("type") == "consulting_status"]

    captured = {}
    controller._start_worker = lambda mode, lines, reference, gaps, speaker, context: captured.update(
        mode=mode, lines=list(lines), reference=reference, gaps=gaps,
        speaker=dict(speaker), context=context)

    print("[1] draft_brief maps the transcript + speaker + mirrored context")
    sent.clear()
    captured.clear()
    window.session_store.update("transcriptions", [
        {"source": "speaker", "text": "Kami butuh kandidat", "timestamp": "T1"},
        {"source": "host", "text": "", "timestamp": "T2"},
        {"source": "host", "text": "Oke siap", "timestamp": "T3"},
    ])
    window.session_store.set_speaker({"name": "Budi"})
    window.translation_controller.set_context({"host": "H notes", "speaker": "S notes"})
    window._handle_webview_message({"type": "draft_brief"})
    check("mode is brief", captured.get("mode") == "brief", str(captured.get("mode")))
    check("only non-empty lines mapped (source, text, timestamp)",
          captured.get("lines") == [("speaker", "Kami butuh kandidat", "T1"),
                                    ("host", "Oke siap", "T3")], str(captured.get("lines")))
    check("speaker profile passed", captured.get("speaker") == {"name": "Budi"}, str(captured))
    check("mirrored context passed",
          captured.get("context") == {"host": "H notes", "speaker": "S notes"},
          str(captured.get("context")))

    print("\n[2] analyze_gaps uses the confirmed brief, else the profile fallback")
    sent.clear()
    captured.clear()
    window.session_store.update("brief", "## Goals\n\n- Grow the team")
    window.session_store.update("brief_meta", {"confirmed": True, "confirmed_at": "T"})
    window._handle_webview_message({"type": "analyze_gaps"})
    check("reference is the confirmed brief",
          captured.get("reference") == "## Goals\n\n- Grow the team", str(captured.get("reference")))
    check("mode is gaps", captured.get("mode") == "gaps")
    captured.clear()
    window.session_store.update("brief_meta", {"confirmed": False})
    window._handle_webview_message({"type": "analyze_gaps"})
    check("reference is empty when the brief is unconfirmed",
          captured.get("reference") == "", str(captured.get("reference")))

    print("\n[3] generate_roadmap passes the reference + flagged gaps")
    sent.clear()
    captured.clear()
    window.session_store.update("brief_meta", {"confirmed": True, "confirmed_at": "T"})
    window.session_store.update("gaps", "**Undefined metric** — faster?")
    window._handle_webview_message({"type": "generate_roadmap"})
    check("mode is roadmap", captured.get("mode") == "roadmap")
    check("reference passed",
          captured.get("reference") == "## Goals\n\n- Grow the team", str(captured.get("reference")))
    check("gaps passed",
          captured.get("gaps") == "**Undefined metric** — faster?", str(captured.get("gaps")))

    print("\n[4] an empty transcript shows a no_input notice for each mode")
    window.session_store.update("transcriptions", [])
    for msg_type, mode in (("draft_brief", "brief"), ("analyze_gaps", "gaps"),
                           ("generate_roadmap", "roadmap")):
        sent.clear()
        window._handle_webview_message({"type": msg_type})
        check(f"{mode}: no_input sent",
              any(s.get("mode") == mode and s.get("status") == "no_input" for s in statuses()),
              str(statuses()))

    print("\n[5] _on_consulting_updated broadcasts and persists (brief clears confirm)")
    sent.clear()
    window.session_store.update("brief_meta", {"confirmed": True, "confirmed_at": "T"})
    window._on_consulting_updated("brief", "## Goals\n\n- Edited")
    check("consulting frame sent",
          consulting_frames() and consulting_frames()[-1].get("mode") == "brief"
          and consulting_frames()[-1].get("text") == "## Goals\n\n- Edited",
          str(consulting_frames()))
    check("brief persisted",
          window.session_store.snapshot().get("brief") == "## Goals\n\n- Edited")
    check("editing a brief clears confirmed",
          (window.session_store.snapshot().get("brief_meta") or {}).get("confirmed") is not True)
    check("frame reports confirmed False",
          consulting_frames()[-1].get("confirmed") is False)

    print("\n[6] confirm_brief sets brief_meta.confirmed and echoes it")
    sent.clear()
    window.session_store.update("brief", "## Goals\n\n- Lock this in")
    window._handle_webview_message({"type": "confirm_brief"})
    meta = window.session_store.snapshot().get("brief_meta") or {}
    check("brief_meta.confirmed is True", meta.get("confirmed") is True, str(meta))
    check("confirmed_at stamped", bool(meta.get("confirmed_at")), str(meta))
    check("echoed with confirmed True",
          consulting_frames() and consulting_frames()[-1].get("confirmed") is True
          and consulting_frames()[-1].get("text") == "## Goals\n\n- Lock this in",
          str(consulting_frames()))

    print("\n[7] consulting_save persists and echoes the edit")
    sent.clear()
    window._handle_webview_message({"type": "consulting_save", "mode": "gaps", "text": "gap edit"})
    check("gaps persisted", window.session_store.snapshot().get("gaps") == "gap edit")
    check("echoed as a consulting frame",
          consulting_frames() and consulting_frames()[-1].get("mode") == "gaps"
          and consulting_frames()[-1].get("text") == "gap edit", str(consulting_frames()))

    print("\n[8] restore seeds the controller from the session snapshot")
    window.session_store.update("brief", "restored brief")
    window.session_store.update("gaps", "restored gaps")
    window.session_store.update("roadmap", "restored roadmap")
    controller.load_state("", "", "")
    window._restore_session()
    check("brief seeded", controller._brief == "restored brief", repr(controller._brief))
    check("gaps seeded", controller._gaps == "restored gaps", repr(controller._gaps))
    check("roadmap seeded", controller._roadmap == "restored roadmap", repr(controller._roadmap))

    print("\n[9] New Session clears the tab and archives the previous texts")
    sent.clear()
    window.session_store.update("brief", "to be archived")
    ui.QMessageBox.exec = lambda self: ui.QMessageBox.StandardButton.Yes
    window._new_session()
    fresh = window.session_store.snapshot()
    check("controller reset", controller._brief == "" and controller._gaps == "" and controller._roadmap == "",
          repr((controller._brief, controller._gaps, controller._roadmap)))
    check("fresh session brief empty", fresh.get("brief") == "")
    check("fresh session gaps empty", fresh.get("gaps") == "")
    check("fresh session roadmap empty", fresh.get("roadmap") == "")
    check("fresh session brief unconfirmed",
          (fresh.get("brief_meta") or {}).get("confirmed") is not True)
    archived = sorted(glob.glob(os.path.join(TMP_DIR, "*.json")))
    archived = [p for p in archived if os.path.basename(p) != "current.json"]
    found = any(json.load(open(p, encoding="utf-8")).get("brief") == "to be archived"
                for p in archived)
    check("archived file keeps the brief", found, str([os.path.basename(p) for p in archived]))
finally:
    if window is not None:
        window.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
