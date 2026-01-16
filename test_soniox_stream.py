#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import signal

import numpy as np
import sounddevice as sd
import websockets
from dotenv import load_dotenv

load_dotenv()

SONIOX_API_KEY = os.environ.get("SONIOX_API_KEY")
if not SONIOX_API_KEY:
    print("ERROR: SONIOX_API_KEY not found in .env file")
    print("Please create a .env file with: SONIOX_API_KEY=\"your_api_key_here\"")
    sys.exit(1)

WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1024

running = True
audio_queue = None


def handle_sigint(sig, frame):
    global running
    running = False
    print("\n\nStopping...")


signal.signal(signal.SIGINT, handle_sigint)


def list_input_devices():
    print("\n=== Available Input Devices ===")
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            sr = int(dev.get("default_samplerate", 0))
            print(f"  [{idx}] {dev['name']} ({sr} Hz)")
    print()


async def soniox_client(audio_queue: asyncio.Queue):
    try:
        async with websockets.connect(WS_URL) as ws:
            print(f"Connected to {WS_URL}")
            
            config = {
                "api_key": SONIOX_API_KEY,
                "model": "stt-rt-v3",
                "audio_format": "pcm_s16le",
                "sample_rate": SAMPLE_RATE,
                "num_channels": CHANNELS,
                "enable_endpoint_detection": True,
            }
            
            await ws.send(json.dumps(config))
            print("Config sent, streaming audio...\n")

            async def sender():
                try:
                    while running:
                        try:
                            chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.5)
                            if chunk is None:
                                break
                            await ws.send(chunk)
                        except asyncio.TimeoutError:
                            continue
                    
                    print("Sender: Sending end-of-stream...")
                    await ws.send("")
                except Exception as e:
                    print(f"Sender error: {e}")

            async def receiver():
                try:
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            
                            if data.get("error_code"):
                                print(f"\n[ERROR] {data['error_code']}: {data.get('error_message', '')}")
                                break
                            
                            tokens = data.get("tokens", [])
                            if tokens:
                                final_tokens = [t for t in tokens if t.get("is_final")]
                                non_final_tokens = [t for t in tokens if not t.get("is_final")]
                                
                                if final_tokens:
                                    text = "".join(t.get("text", "") for t in final_tokens)
                                    print(f"[FINAL] {text}")
                                elif non_final_tokens:
                                    text = "".join(t.get("text", "") for t in non_final_tokens)
                                    print(f"[PART]  {text}", end="\r", flush=True)
                            
                            if data.get("finished"):
                                print("\n[Session finished]")
                                break
                                
                        except json.JSONDecodeError:
                            print(f"Non-JSON message: {msg[:100]}")
                except Exception as e:
                    print(f"Receiver error: {e}")

            await asyncio.gather(sender(), receiver())
            
    except websockets.exceptions.InvalidStatusCode as e:
        print(f"\nWebSocket connection failed: {e}")
        print("Check your API key and network connection")
    except Exception as e:
        print(f"\nConnection error: {e}")


async def main():
    global audio_queue
    
    list_input_devices()
    
    try:
        device_index = int(input("Select input device index (e.g., BlackHole): "))
    except (ValueError, EOFError):
        print("Invalid input")
        return

    device_info = sd.query_devices(device_index)
    print(f"\nUsing: {device_info['name']}")
    print(f"Sample rate: {SAMPLE_RATE} Hz, Channels: {CHANNELS}")
    print("Press Ctrl+C to stop\n")

    audio_queue = asyncio.Queue(maxsize=8)

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"Audio status: {status}", file=sys.stderr)
        
        pcm16 = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
        
        try:
            audio_queue.put_nowait(pcm16)
        except asyncio.QueueFull:
            pass

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=audio_callback,
            blocksize=BLOCK_SIZE,
            device=device_index,
        ):
            print("🎤 Capturing audio... Speak into your system audio!\n")
            await soniox_client(audio_queue)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        await audio_queue.put(None)
        print("\nDone.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
