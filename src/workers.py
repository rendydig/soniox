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
    translation_update = Signal(str, bool)

    def __init__(self, device_id: int, mode: str = "transcription", target_lang: str = "en", parent=None):
        super().__init__(parent)
        self._device_id = device_id
        self._mode = mode
        self._target_lang = target_lang
        self._stop_flag = False
        self._sample_rate = 16000
        self._channels = 1
        self._audio_queue = queue.Queue(maxsize=32)
        self._queue_overflow_count = 0
        self._stream = None

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
                config["translation"] = {
                    "type": "one_way",
                    "target_language": self._target_lang,
                }

            await ws.send(json.dumps(config))
            print(f"[DEBUG] Config sent: {json.dumps(config, indent=2)}")

            async def sender():
                def audio_callback(indata, frames, time_info, status):
                    if not self._stop_flag:
                        pcm16 = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
                        try:
                            self._audio_queue.put_nowait(pcm16)
                            self._queue_overflow_count = 0
                        except queue.Full:
                            self._queue_overflow_count += 1
                            if self._queue_overflow_count > 50:
                                while self._audio_queue.qsize() > 16:
                                    try:
                                        self._audio_queue.get_nowait()
                                    except queue.Empty:
                                        break
                                self._queue_overflow_count = 0

                self._stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="float32",
                    callback=audio_callback,
                    blocksize=1024,
                    device=self._device_id,
                )
                self._stream.start()
                try:
                    while not self._stop_flag:
                        try:
                            chunk = self._audio_queue.get_nowait()
                            await ws.send(chunk)
                        except queue.Empty:
                            await asyncio.sleep(0.01)
                    await ws.send("")
                finally:
                    if self._stream is not None:
                        try:
                            self._stream.stop()
                            self._stream.close()
                        except:
                            pass
                        self._stream = None

            async def receiver():
                async for msg in ws:
                    if self._stop_flag:
                        break
                    
                    data = json.loads(msg)
                    
                    if data.get("error_code"):
                        self.error.emit(f"{data['error_code']}: {data.get('error_message', '')}")
                        break

                    tokens = data.get("tokens", [])
                    if not tokens:
                        continue
                    
                    if self._mode == "translation":
                        # In translation mode, emit both transcription and translation
                        
                        # Final transcription (English - original)
                        final_transcription_tokens = [
                            t for t in tokens 
                            if t.get("is_final") and t.get("translation_status") != "translation"
                        ]
                        
                        # Final translation (Indonesian - translated)
                        final_translation_tokens = [
                            t for t in tokens 
                            if t.get("is_final") and t.get("translation_status") == "translation"
                        ]
                        
                        # Partial tokens (English - for live display)
                        partial_tokens = [
                            t for t in tokens 
                            if not t.get("is_final")
                        ]
                        
                        # Emit final transcription (English)
                        if final_transcription_tokens:
                            text_parts = []
                            for t in final_transcription_tokens:
                                token_text = t.get("text", "")
                                if token_text == "<end>":
                                    text_parts.append("\n")
                                else:
                                    text_parts.append(token_text)
                            final_transcription = "".join(text_parts)
                            print(f"[DEBUG] Final Transcription (English): {repr(final_transcription)}")
                            self.transcription_update.emit(final_transcription, True)
                        
                        # Emit final translation (Indonesian)
                        if final_translation_tokens:
                            text_parts = []
                            for t in final_translation_tokens:
                                token_text = t.get("text", "")
                                if token_text == "<end>":
                                    text_parts.append("\n")
                                else:
                                    text_parts.append(token_text)
                            final_translation = "".join(text_parts)
                            print(f"[DEBUG] Final Translation (Indonesian): {repr(final_translation)}")
                            self.translation_update.emit(final_translation, True)
                        
                        # Emit partial text (English - for live display)
                        part_text = "".join(t.get("text", "") for t in partial_tokens)
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False)
                        elif final_transcription_tokens or final_translation_tokens:
                            self.transcription_update.emit("", False)
                    
                    else:
                        # Transcription mode - original behavior
                        final_tokens = [
                            t for t in tokens 
                            if t.get("is_final")
                        ]

                        partial_tokens = [
                            t for t in tokens 
                            if not t.get("is_final")
                        ]

                        if final_tokens:
                            text_parts = []
                            for t in final_tokens:
                                token_text = t.get("text", "")
                                if token_text == "<end>":
                                    text_parts.append("\n")
                                else:
                                    text_parts.append(token_text)
                            final_text = "".join(text_parts)
                        else:
                            final_text = ""
                        
                        part_text = "".join(t.get("text", "") for t in partial_tokens)

                        if final_text:
                            self.transcription_update.emit(final_text, True)
                        
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False)
                        elif final_text:
                            self.transcription_update.emit("", False)

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
        self._stream = None

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

                self._stream = sd.InputStream(
                    samplerate=self._samplerate,
                    channels=self._channels,
                    device=self._device_id,
                    dtype="int16",
                    callback=callback,
                )
                self._stream.start()
                try:
                    self.status.emit("Recording...")
                    while not self._stop_flag or not self._q.empty():
                        try:
                            data = self._q.get(timeout=0.2)
                            wav_file.write(data)
                        except queue.Empty:
                            if self._stop_flag:
                                break
                            continue
                finally:
                    if self._stream is not None:
                        try:
                            self._stream.stop()
                            self._stream.close()
                        except:
                            pass
                        self._stream = None

            self.saved.emit(self._filepath)
        except Exception as e:
            self.error.emit(str(e))


