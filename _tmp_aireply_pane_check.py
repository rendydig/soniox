"""Temp check: the AI suggestion pane's title ring tracks the reply's life cycle.

Loads `http://localhost:<port>/gemini` in a real QWebEngineView and asserts:
  * the header renders "✨ AI suggestion" with the ⇤/⇥/− controls and the buttons;
  * no ring before anything happens;
  * a `gemini_status started` frame turns the ring on;
  * a streaming chunk keeps it on;
  * the final `gemini_result` turns it off and renders the reply;
  * `started` → `complete` (the auto-reply error path's exit frame) turns it off again;
  * the console stays clean.

Covers the htm template + the `started`/`complete` mapping, which `node --check` cannot.

Run a server first (any port): `cd websocket-server && PORT=8797 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.

    AIREPLY_PANE_PORT=8797 venv/bin/python _tmp_aireply_pane_check.py
"""
import json
import os
import sys

PORT = os.environ.get("AIREPLY_PANE_PORT", "8797")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

console = []
failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        console.append(f"{level.name}: {message}")


app = QApplication(sys.argv)
view = QWebEngineView()
page = Page(view)
view.setPage(page)
view.resize(460, 460)
view.show()

# The whole sequence lives in the page: a second WS client plays the desktop app
# and pushes the frames the server rebroadcasts to the pane's own connection.
PROBE = """
(function () {
    window.__ring = { steps: [], done: false };
    function mark(name, cond) { window.__ring.steps.push([name, !!cond]); }
    function send(obj) { peer.send(JSON.stringify(obj)); }

    var peer = new WebSocket('ws://localhost:%PORT%');
    peer.onopen = function () {
        var title = document.querySelector('.gemini-title');
        mark('titleFound', title);
        mark('titleText', title && title.textContent.indexOf('AI suggestion') >= 0);
        mark('noSpinnerInitially', !document.querySelector('.ai-spinner'));
        mark('controlsPresent',
            document.querySelectorAll('.gemini-controls .gemini-control-btn').length === 3);
        mark('actionsPresent', !!document.querySelector('.gemini-header-actions .btn-gemini'));
        mark('togglePresent', !!document.querySelector('.gemini-header-actions .toggle-label'));

        send({ type: 'gemini_status', status: 'started', mode: 'auto_reply' });
        setTimeout(function () {
            mark('spinnerOnStarted', !!document.querySelector('.ai-spinner'));
            send({ type: 'gemini_stream', text: 'Thinking about it', mode: 'auto_reply' });
            setTimeout(function () {
                mark('spinnerOnStream', !!document.querySelector('.ai-spinner'));
                send({ type: 'gemini_result', text: 'Hello there from the test', mode: 'auto_reply' });
                setTimeout(function () {
                    mark('spinnerOffAfterResult', !document.querySelector('.ai-spinner'));
                    mark('resultRendered',
                        document.body.textContent.indexOf('Hello there from the test') >= 0);
                    send({ type: 'gemini_status', status: 'started', mode: 'auto_reply' });
                    setTimeout(function () {
                        mark('spinnerOnAgain', !!document.querySelector('.ai-spinner'));
                        send({ type: 'gemini_status', status: 'complete', mode: 'auto_reply' });
                        setTimeout(function () {
                            mark('spinnerOffAfterComplete', !document.querySelector('.ai-spinner'));
                            window.__ring.done = true;
                        }, 250);
                    }, 250);
                }, 300);
            }, 200);
        }, 250);
    };
    return 'started';
})()
""".replace("%PORT%", PORT)

READ = "(function () { return JSON.stringify(window.__ring || {}); })()"

state = {"tries": 0}


def poll():
    state["tries"] += 1

    def _cb(value):
        try:
            data = json.loads(value) if isinstance(value, str) else {}
        except ValueError:
            data = {}
        if data.get("done"):
            report(data)
        elif state["tries"] < 40:
            QTimer.singleShot(250, poll)
        else:
            check("the probe finished", False, f"steps={data.get('steps')}")
            report(data)

    page.runJavaScript(READ, _cb)


def report(data):
    steps = dict(data.get("steps") or [])

    print("[1] the header renders")
    check("the title span exists", steps.get("titleFound") is True)
    check("the label reads 'AI suggestion'", steps.get("titleText") is True)
    check("no ring before any request", steps.get("noSpinnerInitially") is True)
    check("the ⇤/⇥/− controls are present", steps.get("controlsPresent") is True)
    check("the Reply now button is present", steps.get("actionsPresent") is True)
    check("the Auto reply toggle is present", steps.get("togglePresent") is True)

    print("\n[2] the ring follows the request")
    check("a 'started' frame turns the ring on", steps.get("spinnerOnStarted") is True)
    check("a streaming chunk keeps it on", steps.get("spinnerOnStream") is True)
    check("the final result turns it off", steps.get("spinnerOffAfterResult") is True)
    check("the reply rendered", steps.get("resultRendered") is True)

    print("\n[3] an explicit 'complete' also turns it off")
    check("a second 'started' turns it on", steps.get("spinnerOnAgain") is True)
    check("'complete' turns it off", steps.get("spinnerOffAfterComplete") is True)

    print("\n[4] no JavaScript errors")
    errors = [line for line in console if "Error" in line]
    check("console clean", not errors, "; ".join(errors[:3]))
    for line in console[:6]:
        print("      console:", line)

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    app.exit(1 if failures else 0)


def on_load(ok):
    if not ok:
        print("FAIL  the page did not load")
        app.exit(1)
        return
    QTimer.singleShot(2500, lambda: page.runJavaScript(PROBE))
    QTimer.singleShot(3000, poll)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/gemini"))
QTimer.singleShot(30000, lambda: report({}))

sys.exit(app.exec())
