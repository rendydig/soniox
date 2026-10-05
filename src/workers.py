import asyncio
import json
import queue
import os
import threading
import numpy as np
import sounddevice as sd
import websockets
from PySide6.QtCore import QThread, Signal
from src.config import SONIOX_API_KEY, WS_URL

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    pyaudio = None


class SonioxWorker(QThread):
    error = Signal(str, str)
    status = Signal(str, str)
    transcription_update = Signal(str, bool, str)
    translation_update = Signal(str, bool, str)

    def __init__(self, device, mode: str = "transcription", target_lang: str = "en", input_source: str = "host", parent=None):
        super().__init__(parent)
        self._mode = mode
        self._target_lang = target_lang
        self._input_source = input_source
        self._stop_flag = False
        self._channels = 1
        self._audio_queue = queue.Queue(maxsize=32)
        self._queue_overflow_count = 0
        self._stream = None
        self._pyaudio = None
        self._capture_thread = None

        if isinstance(device, dict) and device.get("backend") == "loopback":
            self._backend = "loopback"
            self._device_id = None
            self._loopback_index = device["index"]
            self._sample_rate = int(device["rate"])
        else:
            self._backend = "sounddevice"
            self._device_id = device
            self._loopback_index = None
            self._sample_rate = 16000

    def stop(self):
        self._stop_flag = True

    def _push_pcm(self, mono):
        pcm16 = np.clip(mono * 32767, -32768, 32767).astype(np.int16).tobytes()
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

    def _loopback_capture(self):
        while not self._stop_flag:
            try:
                data = self._stream.read(1024, exception_on_overflow=False)
            except Exception:
                break
            mono = np.frombuffer(data, dtype=np.float32).reshape(-1, 2)[:, 0]
            self._push_pcm(mono)

    def _is_wasapi_device(self):
        try:
            hostapi = sd.query_devices(self._device_id)["hostapi"]
            return "wasapi" in sd.query_hostapis(hostapi)["name"].lower()
        except Exception:
            return False

    def _open_input_stream(self, callback):
        kwargs = dict(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            callback=callback,
            blocksize=1024,
            device=self._device_id,
        )
        try:
            return sd.InputStream(**kwargs)
        except sd.PortAudioError:
            if not self._is_wasapi_device():
                raise
            kwargs["extra_settings"] = sd.WasapiSettings(auto_convert=True)
            return sd.InputStream(**kwargs)

    def _close_stream(self):
        if self._backend == "loopback":
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                except Exception:
                    pass
            if self._capture_thread is not None:
                self._capture_thread.join(timeout=3)
                self._capture_thread = None
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
            if self._pyaudio is not None:
                try:
                    self._pyaudio.terminate()
                except Exception:
                    pass
            self._stream = None
        elif self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def run(self):
        if not SONIOX_API_KEY:
            self.error.emit("SONIOX_API_KEY missing", self._input_source)
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._stream_audio())
        except Exception as e:
            self.error.emit(f"Worker error: {e}", self._input_source)
        finally:
            # Ensure stream closed exactly once from worker thread
            self._close_stream()
            loop.close()

    async def _stream_audio(self):
        async with websockets.connect(WS_URL) as ws:
            self.status.emit(f"Connected ({self._mode})", self._input_source)

            config = {
                "api_key": SONIOX_API_KEY,
                "model": "stt-rt-v5",
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
                        self._push_pcm(indata[:, 0])

                if self._backend == "loopback":
                    if pyaudio is None:
                        self.error.emit("PyAudioWPatch not installed", self._input_source)
                        return
                    self._pyaudio = pyaudio.PyAudio()
                    self._stream = self._pyaudio.open(
                        format=pyaudio.paFloat32,
                        channels=2,
                        rate=self._sample_rate,
                        input=True,
                        input_device_index=self._loopback_index,
                        frames_per_buffer=1024,
                    )
                    self._capture_thread = threading.Thread(target=self._loopback_capture, daemon=True)
                    self._capture_thread.start()
                else:
                    self._stream = self._open_input_stream(audio_callback)
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
                    # Don't close stream here; it is done in run()
                    pass

            async def receiver():
                async for msg in ws:
                    if self._stop_flag:
                        break
                    
                    data = json.loads(msg)
                    
                    if data.get("error_code"):
                        self.error.emit(f"{data['error_code']}: {data.get('error_message', '')}", self._input_source)
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
                            print(f"[DEBUG] [{self._input_source}] Final Transcription (English): {repr(final_transcription)}")
                            self.transcription_update.emit(final_transcription, True, self._input_source)
                        
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
                            print(f"[DEBUG] [{self._input_source}] Final Translation (Indonesian): {repr(final_translation)}")
                            self.translation_update.emit(final_translation, True, self._input_source)
                        
                        # Emit partial text (English - for live display)
                        part_text = "".join(t.get("text", "") for t in partial_tokens)
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False, self._input_source)
                        elif final_transcription_tokens or final_translation_tokens:
                            self.transcription_update.emit("", False, self._input_source)
                    
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
                            self.transcription_update.emit(final_text, True, self._input_source)
                        
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False, self._input_source)
                        elif final_text:
                            self.transcription_update.emit("", False, self._input_source)

            await asyncio.gather(sender(), receiver())


