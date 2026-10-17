"""Temp check: the Bullet Points pane really renders and its buttons work.

Loads `http://localhost:<port>/bullets` in a real QWebEngineView and asserts the
Preact app built its DOM, that the bullets tab shows both action buttons inside
`.bullet-header-actions`, and that clicking them sends the right control messages
over the WebSocket (`trigger_bullet_points` / `regenerate_bullet_points`) — the
part `node --check` cannot cover, because htm templates only fail at render time.
It then pushes a `bullet_points` frame (with a locked item) from a second WS
client and asserts a padlock per bullet and that clicking one sends
`set_bullet_lock`.

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

# Push a bullet_points frame (one locked) from a second client, then inspect the
# rendered lock buttons and click the first (spying on send).
LOCK_SCRIPT = """
(function () {
    window.__lock = { ok: true };
    var peer = new WebSocket('ws://localhost:%PORT%');
    peer.onopen = function () {
        peer.send(JSON.stringify({
            type: 'bullet_points',
            items: ['alpha point', 'beta point', 'gamma point'],
            speaker: {},
            windows: [],
            locks: [false, true, false]
        }));
    };
    setTimeout(function () {
        try {
            var locks = Array.prototype.slice.call(
                document.querySelectorAll('.bullet-item .bullet-lock'));
            window.__lock.count = locks.length;
            window.__lock.lockedNumbers = Array.prototype.slice.call(
                document.querySelectorAll('.bullet-item.locked')).map(function (li) {
                    var n = li.querySelector('.bullet-number');
                    return n ? n.textContent.trim() : '';
                });
            window.__lock.aria = locks.map(function (b) { return b.getAttribute('aria-pressed'); });
            var sent = [];
            var orig = WebSocket.prototype.send;
            WebSocket.prototype.send = function (d) { sent.push(String(d)); return orig.apply(this, arguments); };
            if (locks[0]) { locks[0].click(); }
            WebSocket.prototype.send = orig;
            window.__lock.sent = sent.map(function (s) {
                try { return JSON.parse(s); } catch (e) { return s; }
            });
        } catch (e) {
            window.__lock.ok = false;
            window.__lock.error = String(e);
        }
    }, 700);
    return 'started';
})()
""".replace("%PORT%", PORT)

# Push a profile frame, open the Speaker tab, then click one padlock per shape
# (an identity row and a list item) and capture what each sends.
SPEAKER_SCRIPT = """
(function () {
    window.__spk = { ok: true };
    var peer = new WebSocket('ws://localhost:%PORT%');
    peer.onopen = function () {
        peer.send(JSON.stringify({
            type: 'bullet_points',
            items: [],
            speaker: { name: 'Maya', location: 'Jakarta', occupation: 'Head of Ops',
                       interests: ['coffee', 'running'], goals: ['cut onboarding time'],
                       pain_points: ['briefs get lost'], facts: ['12-person team'] },
            windows: [],
            locks: [],
            speaker_locks: { name: true, location: false, occupation: false,
                             interests: [false, true], goals: [], pain_points: [],
                             facts: [] }
        }));
    };
    setTimeout(function () {
        try {
            var tabs = Array.prototype.slice.call(document.querySelectorAll('.bullet-tab'));
            var speakerTab = tabs.filter(function (t) {
                return t.textContent.trim() === 'Speaker Profile';
            })[0];
            if (speakerTab) { speakerTab.click(); }
            setTimeout(function () {
                window.__spk.rows = document.querySelectorAll('.kyc-row').length;
                window.__spk.rowLocks = document.querySelectorAll('.kyc-row .bullet-lock').length;
                window.__spk.itemLocks = document.querySelectorAll('.kyc-item .bullet-lock').length;
                window.__spk.lockedItems = document.querySelectorAll('.kyc-item.locked').length;
                window.__spk.aria = Array.prototype.slice.call(
                    document.querySelectorAll('.kyc-row .bullet-lock'))
                    .map(function (b) { return b.getAttribute('aria-pressed'); });
                var sent = [];
                var orig = WebSocket.prototype.send;
                WebSocket.prototype.send = function (d) { sent.push(String(d)); return orig.apply(this, arguments); };
                var rowLock = document.querySelectorAll('.kyc-row .bullet-lock')[1];
                if (rowLock) { rowLock.click(); }
                var itemLock = document.querySelectorAll('.kyc-item .bullet-lock')[1];
                if (itemLock) { itemLock.click(); }
                WebSocket.prototype.send = orig;
                window.__spk.sent = sent.map(function (s) {
                    try { return JSON.parse(s); } catch (e) { return s; }
                });
            }, 500);
        } catch (e) {
            window.__spk.ok = false;
            window.__spk.error = String(e);
        }
    }, 300);
    return 'started';
})()
""".replace("%PORT%", PORT)


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


def probe():
    page.runJavaScript(PROBE_SCRIPT, collect("probe"))
    QTimer.singleShot(1500, probe_lock)


def probe_lock():
    page.runJavaScript(LOCK_SCRIPT, collect("lock_started"))
    QTimer.singleShot(2200, probe_read_lock)


def probe_read_lock():
    page.runJavaScript(
        "(function () { return JSON.stringify(window.__lock || {}); })()",
        collect("lock"),
    )
    QTimer.singleShot(400, probe_speaker)


def probe_speaker():
    page.runJavaScript(SPEAKER_SCRIPT, collect("speaker_started"))
    QTimer.singleShot(2400, probe_read_speaker)


def probe_read_speaker():
    page.runJavaScript(
        "(function () { return JSON.stringify(window.__spk || {}); })()",
        collect("speaker"),
    )
    QTimer.singleShot(400, report)


def report():
    probe_result = _parse("probe")
    lock_result = _parse("lock")
    print("[1] the page renders")
    check("the DOM probe returned data", bool(probe_result), str(results.get("probe"))[:120])
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

    print("\n[4] each bullet renders a lock toggle")
    check("the lock probe ran", lock_result.get("ok") is True, str(lock_result.get("error")))
    check("one padlock per bullet", lock_result.get("count") == 3, str(lock_result.get("count")))
    check("the locked item carries the .locked tint",
          lock_result.get("lockedNumbers") == ["2."], str(lock_result.get("lockedNumbers")))
    check("aria-pressed reflects the flags",
          lock_result.get("aria") == ["false", "true", "false"], str(lock_result.get("aria")))

    print("\n[5] clicking a padlock sends set_bullet_lock")
    lock_sent = [m for m in (lock_result.get("sent") or []) if isinstance(m, dict)]
    toggle = [m for m in lock_sent if m.get("type") == "set_bullet_lock"]
    check("a set_bullet_lock frame was sent", len(toggle) == 1, str(lock_result.get("sent")))
    check("it targets the clicked item with its text",
          bool(toggle) and toggle[0].get("index") == 0
          and toggle[0].get("text") == "alpha point"
          and toggle[0].get("locked") is True,
          str(toggle))

    print("\n[6] the Speaker tab renders a padlock per profile value")
    spk = _parse("speaker")
    check("the speaker probe ran", spk.get("ok") is True, str(spk.get("error")))
    check("identity rows rendered", spk.get("rows") == 3, str(spk.get("rows")))
    check("one padlock per identity row", spk.get("rowLocks") == 3, str(spk.get("rowLocks")))
    check("one padlock per list item", spk.get("itemLocks") == 5, str(spk.get("itemLocks")))
    check("a locked list item carries the .locked tint",
          spk.get("lockedItems") == 1, str(spk.get("lockedItems")))
    check("aria-pressed reflects the scalar flags",
          spk.get("aria") == ["true", "false", "false"], str(spk.get("aria")))

    print("\n[7] clicking a speaker padlock sends set_speaker_lock")
    spk_sent = [m for m in (spk.get("sent") or []) if isinstance(m, dict)]
    spk_toggle = [m for m in spk_sent if m.get("type") == "set_speaker_lock"]
    check("two set_speaker_lock frames were sent", len(spk_toggle) == 2, str(spk.get("sent")))
    check("the scalar one carries the field and the new value",
          bool(spk_toggle) and spk_toggle[0].get("field") == "location"
          and spk_toggle[0].get("locked") is True,
          str(spk_toggle[0] if spk_toggle else None))
    check("the list one carries the field, index, item and the unlocked value",
          len(spk_toggle) > 1 and spk_toggle[1].get("field") == "interests"
          and spk_toggle[1].get("index") == 1
          and spk_toggle[1].get("item") == "running"
          and spk_toggle[1].get("locked") is False,
          str(spk_toggle[1] if len(spk_toggle) > 1 else None))

    print("\n[8] no JavaScript errors")
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
