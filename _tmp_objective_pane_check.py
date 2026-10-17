"""Temp check: the Objectives tab really renders and wires its four messages.

Loads `http://localhost:<port>/bullets` in a real QWebEngineView and asserts:
  * the new "Objectives" tab renders the list, the add form and its buttons;
  * "Predict now" sends `trigger_objective_prediction`;
  * submitting the add form sends `add_objective` with the typed text;
  * an incoming `objectives` frame renders the items, marks the tracked one and
    shows the Locked badge when the focus is pinned;
  * an incoming `objectives_history` frame appends to the timeline;
  * clicking a padlock sends `set_objective_lock` and the remove button sends
    `remove_objective`.

Covers the htm template, which `node --check` cannot.

Run a server first (any port): `cd websocket-server && PORT=8796 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.

    OBJECTIVE_PANE_PORT=8796 venv/bin/python _tmp_objective_pane_check.py
"""
import json
import os
import sys

PORT = os.environ.get("OBJECTIVE_PANE_PORT", "8796")

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
view.resize(460, 640)
view.show()

# Step 1: open the tab, capture its structure, click Predict now and add an
# objective while spying on WebSocket.send, then push one objectives frame and
# one history frame from a second client (the server rebroadcasts both).
PROBE1 = """
(function () {
    window.__c = {};
    window.__errs = [];
    window.addEventListener('error', function (e) {
        window.__errs.push({ message: e.message,
                             stack: (e.error && e.error.stack) || '' });
    });
    window.addEventListener('unhandledrejection', function (e) {
        window.__errs.push({ message: 'rejection: ' + ((e.reason && e.reason.message) || e.reason),
                             stack: (e.reason && e.reason.stack) || '' });
    });
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.bullet-tab'));
    var tab = tabs.filter(function (b) { return b.textContent.trim() === 'Objectives'; })[0];
    window.__c.tabFound = !!tab;
    if (tab) { tab.click(); }
    setTimeout(function () {
        var sent = [];
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (d) { sent.push(String(d)); return orig.apply(this, arguments); };

        window.__c.hasView = !!document.querySelector('.live-text.objectives-view');
        window.__c.hasInput = !!document.querySelector('.objectives-input');
        var hint = document.querySelector('.objectives-view .bullet-empty');
        window.__c.emptyHint = !!hint && !hint.classList.contains('empty');
        window.__c.itemCount = document.querySelectorAll('.objective-item').length;
        var predict = Array.prototype.slice.call(document.querySelectorAll('.objectives-view button'))
            .filter(function (b) { return b.textContent.trim() === 'Predict now'; })[0];
        window.__c.hasPredict = !!predict;
        if (predict) { predict.click(); }

        var input = document.querySelector('.objectives-input');
        if (input) {
            input.value = 'Ship the pilot';
            input.dispatchEvent(new Event('input', { bubbles: true }));
        }
        setTimeout(function () {
            var add = Array.prototype.slice.call(document.querySelectorAll('.objectives-view button'))
                .filter(function (b) { return b.textContent.trim() === 'Add'; })[0];
            if (add) { add.click(); }
            setTimeout(function () {
                WebSocket.prototype.send = orig;
                window.__c.sent = sent.map(function (s) {
                    try { return JSON.parse(s); } catch (e) { return s; }
                });
                window.__c.inputCleared = document.querySelector('.objectives-input')
                    ? document.querySelector('.objectives-input').value === '' : null;

                var peer = new WebSocket('ws://localhost:%PORT%');
                peer.onopen = function () {
                    peer.send(JSON.stringify({ type: 'objectives',
                        items: ['Ship the pilot', 'Agree on pricing'],
                        locks: [false, true],
                        active: { index: 1, text: 'Agree on pricing', locked: true,
                                  confidence: 1.0, source: 'lock' } }));
                    peer.send(JSON.stringify({ type: 'objectives_history',
                        entry: { ts: '2026-10-17T01:00:00Z', index: 1,
                                 text: 'Agree on pricing', confidence: 0.8, source: 'jev' } }));
                    peer.send(JSON.stringify({ type: 'objectives_status', status: 'started' }));
                };
            }, 300);
        }, 150);
    }, 300);
    return 'started';
})()
""".replace("%PORT%", PORT)

# Step 2: read what the pushed frames rendered, then click the second padlock
# (unlock) and the first remove button, capturing what each sends.
PROBE2 = """
(function () {
    var c = window.__c || {};
    c.items = Array.prototype.slice.call(document.querySelectorAll('.objective-item .bullet-text'))
        .map(function (e) { return e.textContent.trim(); });
    c.lockedCount = document.querySelectorAll('.objective-item.locked').length;
    c.activeText = (document.querySelector('.objectives-active .objectives-active-text') || {}).textContent;
    c.activeClassCount = document.querySelectorAll('.objective-item.active').length;
    c.badges = Array.prototype.slice.call(document.querySelectorAll('.objectives-view .consulting-badge'))
        .map(function (b) { return b.textContent.trim(); });
    c.timelineCount = document.querySelectorAll('.objectives-timeline-item').length;
    c.timelineText = (document.querySelector('.objectives-timeline-text') || {}).textContent;
    var statusEl = document.querySelector('.objectives-view .bullet-status');
    c.status = statusEl ? statusEl.textContent : '';
    c.statusVisible = !!statusEl && !statusEl.classList.contains('empty');
    var hint = document.querySelector('.objectives-view .bullet-empty');
    c.hintHidden = !!hint && hint.classList.contains('empty');

    var sent = [];
    var orig = WebSocket.prototype.send;
    WebSocket.prototype.send = function (d) { sent.push(String(d)); return orig.apply(this, arguments); };
    var pads = document.querySelectorAll('.objective-item .bullet-lock');
    c.ariaPressedBefore = pads[1] ? pads[1].getAttribute('aria-pressed') : null;
    if (pads[1]) { pads[1].click(); }
    var removes = document.querySelectorAll('.objective-item .objective-remove');
    if (removes[0]) { removes[0].click(); }
    WebSocket.prototype.send = orig;
    var out = sent.map(function (s) { try { return JSON.parse(s); } catch (e) { return {}; } });
    c.lockSent = out.filter(function (m) { return m.type === 'set_objective_lock'; });
    c.removeSent = out.filter(function (m) { return m.type === 'remove_objective'; });
    c.ariaPressed = pads[1] ? pads[1].getAttribute('aria-pressed') : null;
    c.errs = window.__errs || [];
    return JSON.stringify(c);
})()
"""


def collect(key):
    def _cb(value):
        results[key] = value
    return _cb


def _parse(key):
    raw = results.get(key)
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}


def probe2():
    page.runJavaScript(PROBE2, collect("probe2"))
    QTimer.singleShot(600, report)


def report():
    # PROBE2 merges `window.__c` (what PROBE1 captured) into its own result, so
    # one parse covers both steps.
    c = _parse("probe2")

    print("[1] the Objectives tab renders")
    check("the tab exists and was clicked", c.get("tabFound") is True)
    check("the view rendered", c.get("hasView") is True)
    check("the add form rendered", c.get("hasInput") is True)
    check("an empty list shows the hint", c.get("emptyHint") is True)
    check("the Predict now button rendered", c.get("hasPredict") is True)

    print("\n[2] the controls send the right messages")
    sent = c.get("sent") or []
    types = [m.get("type") if isinstance(m, dict) else m for m in sent]
    check("Predict now sent trigger_objective_prediction",
          "trigger_objective_prediction" in types, str(types))
    adds = [m for m in sent if isinstance(m, dict) and m.get("type") == "add_objective"]
    check("the add form sent add_objective with the typed text",
          bool(adds) and adds[0].get("text") == "Ship the pilot", str(adds))
    check("the input was cleared after adding", c.get("inputCleared") is True)

    p2 = _parse("probe2")
    print("\n[3] an incoming objectives frame renders")
    check("both objectives are listed", p2.get("items") == ["Ship the pilot", "Agree on pricing"],
          str(p2.get("items")))
    check("the locked item carries the tint", p2.get("lockedCount") == 1,
          str(p2.get("lockedCount")))
    check("the tracked objective is marked active", p2.get("activeClassCount") == 1,
          str(p2.get("activeClassCount")))
    check("the focus banner names it", p2.get("activeText") == "Agree on pricing",
          str(p2.get("activeText")))
    check("the Locked badge is shown", "Locked" in (p2.get("badges") or []), str(p2.get("badges")))
    check("the status line is rendered", (p2.get("status") or "").strip() != ""
          and p2.get("statusVisible") is True, str(p2.get("status")))
    check("the empty-state hint hides once there are items",
          p2.get("hintHidden") is True)

    print("\n[4] an incoming history frame appends to the timeline")
    check("one timeline entry rendered", p2.get("timelineCount") == 1,
          str(p2.get("timelineCount")))
    check("it names the objective", p2.get("timelineText") == "Agree on pricing",
          str(p2.get("timelineText")))

    print("\n[5] the per-item controls send the right messages")
    lock_sent = p2.get("lockSent") or []
    check("clicking a padlock sends set_objective_lock",
          bool(lock_sent) and lock_sent[0].get("index") == 1
          and lock_sent[0].get("text") == "Agree on pricing"
          and lock_sent[0].get("locked") is False, str(lock_sent))
    # The pane only re-renders when the app echoes the new frame, so the click
    # itself must not flip the attribute (it sends the intended value instead).
    check("the locked padlock reports aria-pressed=true before the click",
          p2.get("ariaPressedBefore") == "true", str(p2.get("ariaPressedBefore")))
    remove_sent = p2.get("removeSent") or []
    check("clicking the remove button sends remove_objective",
          bool(remove_sent) and remove_sent[0].get("index") == 0, str(remove_sent))

    print("\n[6] no JavaScript errors")
    errors = [line for line in console if "Error" in line]
    check("console clean", not errors, "; ".join(errors[:3]))
    for err in (p2.get("errs") or []):
        print("      page error:", err.get("message"))
        for line in (err.get("stack") or "").splitlines()[:6]:
            print("        ", line.strip())

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    app.exit(1 if failures else 0)


def probe1():
    page.runJavaScript(PROBE1, collect("probe1"))
    QTimer.singleShot(2200, probe2)


def on_load(ok):
    if not ok:
        print("FAIL  the page did not load")
        app.exit(1)
        return
    QTimer.singleShot(2500, probe1)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/bullets"))
QTimer.singleShot(32000, report)

sys.exit(app.exec())
