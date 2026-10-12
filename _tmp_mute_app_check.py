"""Temp check: the control bar's Mute Microphone button (app-side wiring).

Builds a real `MainWindow` and asserts the button sits in the control row, starts
unchecked (the app always launches unmuted), toggles the controller state and the
icon/tooltip/status label, and is never written to `ui_state.json`.

Side-effect containment matches `_tmp_context_app_check.py`: `ui_state.json`, the
session store and the purpose store are redirected to a temp dir, and the Go hub
is disabled.

    venv/bin/python _tmp_mute_app_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

TMP_DIR = tempfile.mkdtemp(prefix="mute-app-check-")
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
    button = window.mic_button

    print("[1] the button is in the control row and starts unmuted")
    check("MainWindow exposes the mic button", button is window.control_buttons.get_mic_button())
    check("checkable", button.isCheckable())
    check("unchecked at launch", not button.isChecked())
    check("controller starts unmuted", window.transcription_controller._mic_muted is False)
    check("fixed width 30", button.width() == 30 or button.minimumWidth() == 30
          or button.maximumWidth() == 30, str((button.minimumWidth(), button.maximumWidth())))
    check("initial tooltip names mute", "Mute the microphone" in button.toolTip(), button.toolTip())

    live_icon = button.icon().pixmap(18, 18).toImage()

    print("\n[2] toggling mutes the controller, the icon, the tooltip and the status")
    button.setChecked(True)
    check("controller state set", window.transcription_controller._mic_muted is True)
    check("tooltip flips", button.toolTip() == "Unmute the microphone", button.toolTip())
    check("status label shows the mute", window.status_label.text() == "Microphone muted",
          window.status_label.text())
    check("icon changed", button.icon().pixmap(18, 18).toImage() != live_icon)

    button.setChecked(False)
    check("controller state cleared", window.transcription_controller._mic_muted is False)
    check("tooltip restored", "Mute the microphone" in button.toolTip(), button.toolTip())
    check("status label back to listening", window.status_label.text() == "Listening...",
          window.status_label.text())
    check("icon restored", button.icon().pixmap(18, 18).toImage() == live_icon)

    print("\n[3] the state is not persisted")
    window._save_state()
    with open(UI_STATE, "r", encoding="utf-8") as handle:
        saved = json.load(handle)
    blob = json.dumps(saved)
    check("no mic/mute key anywhere in ui_state.json",
          "mic" not in blob.lower() and "mute" not in blob.lower(), blob[:160])
    check("settings block has no mute flag",
          not any("mute" in k.lower() for k in (saved.get("settings") or {})),
          str(list((saved.get("settings") or {}).keys())))
finally:
    if window is not None:
        window.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
