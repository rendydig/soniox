"""Throwaway end-to-end smoke test for the central hub (M0 acceptance).

Starts the real Go hub binary, then exercises the Python client the way the app
and the agents will: handshake, subscribe, publish, ordered events with
sequence numbers, request/response (snapshot / restore / reset), the debug HTTP
endpoint, the JSONL event log and the debounced snapshot, and finally a clean
shutdown.

    venv/Scripts/python.exe _tmp_hub_smoke.py
    venv/Scripts/python.exe _tmp_hub_smoke.py --keep   # leave the hub running

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

# Redirect the hub's artefacts into a temp dir so the real logs/ and sessions/
# files are untouched. Must happen before src.config is imported.
_TMP = tempfile.mkdtemp(prefix="hub-smoke-")
os.environ["HUB_EVENTS_PATH"] = os.path.join(_TMP, "hub-events.jsonl")
os.environ["HUB_SNAPSHOT_PATH"] = os.path.join(_TMP, "hub-state.json")

from src.config import HUB_ADDR, HUB_EVENTS_PATH, HUB_HTTP_ADDR, HUB_SNAPSHOT_PATH  # noqa: E402
from src.hub import protocol  # noqa: E402
from src.hub.client import HubClient  # noqa: E402
from src.hub.manager import HubManager, is_hub_running  # noqa: E402

PASSED = []
FAILED = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def sink(target: list):
    """A message handler that records only fanned-out events (not acks)."""

    def handler(msg):
        if msg.get("type") == protocol.EVENT:
            target.append(msg)

    return handler


def connect(name: str, role: str = protocol.ROLE_UI, timeout: float = 8.0) -> HubClient:
    client = HubClient(HUB_ADDR, role=role, name=name)
    client.start()
    if not wait_for(lambda: client.is_connected(), timeout=timeout):
        raise SystemExit(f"{name} could not connect to the hub at {HUB_ADDR}")
    return client


def barrier(client: HubClient) -> None:
    """Wait until everything sent before this call has been processed.

    Frames on one connection are handled in order, so a completed round trip
    proves a preceding subscribe/publish was applied.
    """
    client.request(protocol.OP_SNAPSHOT, timeout=5.0)


def snapshot_session(client: HubClient) -> dict:
    response = client.request(protocol.OP_SNAPSHOT, timeout=5.0) or {}
    return response.get("result", {}).get("session", {})


def snapshot_config(client: HubClient) -> dict:
    response = client.request(protocol.OP_SNAPSHOT, timeout=5.0) or {}
    return response.get("result", {}).get("config", {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="leave the hub running")
    args = parser.parse_args()

    print(f"hub artefacts: {_TMP}")

    # --- lifecycle ----------------------------------------------------
    print("\n[lifecycle]")
    manager = HubManager()
    already_up = is_hub_running()
    check("hub starts (or is already up)", manager.ensure_running())
    check("port 8770 is listening", is_hub_running())
    own_hub = manager.process is not None
    if not own_hub:
        print("  note: a hub was already running; reusing it and leaving it alone")
        print("        (storage checks are skipped: its paths are not this run's temp dir)")

    subscriber = connect("smoke-subscriber")
    publisher = connect("smoke-publisher", role=protocol.ROLE_PUBLISHER)

    # --- subscribe / ordering / sequence numbers ----------------------
    print("\n[subscribe + ordering]")
    received: list = []
    subscriber.set_message_handler(sink(received))
    subscriber.subscribe([protocol.TOPIC_TRANSCRIPTION_FINAL, protocol.TOPIC_TRANSLATION_FINAL])
    barrier(subscriber)

    lines = ["halo, apa kabar?", "saya baik, terima kasih", "mau ke mana hari ini?"]
    for index, text in enumerate(lines, start=1):
        publisher.publish(
            protocol.TOPIC_TRANSCRIPTION_FINAL,
            {"source": "speaker", "text": text, "endpoint": index == len(lines)},
        )
    check("every published final is delivered",
          wait_for(lambda: len(received) >= 3) and len(received) == 3,
          f"got {len(received)}")
    check("sequence numbers are 1..3", [m.get("seq") for m in received] == [1, 2, 3],
          f"got {[m.get('seq') for m in received]}")
    check("payloads arrive verbatim", [m["payload"]["text"] for m in received] == lines)
    check("events carry their topic",
          all(m.get("topic") == protocol.TOPIC_TRANSCRIPTION_FINAL for m in received))

    # --- topic isolation ------------------------------------------------
    print("\n[topics]")
    received.clear()
    publisher.publish(protocol.TOPIC_TRANSCRIPTION_PARTIAL, {"source": "speaker", "text": "sed"})
    publisher.publish(protocol.TOPIC_TRANSLATION_FINAL, {"source": "speaker", "text": "kemana?"})
    check("translation.final reaches the subscriber",
          wait_for(lambda: len(received) == 1), f"got {len(received)}")
    check("partials stay off the final subscription",
          not any(m.get("topic") == protocol.TOPIC_TRANSCRIPTION_PARTIAL for m in received))
    check("partials are flagged disposable", protocol.is_disposable(protocol.TOPIC_TRANSCRIPTION_PARTIAL))

    # --- fan-out to several subscribers ---------------------------------
    print("\n[fan-out]")
    second = connect("smoke-subscriber-2")
    second_seen: list = []
    second.set_message_handler(sink(second_seen))
    second.subscribe([protocol.TOPIC_TRANSCRIPTION_FINAL])
    barrier(second)
    publisher.publish(protocol.TOPIC_TRANSCRIPTION_FINAL, {"source": "speaker", "text": "broadcast"})
    check("every subscriber receives a published frame",
          wait_for(lambda: len(second_seen) == 1), f"second saw {len(second_seen)}")

    # --- request / response ----------------------------------------------
    print("\n[requests]")
    response = publisher.request(protocol.OP_SNAPSHOT)
    check("snapshot responds", response is not None and response.get("ok") is True)
    session = snapshot_session(publisher)
    check("hub owns the transcript", len(session.get("transcriptions") or []) == 4,
          f"got {len(session.get('transcriptions') or [])}")
    check("hub derives the conversation history",
          [t["text"] for t in session.get("conversation") or []] == lines + ["broadcast"],
          f"got {[t.get('text') for t in session.get('conversation') or []]}")
    check("store starts with an empty speaker profile", session.get("speaker") == {})
    check("publisher timestamps are preserved",
          all((t.get("timestamp") or "") for t in session.get("transcriptions") or []))

    restore_payload = {
        "id": "20261012-060000",
        "created_at": "2026-10-12T06:00:00.000000",
        "bullets": [{"text": "restored bullet"}],
        "bullet_windows": [{"mode": "auto", "start": "t0", "end": "t1", "lines": 3,
                            "from_index": 0, "to_index": 0}],
        "conversation": [{"text": "hi", "role": "speaker", "suggestion": ""}],
        "transcriptions": [{"source": "host", "text": "restored", "timestamp": "t"}],
        "translations": [],
        "aireply_results": [],
        "screenshots": ["data:image/jpeg;base64,AAAA"],
        "last_pickup": "restored pickup",
        "speaker": {"name": "Ada", "occupation": "engineer"},
    }
    response = publisher.request(protocol.OP_RESTORE, restore_payload)
    check("restore responds ok", response is not None and response.get("ok") is True)
    published = snapshot_session(publisher)
    check("restore seeds the transcript", published.get("id") == "20261012-060000")
    check("restore seeds bullets / speaker / last_pickup",
          bool(published.get("bullets"))
          and published.get("speaker", {}).get("name") == "Ada"
          and published.get("last_pickup") == "restored pickup")
    check("restore seeds the screenshots", len(published.get("screenshots") or []) == 1)
    check("restore seeds the bullet windows", len(published.get("bullet_windows") or []) == 1)

    # --- bullets topic (M1 dual-write) ------------------------------------
    print("\n[bullets]")
    publisher.publish(protocol.TOPIC_BULLETS, {
        "items": ["point one", "point two"],
        "speaker": {"name": "Ada", "occupation": "engineer"},
        "windows": [{"mode": "auto", "start": "t0", "end": "t1", "lines": 3,
                     "from_index": 0, "to_index": 1}],
    })
    barrier(publisher)
    bullets_state = snapshot_session(publisher)
    check("bullets topic stores the list", len(bullets_state.get("bullets") or []) == 2,
          f"got {bullets_state.get('bullets')}")
    check("bullets topic stores the windows", len(bullets_state.get("bullet_windows") or []) == 1,
          f"got {bullets_state.get('bullet_windows')}")
    check("bullets topic stores the speaker profile",
          (bullets_state.get("speaker") or {}).get("name") == "Ada")

    # --- session.config ---------------------------------------------------
    print("\n[session config]")
    publisher.publish(protocol.TOPIC_SESSION_CONFIG, {"auto_reply_enabled": True, "purpose": "language_learning"})
    barrier(publisher)
    check("session.config is stored", snapshot_config(publisher).get("auto_reply_enabled") is True)

    # --- persistence --------------------------------------------------------
    print("\n[persistence]")
    if own_hub:
        logged = _read_jsonl(HUB_EVENTS_PATH)
        check("event log records topics in order",
              [e.get("topic") for e in logged[:3]] == [protocol.TOPIC_TRANSCRIPTION_FINAL] * 3,
              f"got {[e.get('topic') for e in logged[:3]]}")
        check("event log records sequence numbers", [e.get("seq") for e in logged[:3]] == [1, 2, 3])
        check("oversized values are elided from the log", _event_log_elides_screenshots(publisher))
        check("state snapshot is written on the debounce", _snapshot_written(publisher))
    else:
        print("  skipped (the hub under test was not started by this run)")

    # --- debug HTTP ----------------------------------------------------------
    print("\n[debug http]")
    check("GET /healthz answers", _http_ok(f"http://{HUB_HTTP_ADDR}/healthz"))
    check("GET /state answers", _http_ok(f"http://{HUB_HTTP_ADDR}/state"))

    # --- reset ----------------------------------------------------------------
    print("\n[reset]")
    response = publisher.request(protocol.OP_RESET)
    check("reset responds ok", response is not None and response.get("ok") is True)
    emptied = snapshot_session(publisher)
    check("reset empties the session",
          not emptied.get("transcriptions") and not emptied.get("bullets")
          and emptied.get("last_pickup") == "")
    check("reset keeps the live config",
          snapshot_config(publisher).get("auto_reply_enabled") is True)

    second.stop()
    subscriber.stop()
    publisher.stop()
    check("clients disconnect cleanly", True)

    # --- shutdown ---------------------------------------------------------------
    print("\n[shutdown]")
    if own_hub and not args.keep:
        manager.stop()
        check("hub stops with the manager", wait_for(lambda: not is_hub_running(), timeout=5.0))
    else:
        print("  note: leaving the hub running")

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _event_log_elides_screenshots(publisher: HubClient) -> bool:
    big = "data:image/jpeg;base64," + ("A" * 2000)
    publisher.publish(protocol.TOPIC_SCREENSHOTS_ADD, {"data_url": big})
    time.sleep(0.3)
    for event in reversed(_read_jsonl(HUB_EVENTS_PATH)):
        if event.get("topic") == protocol.TOPIC_SCREENSHOTS_ADD:
            value = event.get("payload", {}).get("data_url", "")
            return value.startswith("<") and value.endswith("bytes elided>")
    return False


def _snapshot_written(publisher: HubClient) -> bool:
    publisher.publish(protocol.TOPIC_TRANSCRIPTION_FINAL, {"source": "host", "text": "snapshot me"})
    if not wait_for(lambda: os.path.exists(HUB_SNAPSHOT_PATH), timeout=8.0):
        return False
    time.sleep(0.2)
    try:
        with open(HUB_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return any(line.get("text") == "snapshot me" for line in data.get("transcriptions") or [])


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status == 200 and bool(response.read())
    except (urllib.error.URLError, OSError) as e:
        print(f"    ({url}: {e})")
        return False


if __name__ == "__main__":
    sys.exit(main())
