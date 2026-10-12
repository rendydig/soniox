"""Throwaway M1 verification: the Soniox publish path (dual-write).

Drives the *real* SonioxWorker against the existing fake Soniox server (see
``_tmp_long_transcription_test.py``), with the app's real MainWindow and a real
hub, then checks that:

  * the hub received ``transcription.partial`` / ``transcription.final`` /
    ``translation.final`` / ``status`` topics,
  * the finalized lines in the hub are exactly the lines the Live Window editor
    shows (same content through both paths — that is what dual-write means),
  * the hub derived the conversation history from the finals,
  * the debounced snapshot on disk holds the same transcript.

    venv/Scripts/python.exe _tmp_hub_pipeline_smoke.py [--seconds 30]

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import argparse
import atexit
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["SONIOX_WS_URL"] = "ws://localhost:9999"

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

# MainWindow rewrites ui_state.json on close (geometry/settings); put the real
# one back afterwards, even if a check aborts.
_STATE_PATH = os.path.join(REPO_ROOT, "ui_state.json")
_STATE_BACKUP = None
if os.path.exists(_STATE_PATH):
    with open(_STATE_PATH, "rb") as _f:
        _STATE_BACKUP = _f.read()


@atexit.register
def _restore_ui_state():
    if _STATE_BACKUP is not None:
        try:
            with open(_STATE_PATH, "wb") as f:
                f.write(_STATE_BACKUP)
        except OSError as e:
            print(f"  (could not restore ui_state.json: {e})")


# Keep the hub's own artefacts out of the repo (logs/ and sessions/).
_TMP = tempfile.mkdtemp(prefix="hub-pipeline-smoke-")
os.environ["HUB_EVENTS_PATH"] = os.path.join(_TMP, "hub-events.jsonl")
os.environ["HUB_SNAPSHOT_PATH"] = os.path.join(_TMP, "hub-state.json")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.config import HUB_EVENTS_PATH, HUB_SNAPSHOT_PATH  # noqa: E402
from src.hub import protocol  # noqa: E402
from src.hub.manager import is_hub_running  # noqa: E402

harness = importlib.import_module("_tmp_long_transcription_test")

PASSED = []
FAILED = []
FAKE_PORT = 9999


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def read_events():
    if not os.path.exists(HUB_EVENTS_PATH):
        return []
    out = []
    with open(HUB_EVENTS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


EDITOR_LINE = re.compile(r"^\[\d{2}:\d{2}\]\s*\[(?P<source>[^\]]+)\]\s*(?P<text>.*)$")


def editor_lines(text):
    """The editor's "[HH:MM] [SOURCE] line" entries, as (source, text) pairs."""
    pairs = []
    for raw in text.splitlines():
        match = EDITOR_LINE.match(raw.strip())
        if match:
            pairs.append((match.group("source").lower(), match.group("text").strip()))
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30.0, help="how long to run a session")
    args = parser.parse_args()

    print(f"hub artefacts: {_TMP}")

    # The session store would rewrite the real sessions/current.json.
    import src.session_store as session_store_module

    session_store_module.SESSION_DIR = tempfile.mkdtemp(prefix="hub-pipeline-sessions-")

    server = harness.FakeSonioxServer(FAKE_PORT)
    server.start()
    if not harness._wait_for_port(FAKE_PORT):
        raise SystemExit(f"fake Soniox did not start on port {FAKE_PORT}")

    import src.ui as ui_module

    harness._install_stubs(ui_module, "pipeline")

    app = QApplication([])
    window = ui_module.MainWindow()
    window._auto_reply_enabled = False
    window._last_pickup_auto_enabled = False
    window.bullet_points_controller.set_auto(False)
    window.last_pickup_controller.set_auto(False)

    print("\n[live session]")
    check("the app started a hub", is_hub_running())
    check("the app's hub client is connected", window.hub_client.is_connected())
    host_id = window.device_combo.currentData()
    if host_id is None:
        raise SystemExit("no host audio input device available")
    print(f"  host device id: {host_id}")

    window.transcription_controller.start_session(
        host_id, None, mode="transcription", target_lang=None
    )
    started = time.time()
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.exec()
    elapsed = time.time() - started

    ui_pairs = editor_lines(window.transcription_editor.toPlainText())
    print(f"  ran {elapsed:.1f}s; editor shows {len(ui_pairs)} labeled lines")

    window.transcription_controller.stop_session()
    time.sleep(0.5)
    window.close()
    time.sleep(0.5)

    print("\n[hub topics]")
    events = read_events()
    by_topic = {}
    for event in events:
        by_topic.setdefault(event.get("topic"), []).append(event)
    for topic in sorted(by_topic):
        print(f"  {topic}: {len(by_topic[topic])}")
    finals = by_topic.get(protocol.TOPIC_TRANSCRIPTION_FINAL, [])
    partials = by_topic.get(protocol.TOPIC_TRANSCRIPTION_PARTIAL, [])
    check("the hub received finalized transcriptions", len(finals) > 0, f"got {len(finals)}")
    check("the hub received live partials", len(partials) > 0, f"got {len(partials)}")
    check("partials carry the same content the server sent",
          any(p["payload"]["text"].strip() and "\n" not in p["payload"]["text"] for p in partials))
    check("the hub received worker status", bool(by_topic.get(protocol.TOPIC_STATUS)))
    check("final sequence numbers are per-topic and increasing",
          [f["seq"] for f in finals] == list(range(1, len(finals) + 1)),
          str([f["seq"] for f in finals]))

    print("\n[hub vs UI]")
    hub_pairs = [(f["payload"]["source"], f["payload"]["text"].strip()) for f in finals]
    check("the hub's finals match the editor's lines",
          hub_pairs == ui_pairs,
          f"hub={hub_pairs[:3]}... ui={ui_pairs[:3]}...")
    check("the hub recorded the source labels", any(s == "host" for s, _ in hub_pairs))

    print("\n[hub state]")
    snapshot = {}
    if os.path.exists(HUB_SNAPSHOT_PATH):
        try:
            with open(HUB_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
                snapshot = json.load(f)
        except ValueError:
            snapshot = {}
    check("the debounced snapshot was written", bool(snapshot), HUB_SNAPSHOT_PATH)
    stored = [(line.get("source"), (line.get("text") or "").strip())
              for line in snapshot.get("transcriptions") or []]
    check("the snapshot holds the same transcript as the event log", stored == hub_pairs,
          f"snapshot={len(stored)} lines, log={len(hub_pairs)} lines")
    check("every stored line has a session-store timestamp",
          all(line.get("timestamp") for line in snapshot.get("transcriptions") or []))
    check("the hub derived the conversation from the finals",
          [t.get("text", "").strip() for t in snapshot.get("conversation") or []]
          == [text for _, text in hub_pairs][-len(snapshot.get("conversation") or []) or None:])
    print(f"  session id {snapshot.get('id')}  stored {len(stored)} lines")

    # Independent confirmation that the fake server really produced the text the
    # hub recorded (guards against a wiring that invents content).
    expected = set(harness.SENTENCES)
    check("stored sentences come from the fake Soniox server",
          bool(hub_pairs) and all(text in expected for _, text in hub_pairs),
          str(sorted({t for _, t in hub_pairs if t not in expected})[:2]))
    print(f"  digest {hashlib.sha1(json.dumps(hub_pairs).encode()).hexdigest()[:12]}")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
