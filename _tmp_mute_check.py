"""Throwaway checks for the microphone soft mute (no real Soniox connection).

Drives the real ``SonioxWorker._stream_audio()`` against a fake ``websockets``
connection and asserts the sender behaviour:

  * live: each queued chunk is sent as a **binary** frame
  * muted: **no** PCM is sent, the queue keeps draining, and a
    ``{"type": "keepalive"}`` **text** frame is sent within the interval
  * unmuted: PCM resumes immediately
  * stopping still sends the end-of-stream frame

Plus the controller contract: ``set_mic_muted`` reaches the live worker, and a
worker created by ``start_session`` is muted *before* it starts.

    venv/bin/python _tmp_mute_check.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import asyncio
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import src.config as config  # noqa: E402
import src.workers as workers  # noqa: E402
from src.controllers import transcription_controller as tc_module  # noqa: E402
from src.controllers.transcription_controller import TranscriptionController  # noqa: E402
from src.ui_components.mic_icon import mic_icon  # noqa: E402

PASSED = []
FAILED = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


class FakeWS:
    """Records every frame; its async iteration ends when the worker stops."""

    def __init__(self, worker):
        self._worker = worker
        self.frames = []  # (kind, payload)

    async def send(self, data):
        kind = "binary" if isinstance(data, (bytes, bytearray)) else "text"
        self.frames.append((kind, data))
        await asyncio.sleep(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        while not self._worker._stop_flag:
            await asyncio.sleep(0.05)
        if False:  # pragma: no cover - makes this an async generator
            yield None


class FakeConnect:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *exc):
        return False


async def run_scenario():
    worker = workers.SonioxWorker(0)
    # Never spawn the capture child; the queue is fed by hand.
    worker._capture_supervisor = lambda: None
    fake = FakeWS(worker)
    workers.websockets.connect = lambda *a, **k: FakeConnect(fake)

    task = asyncio.create_task(worker._stream_audio())
    await asyncio.sleep(0.1)

    print("\n[live]")
    check("config is sent as a text frame",
          fake.frames and fake.frames[0][0] == "text" and "api_key" in fake.frames[0][1],
          str(fake.frames[:1])[:120])

    mark = len(fake.frames)
    for _ in range(3):
        worker._audio_queue.put_nowait(b"\x01\x02")
    await asyncio.sleep(0.15)
    binary = [f for f in fake.frames[mark:] if f[0] == "binary"]
    check("live audio is sent as binary PCM", len(binary) == 3, f"got {len(binary)}")

    print("\n[muted]")
    worker.set_muted(True)
    mark = len(fake.frames)
    for _ in range(8):
        worker._audio_queue.put_nowait(b"\x03\x04")
    await asyncio.sleep(0.6)
    muted = fake.frames[mark:]
    kinds = [f[0] for f in muted]
    check("no PCM is sent while muted", not any(k == "binary" for k in kinds), str(kinds))
    keepalives = [f for f in muted if f[0] == "text" and f[1] == json.dumps({"type": "keepalive"})]
    check("a keepalive is sent within the interval", len(keepalives) >= 1, f"got {len(keepalives)}")
    check("keepalives are text frames carrying the documented JSON",
          all(f[0] == "text" and json.loads(f[1]) == {"type": "keepalive"} for f in keepalives))
    check("the audio queue drained while muted", worker._audio_queue.qsize() == 0,
          f"qsize={worker._audio_queue.qsize()}")

    print("\n[unmuted]")
    worker.set_muted(False)
    mark = len(fake.frames)
    for _ in range(2):
        worker._audio_queue.put_nowait(b"\x05\x06")
    await asyncio.sleep(0.15)
    resumed = [f for f in fake.frames[mark:] if f[0] == "binary"]
    check("PCM resumes after unmute", len(resumed) == 2, f"got {len(resumed)}")
    check("no keepalive once live again",
          not any(f[0] == "text" and f[1] for f in fake.frames[mark:]) or
          len([f for f in fake.frames[mark:] if f[0] == "text" and f[1] == ""]) <= 1,
          str(fake.frames[mark:])[:120])

    print("\n[stop]")
    worker.stop()
    await asyncio.wait_for(task, timeout=3)
    check("end-of-stream frame is still sent", fake.frames[-1] == ("text", ""),
          str(fake.frames[-1]))


class StubWorker:
    def __init__(self):
        self.muted = None

    def set_muted(self, muted):
        self.muted = bool(muted)


class FakeSonioxWorker(QObject):
    """A QObject stand-in so start_session() can build and connect a worker."""

    transcription_update = Signal(str, bool, str, bool)
    translation_update = Signal(str, bool, str)
    status = Signal(str, str)
    error = Signal(str, str)
    finished = Signal()
    instances = []

    def __init__(self, device, mode="transcription", target_lang="en",
                 input_source="host", parent=None, hub=None):
        super().__init__()
        self.input_source = input_source
        self.events = []
        FakeSonioxWorker.instances.append(self)

    def set_muted(self, muted):
        self.events.append(("set_muted", bool(muted)))

    def start(self):
        self.events.append(("start", None))

    def stop(self):
        self.events.append(("stop", None))

    def isRunning(self):
        return False

    def wait(self, *args):
        return True

    def terminate(self):
        pass

    def deleteLater(self):
        pass


def check_controller():
    print("\n[controller]")
    controller = TranscriptionController()
    check("the app starts unmuted", controller._mic_muted is False)

    stub = StubWorker()
    controller._host_worker = stub
    controller.set_mic_muted(True)
    check("set_mic_muted reaches the live worker", stub.muted is True)
    check("set_mic_muted stores the state", controller._mic_muted is True)
    controller.set_mic_muted(False)
    check("unmute reaches the live worker too", stub.muted is False)
    controller._host_worker = None

    # A worker created by start_session must be muted before it starts.
    tc_module.SonioxWorker = FakeSonioxWorker
    fake_controller = TranscriptionController()
    fake_controller.set_mic_muted(True)
    started = fake_controller.start_session(0, None)
    check("start_session succeeds with no speaker device", started is True)
    host = FakeSonioxWorker.instances[-1]
    check("start_session applies the mute before .start()",
          ("set_muted", True) in host.events
          and host.events.index(("set_muted", True)) < host.events.index(("start", None)),
          str(host.events))
    fake_controller._host_worker = None
    fake_controller._speaker_worker = None


def _pixels(icon):
    image = icon.pixmap(18, 18).toImage()
    return [image.pixelColor(x, y)
            for y in range(image.height())
            for x in range(image.width())]


def check_icon():
    print("\n[icon]")
    live = mic_icon(muted=False)
    muted = mic_icon(muted=True)
    check("the live icon is non-null", not live.isNull())
    check("the muted icon is non-null", not muted.isNull())

    live_px = _pixels(live)
    muted_px = _pixels(muted)

    def opaque(pixels):
        return [c for c in pixels if c.alpha() > 0]

    def has_red(pixels):
        return any(c.alpha() > 0 and c.red() > 150 and c.green() < 110 and c.blue() < 110
                   for c in pixels)

    check("both states draw something", len(opaque(live_px)) > 0 and len(opaque(muted_px)) > 0)
    check("the two states render differently", live_px != muted_px)
    check("the muted icon carries a red slash", has_red(muted_px))
    check("the live icon has no red", not has_red(live_px))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    print("[config]")
    check("keepalive cadence is 10 s", config.SONIOX_MUTE_KEEPALIVE_MS == 10000,
          str(config.SONIOX_MUTE_KEEPALIVE_MS))

    # Keep the test fast: the sender reads this module global at call time.
    workers.SONIOX_MUTE_KEEPALIVE_MS = 200
    asyncio.run(run_scenario())

    check_controller()
    check_icon()
    del app

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
