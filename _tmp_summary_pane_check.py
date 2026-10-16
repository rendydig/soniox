"""Temp check: the Summary tab really renders, summarizes, and edits.

Loads `http://localhost:<port>/bullets` in a real QWebEngineView and asserts:
  * the new "Summary" tab renders with the Summarize button + empty-state hint;
  * clicking Summarize sends `{"type":"summarize"}`;
  * an incoming `summary` frame (pushed by a second WS client) renders as markdown;
  * a **double-click** switches to edit mode (a `.summary-editor` textarea);
  * typing **auto-saves** after the debounce (a `summary_save` frame is sent);
  * the **Back** button returns to preview showing the edited text.

Covers the htm template + the debounce loop, which `node --check` cannot.

Run a server first (any port): `cd websocket-server && PORT=8794 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.

    SUMMARY_PANE_PORT=8794 venv/bin/python _tmp_summary_pane_check.py
"""
import json
import os
import sys

PORT = os.environ.get("SUMMARY_PANE_PORT", "8794")

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

# Step 1: switch to the Summary tab, capture its body, click Summarize (spying on
# WebSocket.send), then push a summary frame from a second client so the server
# rebroadcasts it to this page.
PROBE1 = """
(function () {
    window.__sum = {};
    var tab = Array.prototype.slice.call(document.querySelectorAll('.bullet-tab'))
        .filter(function (b) { return b.textContent.trim() === 'Summary'; })[0];
    window.__sum.tabFound = !!tab;
    if (tab) { tab.click(); }
    setTimeout(function () {
        var view = document.querySelector('.live-text.summary-view');
        window.__sum.hasView = !!view;
        window.__sum.title = (document.querySelector('.summary-title') || {}).textContent || '';
        window.__sum.empty = (document.querySelector('.summary-view .bullet-empty') || {}).textContent || '';
        var btn = document.querySelector('.summary-actions button');
        window.__sum.button = btn ? btn.textContent.trim() : '';
        var sent = [];
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data) { sent.push(String(data)); return orig.apply(this, arguments); };
        if (btn) { btn.click(); }
        WebSocket.prototype.send = orig;
        window.__sum.sent = sent.map(function (s) {
            try { return JSON.parse(s).type; } catch (e) { return s; }
        });
        var peer = new WebSocket('ws://localhost:%PORT%');
        peer.onopen = function () {
            peer.send(JSON.stringify({
                type: 'summary',
                text: '## Overview\\n\\nHello world.\\n\\n## Key Points\\n\\n- one\\n- two'
            }));
        };
    }, 300);
    return 'started';
})()
""".replace("%PORT%", PORT)

# Step 2: read the rendered markdown, then drive the edit flow (double-click ->
# type -> wait out the 800 ms debounce -> Back) into `window.__edit`.
PROBE2 = """
(function () {
    var md = document.querySelector('.summary-view .markdown-body');
    window.__sum.hasMarkdown = !!md;
    window.__sum.headings = md ? Array.prototype.slice.call(md.querySelectorAll('h2'))
        .map(function (h) { return h.textContent.trim(); }) : [];
    window.__sum.mdText = md ? md.textContent : '';
    window.__sum.emptyGone = !document.querySelector('.summary-view .bullet-empty');

    window.__edit = {};
    var editSent = [];
    var orig = WebSocket.prototype.send;
    WebSocket.prototype.send = function (d) { editSent.push(String(d)); return orig.apply(this, arguments); };

    var target = document.querySelector('.summary-text') || document.querySelector('.summary-view .bullet-empty');
    window.__edit.dblTarget = !!target;
    if (target) { target.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); }

    setTimeout(function () {
        var ta = document.querySelector('.summary-view textarea.summary-editor');
        window.__edit.editorAppeared = !!ta;
        window.__edit.editorValue = ta ? ta.value : '';
        window.__edit.backLabel = (document.querySelector('.summary-actions-right button') || {}).textContent.trim();
        if (ta) {
            ta.value = '## Overview\\n\\nEDITED by test';
            ta.dispatchEvent(new Event('input', { bubbles: true }));
        }
        setTimeout(function () {
            window.__edit.sentTypes = editSent.map(function (s) {
                try { return JSON.parse(s).type; } catch (e) { return s; }
            });
            window.__edit.sentTexts = editSent.map(function (s) {
                try { var o = JSON.parse(s); return o.type === 'summary_save' ? o.text : null; }
                catch (e) { return null; }
            }).filter(Boolean);
            var back = document.querySelector('.summary-actions-right button');
            if (back) { back.click(); }
            setTimeout(function () {
                WebSocket.prototype.send = orig;
                window.__edit.editorGone = !document.querySelector('.summary-view textarea.summary-editor');
                var st = document.querySelector('.summary-view .summary-text');
                window.__edit.previewHasEdited = st ? st.textContent.indexOf('EDITED by test') >= 0 : false;
            }, 250);
        }, 1000);
    }, 300);
    return JSON.stringify(window.__sum);
})()
"""

PROBE3 = "(function () { return JSON.stringify(window.__edit || {}); })()"


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


def probe1():
    page.runJavaScript(PROBE1, collect("probe1"))
    QTimer.singleShot(1800, probe2)


def probe2():
    page.runJavaScript(PROBE2, collect("probe2"))
    QTimer.singleShot(2400, probe3)


def probe3():
    page.runJavaScript(PROBE3, collect("probe3"))
    QTimer.singleShot(500, report)


def report():
    sm = _parse("probe2")
    ed = _parse("probe3")

    print("[1] the Summary tab renders")
    check("the Summary tab button exists", sm.get("tabFound") is True)
    check("the summary view is mounted", sm.get("hasView") is True)
    check("a title is shown", sm.get("title") == "Session summary", str(sm.get("title")))
    check("the Summarize button is present", sm.get("button") == "Summarize", str(sm.get("button")))
    check("the empty-state hint is shown before any summary",
          "No summary yet" in (sm.get("empty") or ""), str(sm.get("empty")))

    print("\n[2] the button sends the summarize control message")
    check("'summarize' was sent", "summarize" in (sm.get("sent") or []), str(sm.get("sent")))

    print("\n[3] an incoming summary frame renders as markdown")
    check("a markdown body rendered", sm.get("hasMarkdown") is True)
    check("h2 sections rendered", sm.get("headings") == ["Overview", "Key Points"],
          str(sm.get("headings")))
    check("the body carries the text", "Hello world." in (sm.get("mdText") or ""),
          str(sm.get("mdText"))[:80])
    check("the empty-state hint is gone", sm.get("emptyGone") is True)

    print("\n[4] a double-click opens the editor")
    check("the preview was a double-click target", ed.get("dblTarget") is True)
    check("the textarea appeared", ed.get("editorAppeared") is True)
    check("the editor was seeded with the preview text",
          (ed.get("editorValue") or "").startswith("## Overview"), repr(ed.get("editorValue")))
    check("a Back button replaced Summarize", ed.get("backLabel") == "Back", str(ed.get("backLabel")))

    print("\n[5] typing auto-saves after the debounce")
    check("a summary_save frame was sent", "summary_save" in (ed.get("sentTypes") or []),
          str(ed.get("sentTypes")))
    check("the saved text is the edit",
          any("EDITED by test" in t for t in (ed.get("sentTexts") or [])), str(ed.get("sentTexts")))

    print("\n[6] Back returns to preview showing the edit")
    check("the textarea is gone", ed.get("editorGone") is True)
    check("the preview shows the edited text", ed.get("previewHasEdited") is True)

    print("\n[7] no JavaScript errors")
    errors = [line for line in console if "Error" in line]
    check("console clean", not errors, "; ".join(errors[:3]))
    for line in console[:8]:
        print("      console:", line)

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    app.exit(1 if failures else 0)


def on_load(ok):
    if not ok:
        print("FAIL  the page did not load")
        app.exit(1)
        return
    QTimer.singleShot(2500, probe1)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/bullets"))
QTimer.singleShot(30000, report)

sys.exit(app.exec())
