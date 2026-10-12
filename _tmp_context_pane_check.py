"""Temp check: the Context pane's HTML/JS really renders and talks to the server.

Loads `http://localhost:<port>/context` in a real QWebEngineView and asserts the
Preact app built its DOM, connected over the WebSocket, asked for `context_get`
and painted the selected file's text into the editor — the one part
`node --check` cannot cover.

Run a server first (any port): `cd websocket-server && PORT=8790 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.
"""
import os
import sys

PORT = os.environ.get("CONTEXT_PANE_PORT", "8790")

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

console = []
results = {}
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
view.resize(460, 520)
view.show()


def collect(key):
    def _cb(value):
        results[key] = value
    return _cb


PROBES = {
    "root_len": "document.getElementById('context-root')"
                " ? document.getElementById('context-root').innerHTML.length : -1",
    "tabs": "[...document.querySelectorAll('.bullet-tab')].map(b => b.textContent.trim()).join('|')",
    "buttons": "[...document.querySelectorAll('button')].map(b => b.textContent.trim()).join('|')",
    "selected": "(document.querySelector('.context-select') || {}).value || ''",
    "text_len": "document.querySelector('.context-textarea')"
                " ? document.querySelector('.context-textarea').value.length : -1",
    "text": "document.querySelector('.context-textarea')"
            " ? document.querySelector('.context-textarea').value : ''",
    "disabled": "document.querySelector('.context-textarea')"
                " ? document.querySelector('.context-textarea').disabled : null",
    "hint": "(document.querySelector('.context-hint') || {}).textContent || ''",
    "chips": "document.querySelectorAll('.context-chip').length",
    "status": "(document.querySelector('.context-save-status') || {}).textContent || ''",
}


def probe():
    for key, script in PROBES.items():
        page.runJavaScript(script, collect(key))
    QTimer.singleShot(1500, report)


def report():
    print("[1] the page renders")
    check("root has content", (results.get("root_len") or 0) > 200, str(results.get("root_len")))
    check("Host/Speaker tabs", results.get("tabs") == "Host|Speaker", str(results.get("tabs")))
    buttons = (results.get("buttons") or "").split("|")
    check("Browse… / New… / Save buttons",
          all(b in buttons for b in ("Browse…", "New…", "Save")), str(buttons))
    check("pane controls", all(b in buttons for b in ("⇤", "⇥", "−")))

    print("\n[2] the state came over the WebSocket and painted")
    check("a file is selected", bool(results.get("selected")), str(results.get("selected")))
    check("editor holds the file text", (results.get("text_len") or 0) > 0,
          f"{results.get('text_len')} chars")
    check("editor is editable", results.get("disabled") is False)
    check("path shown in the footer", bool((results.get("hint") or "").strip()),
          (results.get("hint") or "")[:60])
    check("recent list rendered", (results.get("chips") or 0) >= 1, str(results.get("chips")))

    print("\n[3] the text on screen is the file on disk")
    on_disk = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "context_sample.txt"), encoding="utf-8").read().strip()
    check("textarea equals context_sample.txt", (results.get("text") or "").strip() == on_disk,
          f"screen={len(results.get('text') or '')} disk={len(on_disk)}")

    print("\n[4] no JavaScript errors")
    errors = [line for line in console if "Error" in line]
    check("console clean", not errors, "; ".join(errors[:3]))
    for line in console[:10]:
        print("      console:", line)

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    app.exit(1 if failures else 0)


def on_load(ok):
    if not ok:
        print("FAIL  the page did not load")
        app.exit(1)
        return
    QTimer.singleShot(2000, probe)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/context"))
QTimer.singleShot(25000, report)

sys.exit(app.exec())
