import asyncio
import json
import queue
import os
from datetime import datetime
import numpy as np
import sounddevice as sd
import soundfile as sf
import websockets
from PySide6.QtCore import QThread, Signal
from src.config import SONIOX_API_KEY, WS_URL


class SonioxWorker(QThread):
    error = Signal(str)
    status = Signal(str)
    transcription_update = Signal(str, bool)

    def __init__(self, device_id: int, mode: str = "transcription", target_lang: str = "en", parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._mode = mode
        self._target_lang = target_lang
        self._stop_flag = False
        self._sample_rate = 16000
        self._channels = 1
        self._audio_queue = queue.Queue(maxsize=16)

    def stop(self):
        self._stop_flag = True

    def run(self):
        if not SONIOX_API_KEY:
            self.error.emit("SONIOX_API_KEY missing")
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._stream_audio())
        except Exception as e:
            self.error.emit(f"Worker error: {e}")
        finally:
            loop.close()

    async def _stream_audio(self):
        async with websockets.connect(WS_URL) as ws:
            self.status.emit(f"Connected ({self._mode})")

            config = {
                "api_key": SONIOX_API_KEY,
                "model": "stt-rt-v3",
                "audio_format": "pcm_s16le",
                "sample_rate": self._sample_rate,
                "num_channels": self._channels,
                "enable_endpoint_detection": True,
            }

            if self._mode == "translation":
                config["translation_options"] = {
                    "target_language": self._target_lang,
                    "mode": "one_way"
                }

            await ws.send(json.dumps(config))

            async def sender():
                def audio_callback(indata, frames, time_info, status):
                    if not self._stop_flag:
                        pcm16 = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
                        try:
                            self._audio_queue.put_nowait(pcm16)
                        except queue.Full:
                            pass

                with sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="float32",
                    callback=audio_callback,
                    blocksize=1024,
                    device=self._device_id,
                ):
                    while not self._stop_flag:
                        try:
                            chunk = self._audio_queue.get_nowait()
                            await ws.send(chunk)
                        except queue.Empty:
                            await asyncio.sleep(0.01)
                    await ws.send("")

            async def receiver():
                async for msg in ws:
                    data = json.loads(msg)
                    tokens = data.get("tokens", [])
                    
                    if not tokens:
                        continue

                    relevant_tokens = []
                    for t in tokens:
                        status = t.get("translation_status", "none")
                        
                        if self._mode == "translation":
                            if status == "translation":
                                relevant_tokens.append(t)
                        else:
                            if status in ["none", "original"]:
                                relevant_tokens.append(t)

                    if not relevant_tokens:
                        continue

                    final_text = "".join(t["text"] for t in relevant_tokens if t.get("is_final"))
                    part_text = "".join(t["text"] for t in relevant_tokens if not t.get("is_final"))

                    if final_text:
                        self.transcription_update.emit(final_text, True)
                    elif part_text:
                        self.transcription_update.emit(part_text, False)

            await asyncio.gather(sender(), receiver())


class RecorderWorker(QThread):
    error = Signal(str)
    status = Signal(str)
    saved = Signal(str)

    def __init__(self, device_id: int, samplerate: float, channels: int, filepath: str, parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._samplerate = int(samplerate)
        self._channels = channels
        self._filepath = filepath
        self._stop_flag = False
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=64)

    def stop(self):
        self._stop_flag = True

    def run(self):
        try:
            self.status.emit("Opening audio stream...")

            with sf.SoundFile(
                self._filepath,
                mode="w",
                samplerate=self._samplerate,
                channels=self._channels,
                subtype="PCM_16",
                format="WAV",
            ) as wav_file:

                def callback(indata, frames, time_info, status):
                    if status:
                        self.status.emit(f"Audio status: {status}")
                    try:
                        self._q.put_nowait(indata.copy())
                    except queue.Full:
                        pass

                with sd.InputStream(
                    samplerate=self._samplerate,
                    channels=self._channels,
                    device=self._device_id,
                    dtype="int16",
                    callback=callback,
                ):
                    self.status.emit("Recording...")
                    while not self._stop_flag or not self._q.empty():
                        try:
                            data = self._q.get(timeout=0.2)
                            wav_file.write(data)
                        except queue.Empty:
                            if self._stop_flag:
                                break
                            continue

            self.saved.emit(self._filepath)
        except Exception as e:
            self.error.emit(str(e))
