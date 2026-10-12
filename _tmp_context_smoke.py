"""Temp smoke test: the Context pane's WebSocket protocol end-to-end.

Drives a real `websocket-server` (start it first: `cd websocket-server && npm start`)
with two peers:

  * `editor`  — plays the Context pane (sends the mutations)
  * `app`     — plays the Python app, which only listens (this is the path the
                reply pipeline depends on: `context_state` broadcasts)

The user's own selection is restored at the end, and every file the test
creates lives in a temp dir that is deleted afterwards.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time

import websockets

URI = os.environ.get("CONTEXT_WS_URL", "ws://localhost:8765")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
MAX_CONTEXT_BYTES = 64 * 1024

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f"  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        failures.append(name)


class Peer:
    """A WebSocket client with a message queue and typed waits."""

    def __init__(self, name):
        self.name = name
        self.ws = None
        self.queue = asyncio.Queue()
        self.reader = None

    async def connect(self):
        self.ws = await websockets.connect(URI)
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            async for raw in self.ws:
                await self.queue.put(json.loads(raw))
        except Exception:
            pass

    async def send(self, payload):
        await self.ws.send(json.dumps(payload))

    async def drain(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    async def wait_for(self, type_, timeout=3.0):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = await asyncio.wait_for(self.queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if message.get("type") == type_:
                return message

    async def request(self, payload, expect="context_state", timeout=3.0):
        await self.drain()
        await self.send(payload)
        return await self.wait_for(expect, timeout)

    async def wait_for_content(self, role, text, timeout=4.0):
        """Wait for a `context_state` whose `role` content is `text`.

        A broadcast already in flight when the caller started can land first,
        so this keeps reading until the expected content shows up.
        """
        deadline = time.monotonic() + timeout
        last = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return last
            message = await self.wait_for("context_state", timeout=remaining)
            if message is None:
                return last
            last = message
            if (message.get("contents") or {}).get(role) == text:
                return message

    async def close(self):
        if self.reader:
            self.reader.cancel()
        if self.ws:
            await self.ws.close()


def read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


async def main():
    workdir = tempfile.mkdtemp(prefix="context-smoke-")
    editor = Peer("editor")
    app_peer = Peer("app")
    await editor.connect()
    await app_peer.connect()

    created = []
    try:
        # --- shape + seed -------------------------------------------------
        print("[1] context_get returns the whole state")
        initial = await editor.request({"type": "context_get"})
        check("context_state arrived", initial is not None)
        if initial is None:
            print("\nIs the web service running with the new code? "
                  "cd websocket-server && npm start")
            return
        for key in ("selection", "problems", "history", "contents", "revision"):
            check(f"payload has {key}", key in initial)
        for role in ("host", "speaker"):
            check(f"payload has {role}", role in initial["selection"])

        print("\n[2] the .env seed")
        seed_path = initial["selection"]["host"]
        if seed_path:
            check("seed selection set", True, seed_path)
            check("seed contents non-empty", bool(initial["contents"]["host"].strip()))
            check("seed has no problem", initial["problems"]["host"] is None)
            check("seed is in the history", seed_path in initial["history"]["host"])
        else:
            print("SKIP  no host context seeded (SELF_CONTEXT_FILE unset?)")

        # --- create + save -------------------------------------------------
        print("\n[3] context_new + context_save writes the file on disk")
        target = os.path.join(workdir, "host.md")
        created.append(target)
        state = await editor.request({"type": "context_new", "role": "host", "path": target})
        check("new selected it", state and state["selection"]["host"] == target, target)
        check("new file is empty", state and state["contents"]["host"] == "")
        check("new file exists on disk", os.path.exists(target))

        body = "you are a Go engineer\n\n## notes\n- reviews every line"
        state = await editor.request(
            {"type": "context_save", "role": "host", "path": target, "text": body}
        )
        check("save echoed the text", state and state["contents"]["host"] == body)
        check("disk content matches", read_file(target) == body)
        check("history holds the new file", state and state["history"]["host"][0] == target)

        print("\n[4] the Python app sees the same state (broadcast path)")
        await app_peer.drain()
        body2 = body + "\n- one more line"
        state = await editor.request(
            {"type": "context_save", "role": "host", "path": target, "text": body2}
        )
        seen = await app_peer.wait_for_content("host", body2)
        check("broadcast received", seen is not None)
        check("broadcast carries the text", seen and seen["contents"]["host"] == body2)

        # --- rejections ----------------------------------------------------
        print("\n[5] a save only ever overwrites the selected file")
        other = os.path.join(workdir, "other.md")
        status = await editor.request(
            {"type": "context_save", "role": "host", "path": other, "text": "nope"},
            expect="context_status",
        )
        check("rejected", status and status["status"] == "invalid", status and status["message"])
        check("nothing was created", not os.path.exists(other))

        print("\n[6] a save to a file that vanished is 'missing', not a new file")
        vanished = os.path.join(workdir, "vanished.md")
        created.append(vanished)
        await editor.request({"type": "context_new", "role": "host", "path": vanished})
        os.unlink(vanished)
        status = await editor.request(
            {"type": "context_save", "role": "host", "path": vanished, "text": "text"},
            expect="context_status",
        )
        check("rejected as missing", status and status["status"] == "missing")
        check("still deleted", not os.path.exists(vanished))

        print("\n[7] invalid paths are refused")
        status = await editor.request(
            {"type": "context_select", "role": "host", "path": os.path.join(workdir, "x.json")},
            expect="context_status",
        )
        check("bad extension refused", status and status["status"] == "invalid")
        status = await editor.request(
            {"type": "context_select", "role": "host", "path": workdir},
            expect="context_status",
        )
        check("a directory is refused", status and status["status"] == "invalid")
        status = await editor.request(
            {"type": "context_select", "role": "host", "path": os.path.join(workdir, "gone.md")},
            expect="context_status",
        )
        check("a missing file is refused", status and status["status"] == "missing")

        # --- history -------------------------------------------------------
        print("\n[8] the re-select history is MRU, deduped and capped at 10")
        paths = []
        for index in range(12):
            path = os.path.join(workdir, f"hist-{index}.md")
            paths.append(path)
            created.append(path)
            await editor.request({"type": "context_new", "role": "host", "path": path})
        state = await editor.request({"type": "context_get"})
        history = state["history"]["host"]
        check("capped at 10", len(history) == 10, str(len(history)))
        check("most recent first", history[0] == paths[-1])
        check("no duplicates", len(set(history)) == len(history))
        check("older entries dropped", paths[0] not in history)

        # --- missing / oversized while selected ----------------------------
        print("\n[9] a file deleted while selected degrades to 'no context'")
        await editor.request({"type": "context_select", "role": "host", "path": paths[-1]})
        os.unlink(paths[-1])
        state = await editor.request({"type": "context_get"})
        check("problem reported", state["problems"]["host"] == "missing")
        check("contents emptied", state["contents"]["host"] == "")
        check("selection kept for the user to fix", state["selection"]["host"] == paths[-1])

        print("\n[10] a file that grows past the cap degrades too")
        big = os.path.join(workdir, "big.md")
        created.append(big)
        with open(big, "w", encoding="utf-8") as handle:
            handle.write("x")
        await editor.request({"type": "context_select", "role": "host", "path": big})
        with open(big, "w", encoding="utf-8") as handle:
            handle.write("x" * (MAX_CONTEXT_BYTES + 1))
        state = await editor.request({"type": "context_get"})
        check("problem reported", state["problems"]["host"] == "too_large")

        # --- external edit -------------------------------------------------
        print("\n[11] an edit made outside the pane is picked up")
        small = os.path.join(workdir, "external.md")
        created.append(small)
        with open(small, "w", encoding="utf-8") as handle:
            handle.write("first")
        await editor.request({"type": "context_select", "role": "host", "path": small})
        await editor.drain()
        with open(small, "w", encoding="utf-8") as handle:
            handle.write("edited in VS Code")
        state = await editor.wait_for_content("host", "edited in VS Code")
        check("watcher rebroadcast", state is not None)
        check("new text delivered", state and state["contents"]["host"] == "edited in VS Code")

        # --- clear + forget -------------------------------------------------
        print("\n[12] clear_selection and forget")
        state = await editor.request({"type": "context_clear_selection", "role": "host"})
        check("selection cleared", state and state["selection"]["host"] is None)
        check("contents emptied", state and state["contents"]["host"] == "")
        state = await editor.request({"type": "context_forget", "role": "host", "path": small})
        check("forgotten", state and small not in state["history"]["host"])
        check("other entries kept", state and big in state["history"]["host"])

        # --- speaker is independent ------------------------------------------
        print("\n[13] host and speaker are independent")
        speaker_file = os.path.join(workdir, "speaker.txt")
        created.append(speaker_file)
        state = await editor.request(
            {"type": "context_new", "role": "speaker", "path": speaker_file}
        )
        check("speaker selected", state and state["selection"]["speaker"] == speaker_file)
        check("host untouched", state and state["selection"]["host"] is None)
        state = await editor.request(
            {"type": "context_save", "role": "speaker", "path": speaker_file, "text": "the speaker"}
        )
        check("speaker saved", state and state["contents"]["speaker"] == "the speaker")

        # --- cleanup ---------------------------------------------------------
        print("\n[cleanup] restoring the original selection")
        if seed_path:
            state = await editor.request({"type": "context_select", "role": "host", "path": seed_path})
            check("host selection restored", state and state["selection"]["host"] == seed_path)
        state = await editor.request({"type": "context_clear_selection", "role": "speaker"})
        check("speaker cleared", state and state["selection"]["speaker"] is None)
        for path in created:
            await editor.request({"type": "context_forget", "role": "host", "path": path})
            await editor.request({"type": "context_forget", "role": "speaker", "path": path})
        state = await editor.request({"type": "context_get"})
        leftovers = [
            p
            for role in ("host", "speaker")
            for p in state["history"][role]
            if workdir in p
        ]
        check("no temp paths left in the history", not leftovers, str(leftovers))
    finally:
        await editor.close()
        await app_peer.close()
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
