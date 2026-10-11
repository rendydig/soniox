"""Child process: capture an audio device and stream raw PCM to stdout.

Run by ``SonioxWorker`` (``src/workers.py``) as a **separate process** so that a
native crash in the audio stack (PortAudio via sounddevice, or PyAudioWPatch's
WASAPI loopback) — an access violation, which cannot be caught in Python — kills
only this process; the parent detects the exit and restarts it, keeping the app
alive. Both the host (microphone) and speaker (loopback) captures run here.

Protocol (all on the child's stdio):
  * stdin  — one JSON line, e.g.
      {"backend": "loopback", "index": 66, "rate": 48000}
      {"backend": "sounddevice", "device": 1, "rate": 16000, "channels": 1}
  * stdout — raw little-endian int16 **mono** PCM at ``rate`` (nothing else!)
  * stderr — diagnostics (the parent redirects these to a log file)

The parent stops the child by terminating it (safe: separate process).
"""

import json
import sys

import numpy as np

FRAMES_PER_BUFFER = 1024


def _open_loopback(cfg):
    """WASAPI loopback endpoint via PyAudioWPatch (Windows)."""
    import pyaudiowpatch as pyaudio

    rate = int(cfg["rate"])
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paFloat32,
        channels=2,
        rate=rate,
        input=True,
        input_device_index=int(cfg["index"]),
        frames_per_buffer=FRAMES_PER_BUFFER,
    )

    def read():
        data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
        return np.frombuffer(data, dtype=np.float32).reshape(-1, 2)[:, 0]

    def close():
        for fn in (stream.stop_stream, stream.close, pa.terminate):
            try:
                fn()
            except Exception:
                pass

    return read, close


def _open_sounddevice(cfg):
    """Microphone / virtual input via sounddevice (PortAudio)."""
    import sounddevice as sd

    kwargs = dict(
        samplerate=int(cfg["rate"]),
        channels=int(cfg.get("channels", 1)),
        dtype="float32",
        device=cfg.get("device"),
        blocksize=FRAMES_PER_BUFFER,
    )
    try:
        stream = sd.InputStream(**kwargs)
    except sd.PortAudioError:
        # Mirror SonioxWorker._open_input_stream: WASAPI devices (e.g. Stereo
        # Mix) may reject 16 kHz; retry with auto_convert.
        hostapi = sd.query_devices(kwargs["device"])["hostapi"]
        if "wasapi" not in sd.query_hostapis(hostapi)["name"].lower():
            raise
        kwargs["extra_settings"] = sd.WasapiSettings(auto_convert=True)
        stream = sd.InputStream(**kwargs)
    stream.start()

    def read():
        data, _overflowed = stream.read(FRAMES_PER_BUFFER)
        return data[:, 0]

    def close():
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    return read, close


def main() -> int:
    line = sys.stdin.readline()
    if not line:
        print("no config received on stdin", file=sys.stderr, flush=True)
        return 2

    cfg = json.loads(line)
    backend = cfg.get("backend", "loopback")
    read, close = _open_loopback(cfg) if backend == "loopback" else _open_sounddevice(cfg)

    out = sys.stdout.buffer
    try:
        while True:
            mono = read()
            pcm16 = np.clip(mono * 32767, -32768, 32767).astype(np.int16).tobytes()
            out.write(pcm16)
            out.flush()
    except Exception as e:
        # Report and exit; the parent restarts us.
        print(f"{backend} capture error: {e}", file=sys.stderr, flush=True)
        return 1
    finally:
        close()


if __name__ == "__main__":
    sys.exit(main())
