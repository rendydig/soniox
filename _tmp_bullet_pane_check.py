"""Temp check: the Bullet Points pane really renders and its buttons work.

Loads `http://localhost:<port>/bullets` in a real QWebEngineView and asserts the
Preact app built its DOM, that the bullets tab shows both action buttons inside
`.bullet-header-actions`, and that clicking them sends the right control messages
over the WebSocket (`trigger_bullet_points` / `regenerate_bullet_points`) — the
part `node --check` cannot cover, because htm templates only fail at render time.

Run a server first (any port): `cd websocket-server && PORT=8793 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.

    BULLET_PANE_PORT=8793 venv/bin/python _tmp_bullet_pane_check.py
"""
import json
import os
import sys

PORT = os.environ.get("BULLET_PANE_PORT", "8793")

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

# Everything is synchronous in the page: render probe, spy on WebSocket.send,
# click both buttons, and report what was sent.
PROBE_SCRIPT = """
(function () {
    var out = { ok: true };
    try {
        var root = document.getElementById('bullets-root');
        var card = document.querySelector('#bullets-root .card.bullet-card');
        var actionNodes = Array.prototype.slice.call(
            document.querySelectorAll('.bullet-header-actions button'));
        var buttonNodes = Array.prototype.slice.call(document.querySelectorAll('button'));
        out.rootLen = root ? root.innerHTML.length : -1;
        out.hasCard = !!card;
        out.actions = actionNodes.map(function (b) { return b.textContent.trim(); });
        out.allButtons = buttonNodes.map(function (b) { return b.textContent.trim(); });

        var sent = [];
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data) { sent.push(String(data)); return orig.apply(this, arguments); };
        var clickByLabel = function (label) {
            var btn = actionNodes.filter(function (b) { return b.textContent.trim() === label; })[0];
            if (btn) { btn.click(); }
            return !!btn;
        };
        out.clickedFetch = clickByLabel('Fetch new');
        out.clickedRebuild = clickByLabel('Rebuild');
        WebSocket.prototype.send = orig;
        out.sent = sent.map(function (s) {
            try { return JSON.parse(s).type; } catch (e) { return s; }
        });
    } catch (e) {
        out.ok = false;
        out.error = String(e);
    }
    return JSON.stringify(out);
})()
"""


def collect(key):
    def _cb(value):
        results[key] = value
    return _cb


def probe():
    page.runJavaScript(PROBE_SCRIPT, collect("probe"))
    QTimer.singleShot(1500, report)


def report():
    raw = results.get("probe")
    try:
        probe_result = json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        probe_result = {}
    if not isinstance(probe_result, dict):
        probe_result = {}
    print("[1] the page renders")
    check("the DOM probe returned data", bool(probe_result), str(raw)[:120])
    check("the probe script did not throw", probe_result.get("ok") is True,
          str(probe_result.get("error")))
    check("root has content", (probe_result.get("rootLen") or 0) > 200, str(probe_result.get("rootLen")))
    check("the bullet card is mounted", bool(probe_result.get("hasCard")))

    print("\n[2] the bullets tab shows Fetch new + Rebuild side by side")
    actions = probe_result.get("actions") or []
    check("both action buttons are inside .bullet-header-actions",
          actions == ["Fetch new", "Rebuild"], str(actions))
    all_buttons = probe_result.get("allButtons") or []
    check("pane controls still present", all(b in all_buttons for b in ("⇤", "⇥", "−")), str(all_buttons))

    print("\n[3] the buttons send the right control messages")
    sent = probe_result.get("sent") or []
    check("Fetch new clicked", bool(probe_result.get("clickedFetch")))
    check("Rebuild clicked", bool(probe_result.get("clickedRebuild")))
    check("Fetch new sends trigger_bullet_points (incremental)",
          "trigger_bullet_points" in sent, str(sent))
    check("Rebuild sends regenerate_bullet_points",
          "regenerate_bullet_points" in sent, str(sent))

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
    QTimer.singleShot(2500, probe)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/bullets"))
QTimer.singleShot(25000, report)

sys.exit(app.exec())
