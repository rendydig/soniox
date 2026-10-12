"""Temp check: typing in the Context pane autosaves (debounced) to the file.

The whole loop, with no Python-side store involved:

  1. (WS) select a temp file as the Host context
  2. (pane) type into the textarea -> the debounce timer starts
  3. the file on disk must still be empty right after typing (proves debounce)
  4. after the debounce, the file must hold exactly the typed text and the pane
     must show "Saved"
  5. (WS) restore the original selection and delete the temp file

Run a server first: `cd websocket-server && PORT=8790 node server.js`
"""
import asyncio
import json
import os
import sys
import tempfile
import time

PORT = os.environ.get("CONTEXT_PANE_PORT", "8790")
URI = f"ws://localhost:{PORT}"

TYPED = "line one\nline two **bold**"

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


async def ws_call(payload, expect="context_state", timeout=4.0):
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


# --- phase A: point the Host context at a temp file ------------------------
workdir = tempfile.mkdtemp(prefix="context-autosave-")
target = os.path.join(workdir, "host.md")
state = asyncio.run(ws_call({"type": "context_get"}))
seed = state["selection"]["host"] if state else None
created = asyncio.run(ws_call({"type": "context_new", "role": "host", "path": target}))
if not created or created["selection"]["host"] != target:
    print("FAIL  could not select the temp file", created)
    sys.exit(1)
print(f"[setup] host context -> {target} (was {seed!r})")

# --- phase B: type in the pane --------------------------------------------
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

console = []
results = {}


class Page(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line, source):
        console.append(f"{level.name}: {message}")


app = QApplication(sys.argv)
view = QWebEngineView()
page = Page(view)
view.setPage(page)
view.resize(460, 520)
view.show()


def read_file():
    try:
        with open(target, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return "<missing>"


def type_text():
    script = """
    (() => {
      const ta = document.querySelector('.context-textarea');
      if (!ta) return 'no textarea';
      ta.value = %s;
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      return 'typed';
    })()
    """ % json.dumps(TYPED)
    page.runJavaScript(script, lambda value: results.update(typed=value))
    # Right after typing the debounce must still be pending: nothing on disk.
    QTimer.singleShot(300, check_not_yet_saved)


def check_not_yet_saved():
    check("nothing written during the debounce window", read_file() == "",
          repr(read_file()[:30]))
    QTimer.singleShot(2000, check_saved)


def check_saved():
    check("typed text reached the file", read_file() == TYPED, repr(read_file()[:40]))
    page.runJavaScript("(document.querySelector('.context-save-status') || {}).textContent || ''",
                       lambda value: results.update(status=value))
    page.runJavaScript("document.querySelector('.context-textarea').value",
                       lambda value: results.update(text=value))
    QTimer.singleShot(800, report)


def report():
    check("the pane typed", results.get("typed") == "typed", str(results.get("typed")))
    check("editor kept the text", results.get("text") == TYPED, repr(results.get("text"))[:40])
    status = results.get("status") or ""
    check("status shows Saved", status.startswith("Saved"), status)
    errors = [line for line in console if "Error" in line]
    check("no JavaScript errors", not errors, "; ".join(errors[:3]))
    app.exit(1 if failures else 0)


def on_load(ok):
    if not ok:
        check("pane loaded", False)
        app.exit(1)
        return
    QTimer.singleShot(2000, type_text)


view.loadFinished.connect(on_load)
view.setUrl(QUrl(f"http://localhost:{PORT}/context"))
QTimer.singleShot(30000, report)

exit_code = app.exec()

# --- phase C: clean up ----------------------------------------------------
asyncio.run(ws_call({"type": "context_clear_selection", "role": "host"}))
if seed:
    asyncio.run(ws_call({"type": "context_select", "role": "host", "path": seed}))
asyncio.run(ws_call({"type": "context_forget", "role": "host", "path": target}))
try:
    os.unlink(target)
except OSError:
    pass
os.rmdir(workdir) if os.path.isdir(workdir) else None
final = asyncio.run(ws_call({"type": "context_get"}))
check("selection restored", final and final["selection"]["host"] == seed, str(final["selection"]["host"]))
check("temp file gone", not os.path.exists(target))

print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
sys.exit(1 if failures else exit_code)
