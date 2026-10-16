"""Temp check: the Consulting tab really renders and wires its five messages.

Loads `http://localhost:<port>/bullets` in a real QWebEngineView and asserts:
  * the new "Consulting" tab renders the three stacked sections + their buttons;
  * clicking Draft brief / Analyze gaps sends the right control messages;
  * the roadmap button starts disabled (brief unconfirmed) and enables once an
    incoming confirmed `consulting` frame arrives;
  * incoming `consulting` frames render as markdown;
  * clicking Confirm sends `confirm_brief`;
  * a **double-click** on the brief opens the editor; typing auto-saves a
    `consulting_save`; **Back** returns to preview showing the edit.

Covers the htm template + the debounce loop, which `node --check` cannot.

Run a server first (any port): `cd websocket-server && PORT=8795 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.

    CONSULTING_PANE_PORT=8795 venv/bin/python _tmp_consulting_pane_check.py
"""
import json
import os
import sys

PORT = os.environ.get("CONSULTING_PANE_PORT", "8795")

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

# Step 1: switch to the Consulting tab, capture its structure, click the two
# enabled buttons while spying on WebSocket.send, then push three consulting
# frames (brief confirmed) from a second client so the server rebroadcasts them.
PROBE1 = """
(function () {
    window.__c = {};
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.bullet-tab'));
    var tab = tabs.filter(function (b) { return b.textContent.trim() === 'Consulting'; })[0];
    window.__c.tabFound = !!tab;
    if (tab) { tab.click(); }
    setTimeout(function () {
        function btn(text) {
            var all = Array.prototype.slice.call(document.querySelectorAll('.consulting-view button'));
            return all.filter(function (b) { return b.textContent.trim() === text; })[0] || null;
        }
        window.__c.hasView = !!document.querySelector('.live-text.consulting-view');
        window.__c.sections = document.querySelectorAll('.consulting-section').length;
        window.__c.titles = Array.prototype.slice.call(document.querySelectorAll('.consulting-title'))
            .map(function (e) { return e.textContent.trim().replace(/\\s+/g, ' '); });
        window.__c.hasDraft = !!btn('Draft brief');
        window.__c.hasAnalyze = !!btn('Analyze gaps');
        window.__c.hasRoadmap = !!btn('Generate roadmap');
        window.__c.hasConfirm = !!btn('Confirm');
        var rm = btn('Generate roadmap');
        window.__c.roadmapDisabled = rm ? rm.disabled : null;

        var sent = [];
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data) { sent.push(String(data)); return orig.apply(this, arguments); };
        var db = btn('Draft brief'); if (db) { db.click(); }
        var ag = btn('Analyze gaps'); if (ag) { ag.click(); }
        WebSocket.prototype.send = orig;
        window.__c.sent = sent.map(function (s) {
            try { return JSON.parse(s).type; } catch (e) { return s; }
        });

        var peer = new WebSocket('ws://localhost:%PORT%');
        peer.onopen = function () {
            peer.send(JSON.stringify({ type: 'consulting', mode: 'brief',
                text: '## Goals\\n\\n- Grow the team\\n\\n## Success Metrics\\n\\n- 20% faster', confirmed: true }));
            peer.send(JSON.stringify({ type: 'consulting', mode: 'gaps',
                text: '**Undefined metric** — faster means what?' }));
            peer.send(JSON.stringify({ type: 'consulting', mode: 'roadmap',
                text: '1. **Discovery** — close the open questions.' }));
        };
    }, 300);
    return 'started';
})()
""".replace("%PORT%", PORT)

# Step 2: read the rendered markdown + badges, confirm the roadmap button is now
# enabled, then drive the brief edit flow (double-click -> type -> wait out the
# 800 ms debounce -> Back). The edit drops the chip to Draft, so Confirm becomes
# clickable: click it and capture the message.
PROBE2 = """
(function () {
    var c = window.__c || {};
    c.briefMd = !!document.querySelector('.consulting-view .markdown-body');
    c.headings = Array.prototype.slice.call(
        document.querySelectorAll('.consulting-view .markdown-body h2'))
        .map(function (h) { return h.textContent.trim(); });
    c.badges = Array.prototype.slice.call(document.querySelectorAll('.consulting-view .consulting-badge'))
        .map(function (b) { return b.textContent.trim(); });

    function btn(text) {
        var all = Array.prototype.slice.call(document.querySelectorAll('.consulting-view button'));
        return all.filter(function (b) { return b.textContent.trim() === text; })[0] || null;
    }
    var rm = btn('Generate roadmap');
    c.roadmapEnabledAfterConfirm = rm ? !rm.disabled : null;
    var cf0 = btn('Confirm');
    c.confirmDisabledWhileConfirmed = cf0 ? cf0.disabled : null;

    window.__e = {};
    var editSent = [];
    var orig2 = WebSocket.prototype.send;
    WebSocket.prototype.send = function (d) { editSent.push(String(d)); return orig2.apply(this, arguments); };

    var body = document.querySelector('.consulting-section .consulting-text');
    window.__e.dblTarget = !!body;
    if (body) { body.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); }

    setTimeout(function () {
        var ta = document.querySelector('.consulting-view textarea.consulting-editor');
        window.__e.editorAppeared = !!ta;
        window.__e.editorValue = ta ? ta.value : '';
        if (ta) {
            ta.value = '## Goals\\n\\nEDITED brief';
            ta.dispatchEvent(new Event('input', { bubbles: true }));
        }
        setTimeout(function () {
            window.__e.sentTypes = editSent.map(function (s) {
                try { return JSON.parse(s).type; } catch (e) { return s; }
            });
            window.__e.sentTexts = editSent.map(function (s) {
                try { var o = JSON.parse(s); return o.type === 'consulting_save' ? o.text : null; }
                catch (e) { return null; }
            }).filter(Boolean);
            var back = btn('Back');
            if (back) { back.click(); }
            setTimeout(function () {
                window.__e.editorGone = !document.querySelector('.consulting-view textarea.consulting-editor');
                var st = document.querySelector('.consulting-section .consulting-text');
                window.__e.previewHasEdited = st ? st.textContent.indexOf('EDITED brief') >= 0 : false;
                // The edit cleared confirmation -> Confirm is now enabled.
                var cf = btn('Confirm');
                window.__e.confirmEnabledAfterEdit = cf ? !cf.disabled : null;
                var csent = [];
                WebSocket.prototype.send = function (d) { csent.push(String(d)); return orig2.apply(this, arguments); };
                if (cf) { cf.click(); }
                WebSocket.prototype.send = orig2;
                window.__e.confirmSent = csent.map(function (s) {
                    try { return JSON.parse(s).type; } catch (e) { return s; }
                });
            }, 250);
        }, 1000);
    }, 300);
    return JSON.stringify(c);
})()
"""

PROBE3 = "(function () { return JSON.stringify(window.__e || {}); })()"


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
    c = _parse("probe2")
    ed = _parse("probe3")

    print("[1] the Consulting tab renders three sections")
    check("the Consulting tab button exists", c.get("tabFound") is True)
    check("the consulting view is mounted", c.get("hasView") is True)
    check("three sections are present", c.get("sections") == 3, str(c.get("sections")))
    titles = " | ".join(c.get("titles") or [])
    check("Client brief section title", "Client brief" in titles, titles)
    check("Gap analysis section title", "Gap analysis" in titles, titles)
    check("Execution roadmap section title", "Execution roadmap" in titles, titles)

    print("\n[2] each button is present; the roadmap starts locked")
    check("Draft brief button", c.get("hasDraft") is True)
    check("Analyze gaps button", c.get("hasAnalyze") is True)
    check("Generate roadmap button", c.get("hasRoadmap") is True)
    check("Confirm button", c.get("hasConfirm") is True)
    check("roadmap disabled before confirmation", c.get("roadmapDisabled") is True,
          str(c.get("roadmapDisabled")))

    print("\n[3] clicking the buttons sends the control messages")
    check("'draft_brief' was sent", "draft_brief" in (c.get("sent") or []), str(c.get("sent")))
    check("'analyze_gaps' was sent", "analyze_gaps" in (c.get("sent") or []), str(c.get("sent")))

    print("\n[4] an incoming confirmed brief enables the roadmap + renders markdown")
    check("a markdown body rendered", c.get("briefMd") is True)
    check("gaps + roadmap h2 headings rendered",
          "Goals" in (c.get("headings") or []) and "Success Metrics" in (c.get("headings") or []),
          str(c.get("headings")))
    check("roadmap enabled after a confirmed brief", c.get("roadmapEnabledAfterConfirm") is True,
          str(c.get("roadmapEnabledAfterConfirm")))
    badges = [b for b in (c.get("badges") or [])]
    check("a Confirmed badge is shown", "Confirmed" in badges, str(badges))
    check("the reference badge reads 'Confirmed brief'", "Confirmed brief" in badges, str(badges))

    print("\n[5] Confirm is locked while confirmed, and sends once the brief is edited")
    check("Confirm is disabled while the brief is confirmed",
          c.get("confirmDisabledWhileConfirmed") is True, str(c.get("confirmDisabledWhileConfirmed")))
    check("Confirm is enabled after editing the brief",
          ed.get("confirmEnabledAfterEdit") is True, str(ed.get("confirmEnabledAfterEdit")))
    check("'confirm_brief' was sent",
          "confirm_brief" in (ed.get("confirmSent") or []), str(ed.get("confirmSent")))

    print("\n[6] a double-click opens the brief editor")
    check("the brief preview was a double-click target", ed.get("dblTarget") is True)
    check("the textarea appeared", ed.get("editorAppeared") is True)
    check("the editor was seeded with the brief",
          (ed.get("editorValue") or "").startswith("## Goals"), repr(ed.get("editorValue")))

    print("\n[7] typing auto-saves a consulting_save and Back returns to preview")
    check("a consulting_save frame was sent", "consulting_save" in (ed.get("sentTypes") or []),
          str(ed.get("sentTypes")))
    check("the saved text is the edit",
          any("EDITED brief" in t for t in (ed.get("sentTexts") or [])), str(ed.get("sentTexts")))
    check("the textarea is gone after Back", ed.get("editorGone") is True)
    check("the preview shows the edited text", ed.get("previewHasEdited") is True)

    print("\n[8] no JavaScript errors")
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
QTimer.singleShot(32000, report)

sys.exit(app.exec())
