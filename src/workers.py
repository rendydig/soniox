import asyncio
import json
import queue
import os
import logging
import subprocess
import sys
import threading
import time
import numpy as np
import sounddevice as sd
import websockets
from PySide6.QtCore import QThread, Signal
from src.config import (
    SONIOX_API_KEY,
    WS_URL,
    SONIOX_MAX_ENDPOINT_DELAY_MS,
    SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL,
    SONIOX_ENDPOINT_SENSITIVITY,
    SONIOX_MUTE_KEEPALIVE_MS,
)
from src.hub.publisher import HubPublisher

logger = logging.getLogger(__name__)

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    pyaudio = None

# Audio capture (both host/microphone and speaker/loopback) runs in a child
# process (src/audio_capture_process.py) because the audio stack can hit a native
# access violation — PortAudio via sounddevice, or PyAudioWPatch's WASAPI loopback
# when a Bluetooth endpoint is reconfigured (A2DP<->HFP) — which cannot be caught
# in Python and would otherwise kill the whole app. The parent restarts the child
# on exit, so the app survives.
_CAPTURE_CHILD_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "audio_capture_process.py"
)
_CAPTURE_CHILD_LOG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "audio-capture.log"
)
_CAPTURE_MAX_RESTARTS = 5
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Used when no hub publisher was injected: every publish is a no-op, so the
# worker's hot path has no branch on hub availability.
_NULL_HUB = HubPublisher(None)


class SonioxWorker(QThread):
    error = Signal(str, str)
    status = Signal(str, str)
    transcription_update = Signal(str, bool, str, bool)
    translation_update = Signal(str, bool, str)

    def __init__(self, device, mode: str = "transcription", target_lang: str = "en", input_source: str = "host", parent=None, hub=None):
        super().__init__(parent)
        self._mode = mode
        self._target_lang = target_lang
        self._input_source = input_source
        # Dual-write: the hub receives every finalized line as well as every
        # partial, in addition to the Qt signals that still drive the UI. The
        # publisher is thread-safe and a no-op when the hub is unreachable, so
        # nothing here can fail the audio path.
        self._hub = hub or _NULL_HUB
        self._stop_flag = False
        # Soft mute: set from the Qt thread, read from this worker's asyncio
        # loop (lock-free, like _stop_flag). While set, the sender drops audio
        # and only emits keepalives, so the capture stream never restarts.
        self._muted = False
        self._channels = 1
        self._audio_queue = queue.Queue(maxsize=32)
        self._queue_overflow_count = 0
        self._stream = None
        self._pyaudio = None
        self._capture_thread = None
        self._child = None
        self._child_restarts = 0

        if isinstance(device, dict) and device.get("backend") == "loopback":
            # Windows: WASAPI loopback endpoint, read through PyAudioWPatch.
            self._backend = "loopback"
            self._device_id = None
            self._loopback_index = device["index"]
            self._sample_rate = int(device["rate"])
        elif isinstance(device, dict) and device.get("backend") == "input":
            # macOS: system audio captured from a virtual input device (BlackHole)
            # through PortAudio, at the device's native rate.
            self._backend = "sounddevice"
            self._device_id = device["index"]
            self._loopback_index = None
            self._sample_rate = int(device.get("rate") or 16000)
        else:
            self._backend = "sounddevice"
            self._device_id = device
            self._loopback_index = None
            self._sample_rate = 16000

    def stop(self):
        self._stop_flag = True

    def set_muted(self, muted: bool):
        """Stop (or resume) sending this worker's audio to Soniox.

        Soft mute: the capture stream keeps running and the Soniox session is
        held open with periodic keepalives, so unmuting resumes instantly with
        no audio-stack restart (and the device is never taken exclusively).
        """
        self._muted = bool(muted)

    # --- hub publishing (dual-write) ----------------------------------

    def _publish_partial(self, text: str):
        """Publish a live partial: disposable, superseded by the next one."""
        self._hub.transcription_partial(self._input_source, text)

    def _publish_final(self, text: str, endpoint: bool = False):
        """Publish a finalized line (the hub derives the conversation from these)."""
        self._hub.transcription_final(self._input_source, text, endpoint=endpoint)

    def _publish_translation(self, text: str):
        """Publish a finalized translation."""
        self._hub.translation_final(self._input_source, text)

    def _enqueue_pcm(self, pcm16: bytes):
        """Queue a raw int16 mono chunk, shedding the backlog if it overflows."""
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

    def _push_pcm(self, mono):
        self._enqueue_pcm(np.clip(mono * 32767, -32768, 32767).astype(np.int16).tobytes())

    def _spawn_capture_child(self):
        """Start the isolated capture process for this worker's device; Popen or None."""
        try:
            os.makedirs(os.path.dirname(_CAPTURE_CHILD_LOG), exist_ok=True)
            log_file = open(_CAPTURE_CHILD_LOG, "ab")
        except OSError:
            log_file = subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", _CAPTURE_CHILD_SCRIPT],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log_file,
                bufsize=0,
                creationflags=_CREATE_NO_WINDOW,
            )
        except OSError as e:
            logger.error("Failed to start %s capture process: %s", self._backend, e)
            return None
        cfg = {
            "backend": self._backend,
            "rate": self._sample_rate,
            "channels": self._channels,
            "frames_per_buffer": 1024,
        }
        if self._backend == "loopback":
            cfg["index"] = self._loopback_index
        else:
            cfg["device"] = self._device_id
        try:
            proc.stdin.write(json.dumps(cfg).encode("utf-8") + b"\n")
            proc.stdin.flush()
        except OSError as e:
            logger.error("Failed to configure capture process: %s", e)
            proc.terminate()
            return None
        return proc

    def _read_child_stdout(self, proc):
        """Forward the child's raw PCM to the audio queue until it exits."""
        out = proc.stdout
        while not self._stop_flag:
            try:
                chunk = out.read(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            self._enqueue_pcm(chunk)

    def _capture_supervisor(self):
        """Own the capture child: (re)start it and restart it if it crashes."""
        while not self._stop_flag:
            proc = self._spawn_capture_child()
            if proc is None:
                logger.warning("Falling back to in-process %s capture", self._backend)
                self._in_process_capture()
                return
            self._child = proc
            reader = threading.Thread(
                target=self._read_child_stdout, args=(proc,), daemon=True
            )
            reader.start()
            proc.wait()  # returns when the child exits (crash or stop)
            reader.join(timeout=1)
            self._child = None
            if self._stop_flag:
                return
            self._child_restarts += 1
            logger.warning(
                "%s capture process exited (code=%s); restart %d/%d",
                self._backend, proc.returncode, self._child_restarts,
                _CAPTURE_MAX_RESTARTS,
            )
            if self._child_restarts > _CAPTURE_MAX_RESTARTS:
                # Give up on this capture but keep the rest of the session alive:
                # setting the stop flag ends this worker only.
                logger.error("%s capture keeps crashing; stopping it", self._backend)
                self.status.emit("Audio capture failed repeatedly; stopped",
                                 self._input_source)
                self._stop_flag = True
                return
            delay = min(1.0 * self._child_restarts, 3.0)
            deadline = time.time() + delay
            while time.time() < deadline and not self._stop_flag:
                time.sleep(0.1)

    def _in_process_capture(self):
        """Fallback used only if the isolated capture process cannot start."""
        if self._backend == "loopback":
            self._in_process_loopback_capture()
            return

        def callback(indata, frames, time_info, status):
            if not self._stop_flag:
                self._push_pcm(indata[:, 0])

        try:
            self._stream = self._open_input_stream(callback)
            self._stream.start()
        except Exception as e:
            self.error.emit(f"Failed to open input stream: {e}", self._input_source)
            return
        while not self._stop_flag:
            time.sleep(0.1)

    def _in_process_loopback_capture(self):
        if pyaudio is None:
            self.error.emit("PyAudioWPatch not installed", self._input_source)
            return
        try:
            self._pyaudio = pyaudio.PyAudio()
            self._stream = self._pyaudio.open(
                format=pyaudio.paFloat32,
                channels=2,
                rate=self._sample_rate,
                input=True,
                input_device_index=self._loopback_index,
                frames_per_buffer=1024,
            )
        except Exception as e:
            self.error.emit(f"Failed to open loopback stream: {e}", self._input_source)
            return
        self._loopback_capture()

    def _loopback_capture(self):
        while not self._stop_flag:
            try:
                data = self._stream.read(1024, exception_on_overflow=False)
            except Exception as e:
                # A read failure is expected on shutdown (the stream is being
                # stopped); log it only if we were not asked to stop.
                if not self._stop_flag:
                    logger.warning("Loopback capture read failed: %s", e)
                break
            mono = np.frombuffer(data, dtype=np.float32).reshape(-1, 2)[:, 0]
            self._push_pcm(mono)

    def _stop_capture_child(self):
        """Terminate the isolated capture process (safe: a separate process)."""
        proc = self._child
        self._child = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass

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
        # Preferred path: the isolated capture process owns the stream; stop it
        # first (terminating a separate process can't corrupt this one).
        self._stop_capture_child()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=3)
            if self._capture_thread.is_alive():
                # The in-process fallback's read is still blocking; closing the
                # stream under it would free its buffers and crash the process.
                # Leak it instead — the worker is being torn down anyway.
                logger.warning(
                    "%s capture thread did not stop; skipping stream close to "
                    "avoid a native crash", self._backend
                )
                self._stream = None
                self._capture_thread = None
                return
            self._capture_thread = None
        # Close the in-process fallback stream, if one was ever opened.
        if self._stream is not None:
            try:
                if self._backend == "loopback":
                    self._stream.stop_stream()
                    self._stream.close()
                else:
                    self._stream.stop()
                    self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None

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
                "max_endpoint_delay_ms": SONIOX_MAX_ENDPOINT_DELAY_MS,
                "endpoint_latency_adjustment_level": SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL,
                "endpoint_sensitivity": SONIOX_ENDPOINT_SENSITIVITY,
            }

            if self._mode == "translation":
                config["translation"] = {
                    "type": "one_way",
                    "target_language": self._target_lang,
                }

            await ws.send(json.dumps(config))
            logger.debug("Config sent: %s", json.dumps(config, indent=2))

            async def sender():
                if self._backend == "loopback" and pyaudio is None:
                    self.error.emit("PyAudioWPatch not installed", self._input_source)
                    return
                # Capture in an isolated process (restarted on crash) so a native
                # audio-stack fault can't take the app down.
                self._capture_thread = threading.Thread(
                    target=self._capture_supervisor, daemon=True
                )
                self._capture_thread.start()
                keepalive_s = SONIOX_MUTE_KEEPALIVE_MS / 1000.0
                last_keepalive = time.monotonic()
                try:
                    while not self._stop_flag:
                        try:
                            chunk = self._audio_queue.get_nowait()
                        except queue.Empty:
                            chunk = None
                        if self._muted:
                            # Keep draining (so the queue can't back up) but send
                            # nothing except the keepalive Soniox needs to hold an
                            # idle stream open. Text JSON frame, never binary.
                            if time.monotonic() - last_keepalive >= keepalive_s:
                                await ws.send(json.dumps({"type": "keepalive"}))
                                last_keepalive = time.monotonic()
                            await asyncio.sleep(0.01)
                            continue
                        last_keepalive = time.monotonic()
                        if chunk is not None:
                            await ws.send(chunk)
                        else:
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
                            # <end> may be tagged as a translation token, so scan all finals.
                            endpoint = any(t.get("text") == "<end>" for t in tokens if t.get("is_final"))
                            text_parts = []
                            for t in final_transcription_tokens:
                                token_text = t.get("text", "")
                                if token_text == "<end>":
                                    text_parts.append("\n")
                                else:
                                    text_parts.append(token_text)
                            final_transcription = "".join(text_parts)
                            logger.debug("[%s] Final Transcription (English): %r", self._input_source, final_transcription)
                            self.transcription_update.emit(final_transcription, True, self._input_source, endpoint)
                            self._publish_final(final_transcription, endpoint)
                        
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
                            logger.debug("[%s] Final Translation (Indonesian): %r", self._input_source, final_translation)
                            self.translation_update.emit(final_translation, True, self._input_source)
                            self._publish_translation(final_translation)
                        
                        # Emit partial text (English - for live display)
                        part_text = "".join(t.get("text", "") for t in partial_tokens)
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False, self._input_source, False)
                            self._publish_partial(part_text)
                        elif final_transcription_tokens or final_translation_tokens:
                            self.transcription_update.emit("", False, self._input_source, False)
                    
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
                            endpoint = False
                            for t in final_tokens:
                                token_text = t.get("text", "")
                                if token_text == "<end>":
                                    endpoint = True
                                    text_parts.append("\n")
                                else:
                                    text_parts.append(token_text)
                            final_text = "".join(text_parts)
                        else:
                            final_text = ""
                            endpoint = False
                        
                        part_text = "".join(t.get("text", "") for t in partial_tokens)

                        if final_text:
                            self.transcription_update.emit(final_text, True, self._input_source, endpoint)
                            self._publish_final(final_text, endpoint)
                        
                        if part_text.strip():
                            self.transcription_update.emit(part_text, False, self._input_source, False)
                            self._publish_partial(part_text)
                        elif final_text:
                            self.transcription_update.emit("", False, self._input_source, False)

            await asyncio.gather(sender(), receiver())


