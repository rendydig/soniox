"""Temp check: the Context pane's HTML/JS really renders and talks to the server.

Loads `http://localhost:<port>/context` in a real QWebEngineView and asserts the
Preact app built its DOM, connected over the WebSocket, and painted the selected
file's text into the editor — the one part `node --check` cannot cover, because
htm templates only fail at render time.

It points the Host context at a managed temp file first, so the check does not
depend on which file the machine happens to have selected, and then covers the
compacted *variant* UI: the Original/Compacted radio pair (mutually exclusive,
the editor follows the active one), the Compact button sending `compact_context`,
and an injected `context_state` frame (compacted available + stale) painting the
"out of date" badge and switching the radio.

Run a server first (any port): `cd websocket-server && PORT=8790 node server.js`
A window appears for a few seconds; there is no headless path because Qt
WebEngine cannot render on the offscreen platform here.
"""
import asyncio
import json
import os
import sys
import tempfile
import time

PORT = os.environ.get("CONTEXT_PANE_PORT", "8790")
URI = f"ws://localhost:{PORT}"

# Long enough to clear CONTEXT_COMPACT_MIN_CHARS (400) so the button enables.
BODY = ("Helpy is a conversation copilot for consultants. " * 12).strip()
COMPACTED = "Helpy: a conversation copilot for consultants."

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


async def ws_call(payload, expect="context_state", timeout=5.0):
    """One request/response round-trip against the context protocol."""
    import websockets

    async with websockets.connect(URI) as ws:
        await ws.send(json.dumps(payload))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                return None
            message = json.loads(raw)
            if message.get("type") == expect:
                return message
        return None


# --- phase A: point the Host context at a managed temp file ----------------
workdir = tempfile.mkdtemp(prefix="context-pane-")
target = os.path.join(workdir, "host.md")
compacted = target + ".compacted"
before = asyncio.run(ws_call({"type": "context_get"}))
seed = before["selection"]["host"] if before else None
created = asyncio.run(ws_call({"type": "context_new", "role": "host", "path": target}))
saved = asyncio.run(ws_call({"type": "context_save", "role": "host", "path": target, "text": BODY}))
if not created or not saved or saved["selection"]["host"] != target:
    print("FAIL  could not select the temp file", created)
    sys.exit(1)
print(f"[setup] host context -> {target} (was {seed!r})")


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        console.append(f"{level.name}: {message}")


app = QApplication(sys.argv)
view = QWebEngineView()
page = Page(view)
view.setPage(page)
view.resize(460, 560)
view.show()


def collect(key):
    def _cb(value):
        results[key] = value
    return _cb


# --- probe 1: the DOM, the variant row, and what a click sends -------------
PROBE_ONE = """
(function () {
    var out = { ok: true, sent: [] };
    try {
        out.root_len = document.getElementById('context-root')
            ? document.getElementById('context-root').innerHTML.length : -1;
        out.tabs = Array.prototype.slice.call(document.querySelectorAll('.bullet-tab'))
            .map(function (b) { return b.textContent.trim(); }).join('|');
        var buttons = Array.prototype.slice.call(document.querySelectorAll('button'))
            .map(function (b) { return b.textContent.trim(); });
        out.buttons = buttons.join('|');
        out.selected = (document.querySelector('.context-select') || {}).value || '';
        var ta = document.querySelector('.context-textarea');
        out.text = ta ? ta.value : '';
        out.disabled = ta ? ta.disabled : null;
        out.hint = (document.querySelector('.context-hint') || {}).textContent || '';
        out.chips = document.querySelectorAll('.context-chip').length;
        var radios = Array.prototype.slice.call(document.querySelectorAll('.context-radio'));
        out.radios = radios.map(function (r) { return r.textContent.trim(); }).join('|');
        var inputs = Array.prototype.slice.call(document.querySelectorAll('.context-radio input'));
        out.radio_checked = inputs.map(function (i) { return i.checked; }).join('|');
        out.radio_disabled = inputs.map(function (i) { return i.disabled; }).join('|');
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data) {
            out.sent.push(String(data));
            return orig.apply(this, arguments);
        };
        var compact = buttons.indexOf('Compact');
        var compactBtn = Array.prototype.slice.call(document.querySelectorAll('button'))
            .filter(function (b) { return b.textContent.trim() === 'Compact'; })[0];
        if (compactBtn) compactBtn.click();
        WebSocket.prototype.send = orig;
    } catch (e) { out.ok = false; out.error = String(e); }
    return JSON.stringify(out);
})()
"""


def probe_one():
    page.runJavaScript(PROBE_ONE, collect("one"))
    QTimer.singleShot(600, report_one)


def report_one():
    one = json.loads(results.get("one") or "{}")
    print("[1] the page renders")
    check("probe ran", one.get("ok") is True, str(one.get("error", "")))
    check("root has content", (one.get("root_len") or 0) > 200, str(one.get("root_len")))
    check("Host/Speaker tabs", one.get("tabs") == "Host|Speaker", str(one.get("tabs")))
    buttons = (one.get("buttons") or "").split("|")
    check("Browse… / New… / Save / Compact buttons",
          all(b in buttons for b in ("Browse…", "New…", "Save", "Compact")), str(buttons))
    check("pane controls", all(b in buttons for b in ("⇤", "⇥", "−")))

    print("\n[2] the state came over the WebSocket and painted")
    check("a file is selected", one.get("selected") == target, str(one.get("selected")))
    check("editor holds the file text", (one.get("text") or "").strip() == BODY,
          f"screen={len(one.get('text') or '')} disk={len(BODY)}")
    check("editor is editable", one.get("disabled") is False)
    check("footer names the original variant",
          "using the original" in (one.get("hint") or ""), (one.get("hint") or "")[:70])

    print("\n[3] the variant row (Original / Compacted)")
    check("two radios", one.get("radios") == "Original|Compacted", str(one.get("radios")))
    check("Original is checked", one.get("radio_checked") == "true|false",
          str(one.get("radio_checked")))
    check("Compacted is disabled with no compacted file",
          one.get("radio_disabled") == "false|true", str(one.get("radio_disabled")))

    print("\n[4] the Compact button sends the real file's text")
    sent = [json.loads(entry) for entry in (one.get("sent") or [])]
    compact_msgs = [m for m in sent if m.get("type") == "compact_context"]
    check("compact_context sent", bool(compact_msgs), str(sent))
    if compact_msgs:
        msg = compact_msgs[0]
        check("carries the role", msg.get("role") == "host", str(msg.get("role")))
        check("carries the real file's path", msg.get("path") == target, str(msg.get("path")))
        check("carries the real file's text", msg.get("text") == BODY,
              str(len(msg.get("text") or "")))
    else:
        check("carries the role", False)
        check("carries the real file's path", False)
        check("carries the real file's text", False)

    QTimer.singleShot(200, inject_state)


# --- probe 2: an injected compacted+stale frame drives the radio + badge ---
INJECT = """
(function () {
    var frame = {
        type: 'context_state',
        selection: { host: %HOST%, speaker: null },
        problems: { host: null, speaker: null },
        history: { host: [%HOST%], speaker: [] },
        contents: { host: %BODY%, speaker: '' },
        revision: { host: 111, speaker: 0 },
        compacted_path: { host: %COMPACTED_PATH%, speaker: null },
        compacted_contents: { host: %COMPACTED%, speaker: '' },
        compacted_problem: { host: null, speaker: null },
        compacted_revision: { host: 222, speaker: 0 },
        compacted_available: { host: true, speaker: false },
        compacted_stale: { host: true, speaker: false },
        variant: { host: 'compacted', speaker: 'full' },
        active: { host: 'compacted', speaker: 'full' },
        effective: { host: %COMPACTED%, speaker: '' }
    };
    var peer = new WebSocket('ws://localhost:%PORT%');
    peer.onopen = function () { peer.send(JSON.stringify(frame)); };
    return 'sent';
})()
"""


def inject_state():
    script = (INJECT
              .replace("%HOST%", json.dumps(target))
              .replace("%COMPACTED_PATH%", json.dumps(compacted))
              .replace("%BODY%", json.dumps(BODY))
              .replace("%COMPACTED%", json.dumps(COMPACTED))
              .replace("%PORT%", str(PORT)))
    page.runJavaScript(script, collect("inject"))
    QTimer.singleShot(900, probe_two)


PROBE_TWO = """
(function () {
    var out = { ok: true, sent: [] };
    try {
        var ta = document.querySelector('.context-textarea');
        out.text = ta ? ta.value : '';
        var inputs = Array.prototype.slice.call(document.querySelectorAll('.context-radio input'));
        out.radio_checked = inputs.map(function (i) { return i.checked; }).join('|');
        out.radio_disabled = inputs.map(function (i) { return i.disabled; }).join('|');
        out.badges = Array.prototype.slice.call(document.querySelectorAll('.context-badge'))
            .map(function (b) { return b.textContent.trim(); }).join('|');
        out.hint = (document.querySelector('.context-hint') || {}).textContent || '';
        var orig = WebSocket.prototype.send;
        WebSocket.prototype.send = function (data) {
            out.sent.push(String(data));
            return orig.apply(this, arguments);
        };
        // Click "Original" (currently unchecked, since the frame made the
        // compacted copy active): the editor follows it and a control message
        // goes out.
        if (inputs.length > 0) inputs[0].click();
        WebSocket.prototype.send = orig;
    } catch (e) { out.ok = false; out.error = String(e); }
    return JSON.stringify(out);
})()
"""


def probe_two():
    page.runJavaScript(PROBE_TWO, collect("two"))
    QTimer.singleShot(500, report_two)


def report_two():
    two = json.loads(results.get("two") or "{}")
    print("\n[5] a compacted + stale frame paints the variant UI")
    check("probe ran", two.get("ok") is True, str(two.get("error", "")))
    check("editor switched to the compacted text", two.get("text") == COMPACTED,
          repr(two.get("text"))[:50])
    check("Compacted is now checked", two.get("radio_checked") == "false|true",
          str(two.get("radio_checked")))
    check("Compacted is enabled", two.get("radio_disabled") == "false|false",
          str(two.get("radio_disabled")))
    check("stale badge shown", "out of date" in (two.get("badges") or ""),
          str(two.get("badges")))
    check("footer names the compacted copy",
          "using the compacted copy" in (two.get("hint") or ""), (two.get("hint") or "")[:70])
    sent = [json.loads(entry) for entry in (two.get("sent") or [])]
    variant_msgs = [m for m in sent if m.get("type") == "context_set_variant"]
    check("clicking Original sends context_set_variant", bool(variant_msgs), str(sent))
    if variant_msgs:
        check("variant message shape",
              variant_msgs[0].get("role") == "host" and variant_msgs[0].get("variant") == "full",
              str(variant_msgs[0]))
    else:
        check("variant message shape", False)

    print("\n[6] no JavaScript errors")
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
    QTimer.singleShot(1800, probe_one)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/context"))
QTimer.singleShot(30000, lambda: (print("TIMEOUT"), app.exit(1)))

exit_code = app.exec()

# --- cleanup: restore the selection and remove the temp files --------------
asyncio.run(ws_call({"type": "context_clear_selection", "role": "host"}))
if seed:
    asyncio.run(ws_call({"type": "context_select", "role": "host", "path": seed}))
asyncio.run(ws_call({"type": "context_forget", "role": "host", "path": target}))
for path in (target, compacted):
    try:
        os.unlink(path)
    except OSError:
        pass
try:
    os.rmdir(workdir)
except OSError:
    pass
final = asyncio.run(ws_call({"type": "context_get"}))
check("selection restored", final and final["selection"]["host"] == seed,
      str(final["selection"]["host"]) if final else "no state")
check("temp files gone", not os.path.exists(target) and not os.path.exists(compacted))

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else exit_code)
