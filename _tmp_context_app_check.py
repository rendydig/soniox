"""Temp check: the Context pane's app-side wiring (pane parity).

Builds a real `MainWindow` and exercises the twelve places in `src/ui.py` that
enumerate the panes, plus the context message handlers. It never starts a
session, so no audio device is touched.

Side-effect containment (nothing of the user's is modified):
  * `ui_state.json` is never touched: `load_state`/`save_state` are redirected
    to a temp file *before* `MainWindow` is built.
  * The session store and purpose store are redirected to a temp dir.
  * The Go hub is disabled (`HUB_ENABLED=false`), so no hub is started,
    adopted or stopped.
  * The macOS screen-recording permission prompt is stubbed out.
"""
import json
import os
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO_ROOT)
os.environ["HUB_ENABLED"] = "false"

# Redirect the stores before anything imports them, so a flush on close cannot
# rewrite the user's session / purposes / ui-state files.
TMP_DIR = tempfile.mkdtemp(prefix="context-app-check-")
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

# A scratch ui_state.json, so the test starts from a first-run state and the
# user's real pane layout is never read or written.
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
    pane = window.context_window

    print("[1] the pane is constructed and starts hidden")
    check("pane exists", pane is not None)
    check("webview points at /context", pane.get_webview().url().toString().endswith("/context"))
    check("Tool action unchecked", not window.context_window_action.isChecked())
    check("pane hidden", not pane.isVisible())
    check("free-floating by default", not pane.is_docked())
    from src.ui_components.context_window import (
        CONTEXT_WINDOW_WIDTH, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
    )
    check("default width", pane.get_width() == CONTEXT_WINDOW_WIDTH, str(pane.get_width()))
    check("min sizes are set", (MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT) == (240, 140))

    print("\n[2] Tool menu + hotkey wiring")
    labels = [action.text() for action in window.tool_menu.actions()]
    check("Tool menu lists Context", "Context" in labels, str(labels))
    check("hotkey callback bound", window.hotkeys._callbacks[7] == window._toggle_context_window)

    print("\n[3] visibility toggles (and persists)")
    window._toggle_context_window()
    check("hotkey shows it", window.context_window_action.isChecked() and pane.isVisible())
    window._toggle_context_window()
    check("hotkey hides it", not window.context_window_action.isChecked() and not pane.isVisible())
    window.context_window_action.setChecked(True)
    check("action shows it", pane.isVisible())

    print("\n[4] geometry parity: dock, swap, always-on-top, screen protection")
    window._set_pane_edge(pane, "left")
    check("docked left", pane.is_docked() and pane.get_edge() == "left")
    window._set_pane_edge(window.gemini_window, "left")
    check("docked Gemini pushed the context pane away", pane.get_edge() == "right")
    window._set_always_on_top(False)
    check("always-on-top off reaches the pane", pane._always_on_top is False)
    window._set_screen_protection(False)
    check("screen protection reaches the pane", pane._screen_protection_enabled is False)
    window._set_always_on_top(True)
    window._set_screen_protection(True)

    print("\n[5] hide-all covers the pane")
    window._toggle_all_panes()
    check("hidden by Ctrl+Shift+M", not window.context_window_action.isChecked())
    window._toggle_all_panes()
    check("restored by Ctrl+Shift+M", window.context_window_action.isChecked())

    print("\n[6] _save_state persists the pane")
    window._save_state()
    with open(UI_STATE, "r", encoding="utf-8") as handle:
        saved = json.load(handle)
    check("geometry block written", "context_window" in saved)
    check("edge persisted", saved["context_window"]["edge"] == pane.get_edge())
    check("visibility persisted", saved["settings"]["context_window_visible"] is True)

    print("\n[7] context messages reach the reply path")
    window._handle_webview_message(
        {"type": "context_state", "contents": {"host": "HOSTCTX", "speaker": "SPEAKERCTX"}}
    )
    check("mirrored", window.translation_controller._context == {"host": "HOSTCTX", "speaker": "SPEAKERCTX"})
    window._handle_webview_message({"type": "context_state", "contents": {"host": "", "speaker": ""}})
    check("empty means 'no context'", window.translation_controller._context == {"host": "", "speaker": ""})
    window._handle_webview_message({"type": "context_state"})
    check("malformed payload ignored", window.translation_controller._context == {"host": "", "speaker": ""})
    window._handle_webview_message({"type": "hide_context_window"})
    check("pane hide message honoured", not window.context_window_action.isChecked())
    window._handle_webview_message({"type": "set_context_window_edge", "edge": "left"})
    check("edge message honoured", pane.get_edge() == "left" and pane.is_docked())
    print("\n[7b] Browse…/New… open a native dialog and report the picked path")
    # The dialogs are modal, so stub them out (there is no user here) and
    # capture what the app would send back to the web service.
    picked = os.path.join(TMP_DIR, "picked.md")
    created = os.path.join(TMP_DIR, "created.md")

    class FakeFileDialog:
        @staticmethod
        def getOpenFileName(*args, **kwargs):
            return picked, ""

        @staticmethod
        def getSaveFileName(*args, **kwargs):
            return created, ""

    ui.QFileDialog = FakeFileDialog
    sent = []
    window.websocket_client.send_message = sent.append

    window._handle_webview_message({"type": "connection"})
    check("connection asks for the context", sent[-1] == {"type": "context_get"}, str(sent[-1]))
    window._flush_context_editor()
    check("flush message", sent[-1] == {"type": "context_flush"}, str(sent[-1]))
    window._handle_webview_message({"type": "context_browse", "role": "host"})
    check("browse selects the picked file",
          sent[-1] == {"type": "context_select", "role": "host", "path": picked}, str(sent[-1]))
    window._handle_webview_message({"type": "context_new_request", "role": "speaker"})
    check("new creates the chosen file",
          sent[-1] == {"type": "context_new", "role": "speaker", "path": created}, str(sent[-1]))
    window._handle_webview_message({"type": "context_browse", "role": "nonsense"})
    check("an unknown role falls back to host",
          sent[-1] == {"type": "context_select", "role": "host", "path": picked}, str(sent[-1]))

    print("\n[8] the persisted state round-trips (fresh MainWindow loads it)")
    window._save_state()
    saved_edge = pane.get_edge()
    saved_visible = window.context_window_action.isChecked()
    restored = ui.load_state()
    check("scratch state has the pane", "context_window" in restored)
    check("edge round-trips", restored["context_window"]["edge"] == saved_edge)
    check("visibility round-trips", restored["settings"]["context_window_visible"] is saved_visible)
finally:
    if window is not None:
        window.close()

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else 0)
