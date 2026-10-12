"""Throwaway app-level hub smoke test (M0 acceptance, "hub starts/stops with the app").

Builds the real MainWindow on Qt's offscreen platform, with the hub's artefacts
redirected into a temp dir, and checks the whole lifecycle:

  * MainWindow brings the hub up and the app's HubClient handshakes,
  * publishing through ``w.hub`` lands in the hub's state (read back by an
    independent client, i.e. the hub really is the shared source of truth),
  * closing the app shuts the hub down again,
  * a hub the app did *not* start is left alone.

    venv/Scripts/python.exe _tmp_hub_app_smoke.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import os
import shutil
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

# The hub the app spawns inherits these, so nothing real is touched.
_TMP = tempfile.mkdtemp(prefix="hub-app-smoke-")
os.environ["HUB_EVENTS_PATH"] = os.path.join(_TMP, "hub-events.jsonl")
os.environ["HUB_SNAPSHOT_PATH"] = os.path.join(_TMP, "hub-state.json")

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.hub import protocol  # noqa: E402
from src.hub.client import HubClient  # noqa: E402
from src.hub.manager import is_hub_running  # noqa: E402
from src.ui import MainWindow  # noqa: E402

PASSED = []
FAILED = []

# State files the app rewrites on launch/close; put them back afterwards.
BACKUPS = {}
for _name in ("ui_state.json", os.path.join("sessions", "current.json")):
    _path = os.path.join(REPO_ROOT, _name)
    if os.path.exists(_path):
        with open(_path, "rb") as _f:
            BACKUPS[_path] = _f.read()


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def wait_for(predicate, timeout=8.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def restore_backups():
    for path, blob in BACKUPS.items():
        try:
            with open(path, "wb") as f:
                f.write(blob)
        except OSError as e:
            print(f"  (could not restore {path}: {e})")


def main() -> int:
    if is_hub_running():
        raise SystemExit(
            "a hub is already listening on 8770; stop it first (the app leaves a "
            "hub it did not start running, so this test cannot observe a shutdown)"
        )

    print(f"hub artefacts: {_TMP}")
    app = QApplication([])

    print("\n[app startup]")
    window = MainWindow()
    check("MainWindow starts the hub", wait_for(is_hub_running))
    check("the app's hub client handshakes", wait_for(lambda: window.hub_client.is_connected()))
    check("MainWindow exposes a publisher", window.hub is not None and window.hub.is_connected())

    observer = HubClient(role=protocol.ROLE_UI, name="app-smoke-observer")
    observer.start()
    check("an independent client can connect", wait_for(observer.is_connected))

    print("\n[publishing from the app]")
    window.hub.transcription_final("speaker", "app smoke line", endpoint=True)
    window.hub.translation_final("speaker", "baris uji")
    window.hub.session_config(auto_reply_enabled=False, purpose="language_learning")

    def session():
        response = observer.request(protocol.OP_SNAPSHOT, timeout=5.0) or {}
        return response.get("result", {}).get("session", {})

    check("transcription published by the app is in the hub",
          wait_for(lambda: any(t.get("text") == "app smoke line" for t in session().get("transcriptions") or [])),
          str(session().get("transcriptions")))
    check("translation published by the app is in the hub",
          any(t.get("text") == "baris uji" for t in session().get("translations") or []))
    check("conversation history is derived by the hub",
          [t.get("text") for t in session().get("conversation") or []] == ["app smoke line"])
    check("timestamp matches the session-store format",
          (session().get("transcriptions") or [{}])[0].get("timestamp", "").startswith("20"))

    def config():
        response = observer.request(protocol.OP_SNAPSHOT, timeout=5.0) or {}
        return response.get("result", {}).get("config", {})

    check("session.config from the app is stored",
          wait_for(lambda: config().get("purpose") == "language_learning"), str(config()))

    print("\n[shutdown]")
    observer.stop()
    window.close()
    check("closing the app stops the hub it started", wait_for(lambda: not is_hub_running()))
    check("the hub client is stopped", not window.hub_client.is_connected())

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        restore_backups()
        shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(code)
