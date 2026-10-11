"""Long-run transcription stress test — real audio, fake Soniox, no AI.

Drives the real app end to end (real microphone/loopback capture through the
real ``SonioxWorker`` and the real editor/session/webview/Node pipeline) but
points it at a **local fake Soniox WebSocket** instead of the real API, and
forces the AI off. Use it to see whether a long recording grows memory / threads
/ webview heap or crashes.

    # 10 minutes, full app (webviews + Node server), default devices
    venv/Scripts/python.exe _tmp_long_transcription_test.py --minutes 10

    # same, but without the browser panes / Node server (isolates Python+audio)
    venv/Scripts/python.exe _tmp_long_transcription_test.py --minutes 10 --mode pipeline

    # 2 hours
    venv/Scripts/python.exe _tmp_long_transcription_test.py --minutes 120

Speak into the selected Host device for the run (or play a clip routed to the
loopback Speaker device). Samples land in ``logs/health.log``; a native crash
leaves a stack in ``logs/faulthandler.log``.

This is a throwaway dev script (``_tmp_`` prefix), not shipped code.
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time

# --- fake Soniox content ----------------------------------------------------
# Canned transcript emitted at a speech-like cadence; independent of the audio
# bytes (the worker just forwards whatever the server sends).
WORDS = (
    "so", "you", "know", "the", "thing", "about", "that", "is", "it", "really",
    "works", "when", "we", "talk", "for", "a", "while", "and", "keep", "going",
)
SENTENCES = (
    "So the thing about a long recording is that it just keeps going.",
    "You start talking and the transcript grows line by line.",
    "Every utterance becomes a final sentence with a timestamp.",
    "The pipeline trims old lines but the session keeps the recent ones.",
    "Let me keep speaking so we can watch the memory over time.",
    "This is exactly what a two hour session would look like.",
    "The editor, the history and the session store all stay busy.",
    "And the webviews repaint on every partial update.",
)

_PARTIAL_EVERY_S = 0.6
_FINAL_EVERY_S = 3.5
_END_EVERY_N_FINALS = 4


class FakeSonioxServer:
    """A local stand-in for Soniox' realtime WebSocket.

    Accepts the session-config frame the worker sends first, then consumes the
    binary PCM frames while emitting canned partial/final tokens (occasionally a
    ``<end>`` marker) at a speech-like pace.
    """

    def __init__(self, port: int):
        self.port = port
        self._thread = None
        self.bytes_received = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, name="fake-soniox", daemon=True)
        self._thread.start()

    def _run(self):
        from websockets.asyncio.server import serve

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def main():
            async with serve(self._handler, "localhost", self.port):
                print(f"[fake-soniox] listening on ws://localhost:{self.port}", flush=True)
                await asyncio.Future()  # run forever

        loop.run_until_complete(main())

    async def _drain(self, ws):
        try:
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    self.bytes_received += len(msg)
        except Exception:
            pass

    async def _handler(self, ws):
        try:
            await ws.recv()  # session config JSON
        except Exception:
            return

        loop = asyncio.get_event_loop()
        drain = asyncio.create_task(self._drain(ws))
        t_partial = 0.0
        t_final = 0.0
        words = []
        idx = 0
        try:
            while not drain.done():
                now = loop.time()
                if now - t_partial >= _PARTIAL_EVERY_S:
                    t_partial = now
                    word = WORDS[(idx + len(words)) % len(WORDS)]
                    words.append(word)
                    await ws.send(json.dumps(
                        {"tokens": [{"text": word + " ", "is_final": False}]}))
                if now - t_final >= _FINAL_EVERY_S:
                    t_final = now
                    tokens = [{"text": SENTENCES[idx % len(SENTENCES)] + " ", "is_final": True}]
                    idx += 1
                    if idx % _END_EVERY_N_FINALS == 0:
                        tokens.append({"text": "<end>", "is_final": True})
                    await ws.send(json.dumps({"tokens": tokens}))
                    words = []
                await asyncio.sleep(0.1)
        except Exception:
            pass
        finally:
            drain.cancel()


def _wait_for_port(port: int, timeout: float = 5.0) -> bool:
    """Wait until the fake server accepts a real WebSocket handshake.

    A raw TCP probe would make the server log an 'opening handshake failed'
    error (it tries to parse the connection as HTTP), so handshake properly.
    """
    from websockets.asyncio.client import connect

    async def probe():
        async with connect(f"ws://localhost:{port}", open_timeout=0.5):
            return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            asyncio.run(probe())
            return True
        except Exception:
            time.sleep(0.1)
    return False


def _install_stubs(ui_module, mode: str):
    """Replace the parts of ``src.ui`` that need a browser/server for `pipeline`."""
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QStackedWidget, QTextEdit

    class StubPane(QObject):
        state_changed = Signal()
        geometry_changed = Signal()

        def __init__(self, edge=None, width=None, height=None, x=None, y=None,
                     docked=None, **kwargs):
            super().__init__()
            self._edge = edge or "right"
            self._docked = True if docked is None else docked
            self._width = width or 320
            self._height = height or 400
            self._x = x or 0
            self._y = y or 0

        def apply_always_on_top(self, enabled): pass
        def apply_screen_protection(self, enabled): pass
        def _apply_geometry(self): pass
        def show(self): pass
        def hide(self): pass
        def showNormal(self): pass
        def raise_(self): pass
        def close(self): pass
        def set_edge(self, edge): self._edge = edge
        def set_width(self, width): self._width = width
        def set_height(self, height): self._height = height
        def move_to(self, x, y): self._x, self._y = x, y
        def get_edge(self): return self._edge
        def is_docked(self): return self._docked
        def get_width(self): return self._width
        def get_height(self): return self._height
        def get_x(self): return self._x
        def get_y(self): return self._y

    class StubLiveWindow(StubPane):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self._editor = QTextEdit()
            self._editor.setUndoRedoEnabled(False)
            self._stack = QStackedWidget()
            self._stack.addWidget(self._editor)

        def get_transcription_editor(self):
            return self._editor

        def get_view_stack(self):
            return self._stack

    class StubServerManager:
        def ensure_running(self, *a, **k): return False
        def stop(self): pass

    class StubWebSocketClient:
        def __init__(self, uri=None): self.uri = uri
        def set_message_handler(self, handler): pass
        def start(self): pass
        def stop(self): pass
        def is_connected(self): return False
        def send_transcription(self, *a, **k): pass
        def send_message(self, *a, **k): pass

    class StubHotkeys:
        def __init__(self, **kwargs): pass
        def register(self): pass
        def unregister(self): pass

    ui_module.GlobalHotkeys = StubHotkeys
    if mode == "pipeline":
        ui_module.WebSocketServerManager = StubServerManager
        ui_module.WebSocketClient = StubWebSocketClient
        ui_module.GeminiWindow = StubPane
        ui_module.LiveWindow = StubLiveWindow
        ui_module.BulletPointsWindow = StubPane


def _health_log_path():
    root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(root, "logs", "health.log")


def _read_new_lines(path, start_count):
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return lines[start_count:]


def main():
    parser = argparse.ArgumentParser(description="Long-run transcription stress test")
    parser.add_argument("--minutes", type=float, default=10.0, help="run length (default 10)")
    parser.add_argument("--mode", choices=("full", "pipeline"), default="full",
                        help="full = webviews + Node server; pipeline = Python+audio only")
    parser.add_argument("--port", type=int, default=9999, help="fake Soniox port")
    parser.add_argument("--host", type=int, default=None, help="host input device index override")
    parser.add_argument("--speaker-index", type=int, default=None,
                        help="loopback device index override (default: combo default)")
    parser.add_argument("--no-speaker", action="store_true", help="run host-only (no loopback)")
    args = parser.parse_args()

    # Point the app at the fake Soniox BEFORE src.config is imported.
    os.environ["SONIOX_WS_URL"] = f"ws://localhost:{args.port}"

    server = FakeSonioxServer(args.port)
    server.start()
    if not _wait_for_port(args.port):
        print(f"[harness] fake Soniox did not start on port {args.port}", file=sys.stderr)
        return 1

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from src.logging_setup import setup_logging

    # Redirect the session store so the real sessions/current.json is untouched.
    import src.session_store as session_store_module
    tmp_sessions = tempfile.mkdtemp(prefix="soniox-test-sessions-")
    session_store_module.SESSION_DIR = tmp_sessions

    # Back up ui_state.json (MainWindow rewrites it on geometry/settings changes).
    root = os.path.dirname(os.path.abspath(__file__))
    state_path = os.path.join(root, "ui_state.json")
    state_backup = state_path + ".stress-backup"
    if os.path.exists(state_path):
        shutil.copy2(state_path, state_backup)

    import src.ui as ui_module
    _install_stubs(ui_module, args.mode)

    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    app = QApplication(sys.argv)
    win = ui_module.MainWindow()

    # Force every AI path off (ui_state may have bullet auto on).
    win._auto_reply_enabled = False
    win._last_pickup_auto_enabled = False
    win.bullet_points_controller.set_auto(False)
    win.last_pickup_controller.set_auto(False)

    win.show()

    host_id = args.host if args.host is not None else win.device_combo.currentData()
    speaker = None
    if not args.no_speaker:
        if args.speaker_index is not None:
            for i in range(win.speaker_combo.count()):
                item = win.speaker_combo.itemData(i)
                if isinstance(item, dict) and item.get("index") == args.speaker_index:
                    speaker = item
                    break
            if speaker is None:
                print(f"[harness] speaker index {args.speaker_index} not in the Speaker list",
                      file=sys.stderr)
        else:
            speaker = win.speaker_combo.currentData()
    if speaker == host_id:
        speaker = None
    print(f"[harness] mode={args.mode} minutes={args.minutes} "
          f"host={host_id} speaker={speaker}", flush=True)
    if host_id is None:
        print("[harness] no host input device available — cannot start capture",
              file=sys.stderr)

    health_path = _health_log_path()
    try:
        with open(health_path, "r", encoding="utf-8") as f:
            start_count = len(f.readlines())
    except OSError:
        start_count = 0

    started = time.time()
    interrupted = {"flag": False}

    def _on_sigint(_sig, _frame):
        interrupted["flag"] = True

    signal.signal(signal.SIGINT, _on_sigint)

    if host_id is not None:
        win.transcription_controller.start_session(
            host_id, speaker, mode="transcription", target_lang=None)

    def _tick():
        if interrupted["flag"]:
            print("[harness] interrupted", flush=True)
            app.quit()
            return
        try:
            import psutil
            rss = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except Exception:
            rss = -1.0
        blocks = win.transcription_editor.document().blockCount()
        print("[harness] t=%4ds rss=%.1fMB threads=%d blocks=%d"
              % (time.time() - started, rss, threading.active_count(), blocks), flush=True)

    tick_timer = QTimer()
    tick_timer.timeout.connect(_tick)
    tick_timer.start(30000)

    def _finish():
        try:
            win.transcription_controller.stop_session()
            win.close()
        except Exception:
            pass
        app.quit()

    QTimer.singleShot(int(args.minutes * 60 * 1000), _finish)

    app.exec()

    # --- report -----------------------------------------------------------
    print("\n[harness] ===== summary =====")
    print("[harness] elapsed: %.1f min" % ((time.time() - started) / 60.0))
    print("[harness] audio bytes received by fake Soniox: %d" % server.bytes_received)
    samples = [ln.strip() for ln in _read_new_lines(health_path, start_count) if ln.strip()]
    if samples:
        print("[harness] health samples (%d):" % len(samples))
        print("[harness]   first: " + samples[0])
        print("[harness]   last:  " + samples[-1])
    else:
        print("[harness] no health samples written (did the app start?)")
    print("[harness] session dir (temp): " + tmp_sessions)
    print("[harness] crash log: " + os.path.join(root, "logs", "faulthandler.log"))

    # Restore ui_state.json.
    if os.path.exists(state_backup):
        try:
            shutil.move(state_backup, state_path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
