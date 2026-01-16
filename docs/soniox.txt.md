You can build this in two layers:  
1) capture macOS system/output audio as raw PCM,  
2) stream that PCM over WebSocket to Soniox’s real‑time API and print tokens as they arrive. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)

Below is a concrete, minimal tutorial tailored for your use case.

***

## 1. High‑level architecture

You will:

- Use a “virtual loopback” device (e.g. BlackHole or Loopback) to route macOS system audio into a Python process as if it were a microphone.  
- Capture raw PCM frames with a Python audio library (e.g. `sounddevice` or `pyaudio`).  
- Open a WebSocket connection to `wss://stt-rt.soniox.com/transcribe-websocket`. [soniox](https://soniox.com/docs/llms.txt)
- Send a JSON config message once, then stream binary audio chunks. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)
- Read token responses, printing `is_final` tokens as stable transcript. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)

***

## 2. macOS audio setup (output → input)

1. Install a virtual audio device (free BlackHole example):  
   - `brew install blackhole-2ch` (or follow their README GUI installer).  
2. In **Audio MIDI Setup**:  
   - Create a “Multi‑Output Device” or “Aggregate Device” if needed so your Mac speakers and BlackHole both receive audio.  
3. In **System Settings → Sound → Output**:  
   - Select the device that sends audio to BlackHole (e.g. “Multi‑Output Device”).  
4. In Python, you will then open the **input** device that corresponds to BlackHole, so you capture whatever the system plays.

This step is independent of Soniox and just ensures your script sees system audio as a mono/16‑kHz PCM stream.

***

## 3. Python dependencies and env

Install:

```bash
pip install websockets sounddevice numpy
```

Export your API key (from Soniox console): [soniox](https://soniox.com/docs/llms.txt)

```bash
export SONIOX_API_KEY="YOUR_API_KEY"
```

You’ll stream raw PCM, so configure Soniox with `audio_format`, `sample_rate`, `num_channels`. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)

***

## 4. Minimal real‑time client (Python)

This example:

- Captures mono 16‑kHz `int16` from a selected input device.  
- Connects to Soniox real‑time WebSocket.  
- Sends config (model, audio format).  
- Streams binary chunks.  
- Prints partial vs final text. [soniox](https://soniox.com/docs/llms.txt)

```python
import asyncio
import json
import os
import signal
import sys

import numpy as np
import sounddevice as sd
import websockets

SONIOX_API_KEY = os.environ.get("SONIOX_API_KEY")
if not SONIOX_API_KEY:
    print("Please set SONIOX_API_KEY env var")
    sys.exit(1)

WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1024  # frames per block, tweak for latency vs overhead

running = True

def handle_sigint(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, handle_sigint)

def list_input_devices():
    print("Available input devices:")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            print(f"{idx}: {dev['name']}")

async def soniox_client(audio_queue: asyncio.Queue):
    async with websockets.connect(WS_URL) as ws:
        # 1) Send config message
        config = {
            "api_key": SONIOX_API_KEY,
            "model": "stt-rt-v3",  # current RT model name [web:8]
            "audio_format": "pcm_s16le",
            "sample_rate": SAMPLE_RATE,
            "num_channels": CHANNELS,
            "enable_endpoint_detection": True,
            # optional hints:
            # "language_hints": ["en"],
        }
        await ws.send(json.dumps(config))

        async def sender():
            while running:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                await ws.send(chunk)
            # signal end of stream
            await ws.send("")  # empty message as EOS [web:8]

        async def receiver():
            async for msg in ws:
                data = json.loads(msg)
                # Each message may contain tokens
                tokens = data.get("tokens", [])
                if not tokens:
                    continue
                text = "".join(t["value"] for t in tokens)
                is_final = all(t.get("is_final", False) for t in tokens)
                if is_final:
                    print(f"[FINAL] {text}")
                else:
                    print(f"[PART]  {text}", end="\r", flush=True)

        await asyncio.gather(sender(), receiver())

async def main():
    list_input_devices()
    device_index = int(input("Select input device index (BlackHole / loopback): "))

    audio_queue: asyncio.Queue = asyncio.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        # Convert float32 [-1,1) from sounddevice to int16 PCM
        pcm16 = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        # Use asyncio-friendly put_nowait
        try:
            audio_queue.put_nowait(pcm16)
        except asyncio.QueueFull:
            pass

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="float32",
        callback=audio_callback,
        blocksize=BLOCK_SIZE,
        device=device_index,
    ):
        print("Capturing audio... Ctrl+C to stop.")
        await soniox_client(audio_queue)

    await audio_queue.put(None)

if __name__ == "__main__":
    asyncio.run(main())
```

Key points aligned with Soniox docs and examples: [github](https://github.com/soniox/soniox_examples)

- Uses the WebSocket endpoint with a JSON config followed by raw PCM audio frames.  
- Specifies `audio_format: "pcm_s16le"`, `sample_rate: 16000`, `num_channels: 1` as required for raw audio. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)
- Handles token streams where each token has `value` and `is_final`. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)
- Sends an empty string at the end to finalize the stream, similar to pseudo‑code in their `llms.txt`. [soniox](https://soniox.com/docs/llms.txt)

***

## 5. Mapping to official `soniox_realtime.py`

The official example repo `soniox_examples` has a Python real‑time script that: [github](https://github.com/soniox/soniox_examples)

- Reads from a file or microphone,  
- Opens a WebSocket to the same endpoint,  
- Sends config and audio,  
- Prints streaming results.

Your adaptation mainly replaces their audio source with:

- The `sounddevice` loopback stream shown above, or  
- Any other macOS capture mechanism producing PCM chunks.

If you prefer, you can:

1. Clone the repo. [github](https://github.com/soniox/soniox_examples)
2. Inspect `speech_to_text/python/soniox_realtime.py` and identify their “read audio and send chunk” part.  
3. Swap their `audio_file.read(...)` with frames from `sounddevice` (same format: `pcm_s16le` at `16 kHz`, mono) and keep the rest of the logic.

***

If you want, next step can be: refine this into a small “library‑style” module plus a demo script, or add features like language hints, diarization, or endpoint‑driven manual `{"type": "finalize"}` for stricter utterance boundaries. [soniox](https://soniox.com/docs/stt/rt/real-time-transcription)