#!/usr/bin/env python
"""Debug CLI for the central hub.

Talks to the hub the same way the app does (NDJSON over loopback), and starts
it on demand when nothing is listening (``--no-start`` to forbid that) — which
keeps the hub inspectable without launching the UI. A hub started this way
outlives the command, exactly like one started by hand.

    python tools/hubctl.py state
    python tools/hubctl.py tail transcription.final bullet_points
    python tools/hubctl.py publish status '{"source":"manual","message":"hi"}'
    python tools/hubctl.py config '{"auto_reply_enabled":true}'
    python tools/hubctl.py reset
    python tools/hubctl.py restore sessions/20261012-060000.json
    python tools/hubctl.py health
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hub import protocol  # noqa: E402
from src.hub.client import HubClient  # noqa: E402
from src.hub.manager import HubManager, is_hub_running  # noqa: E402


def parse_json(raw: str):
    try:
        return json.loads(raw)
    except ValueError as e:
        raise SystemExit(f"invalid JSON: {e}")


def connect(args) -> HubClient:
    if not is_hub_running(args.addr):
        if args.no_start:
            raise SystemExit(f"no hub listening on {args.addr}")
        if not HubManager(args.addr).ensure_running():
            raise SystemExit(f"could not start a hub on {args.addr}")

    client = HubClient(args.addr, role=protocol.ROLE_UI, name="hubctl")
    client.start()
    deadline = time.time() + 5.0
    while time.time() < deadline and not client.is_connected():
        time.sleep(0.05)
    if not client.is_connected():
        raise SystemExit("connected to the port but the handshake failed (check HUB_TOKEN)")
    return client


def cmd_state(args, client):
    response = client.request(protocol.OP_SNAPSHOT, timeout=5.0)
    if response is None:
        raise SystemExit("no response to the snapshot request")
    session = response.get("result", {}).get("session", {})
    if args.summary:
        counts = {
            key: len(session.get(key) or [])
            for key in ("transcriptions", "translations", "conversation", "aireply_results", "screenshots")
        }
        print(f"session   {session.get('id')}  (updated {session.get('updated_at')})")
        for key, count in counts.items():
            print(f"  {key:<15} {count}")
        print(f"  bullets         {len(session.get('bullets') or [])}")
        print(f"  bullet_windows  {len(session.get('bullet_windows') or [])}")
        print(f"  last_pickup     {session.get('last_pickup')!r}")
        speaker = session.get("speaker") or {}
        print(f"  speaker         {speaker.get('name') or '-'}")
        return
    print(json.dumps(response.get("result"), indent=2, ensure_ascii=False))


def cmd_health(args, client):
    import urllib.request

    url = f"http://{args.http}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            print(response.read().decode("utf-8").strip())
    except OSError as e:
        raise SystemExit(f"debug HTTP unreachable at {url}: {e}")


def cmd_tail(args, client):
    topics = args.topics or [protocol.TOPIC_ALL]

    def show(msg):
        # Only fanned-out events; the subscribe ack would just be noise.
        if msg.get("type") != protocol.EVENT:
            return
        print(
            json.dumps(
                {"seq": msg.get("seq"), "topic": msg.get("topic"), "payload": msg.get("payload")},
                ensure_ascii=False,
            ),
            flush=True,
        )

    client.set_message_handler(show)
    if not client.subscribe(topics):
        raise SystemExit("could not subscribe (hub not connected)")
    print(f"# tailing {', '.join(topics)} on {args.addr} (Ctrl-C to stop)", file=sys.stderr, flush=True)
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


def cmd_publish(args, client):
    payload = parse_json(args.payload) if args.payload else {}
    client.publish(args.topic, payload)
    time.sleep(0.2)
    print(f"published {args.topic}")


def cmd_config(args, client):
    client.publish(protocol.TOPIC_SESSION_CONFIG, parse_json(args.payload))
    time.sleep(0.2)


def cmd_reset(args, client):
    response = client.request(protocol.OP_RESET, timeout=5.0)
    print(json.dumps(response, ensure_ascii=False))


def cmd_restore(args, client):
    with open(args.path, "r", encoding="utf-8") as f:
        session = json.load(f)
    response = client.request(protocol.OP_RESTORE, session, timeout=10.0)
    print(json.dumps(response, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    from src.config import HUB_ADDR, HUB_HTTP_ADDR

    parser = argparse.ArgumentParser(description="Debug CLI for the Soniox hub")
    parser.add_argument("--addr", default=HUB_ADDR, help="hub NDJSON address")
    parser.add_argument("--http", default=HUB_HTTP_ADDR, help="hub debug HTTP address")
    parser.add_argument("--no-start", action="store_true", help="never start the hub")
    sub = parser.add_subparsers(dest="command", required=True)

    state = sub.add_parser("state", help="dump the live session state")
    state.add_argument("--summary", action="store_true", help="one-line counts instead of JSON")
    state.set_defaults(func=cmd_state)

    health = sub.add_parser("health", help="query the debug HTTP endpoint")
    health.set_defaults(func=cmd_health)

    tail = sub.add_parser("tail", help="stream events")
    tail.add_argument("topics", nargs="*", help="topic patterns (default: everything)")
    tail.set_defaults(func=cmd_tail)

    publish = sub.add_parser("publish", help="publish one topic")
    publish.add_argument("topic")
    publish.add_argument("payload", nargs="?", default="")
    publish.set_defaults(func=cmd_publish)

    config = sub.add_parser("config", help="publish session.config")
    config.add_argument("payload")
    config.set_defaults(func=cmd_config)

    reset = sub.add_parser("reset", help="start a new session")
    reset.set_defaults(func=cmd_reset)

    restore = sub.add_parser("restore", help="seed the session from a JSON file")
    restore.add_argument("path")
    restore.set_defaults(func=cmd_restore)

    return parser


def main():
    args = build_parser().parse_args()
    client = connect(args)
    try:
        args.func(args, client)
    finally:
        client.stop()


if __name__ == "__main__":
    main()
