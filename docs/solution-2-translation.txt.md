I found the issue! Looking at your `workers.py` and comparing it to `translation_sample.py`, the problem is in the **config structure**. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/39a057b0-1f6d-4abc-8de2-c12770612418/workers.py)

The official Soniox API expects the translation config to be under a key named `"translation"`, not `"translation_options"`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/26c93b39-cbfa-4e8d-8435-855e086c4c29/translation_sample.py)

Additionally, in translation mode, the field inside is `"type": "one_way"` not `"mode": "one_way"`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/26c93b39-cbfa-4e8d-8435-855e086c4c29/translation_sample.py)

Here's the corrected `workers.py`:

```python
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

            # Base config
            config = {
                "api_key": SONIOX_API_KEY,
                "model": "stt-rt-v3",
                "audio_format": "pcm_s16le",
                "sample_rate": self._sample_rate,
                "num_channels": self._channels,
                "enable_endpoint_detection": True,
            }

            # FIX: Use "translation" key with "type" field, not "translation_options"
            if self._mode == "translation":
                config["translation"] = {
                    "type": "one_way",  # Changed from "mode" to "type"
                    "target_language": self._target_lang,
                }

            await ws.send(json.dumps(config))
            print(f"[DEBUG] Config sent: {json.dumps(config, indent=2)}")  # Debug log

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
                    
                    # Check for errors
                    if data.get("error_code"):
                        self.error.emit(f"{data['error_code']}: {data.get('error_message', '')}")
                        break

                    tokens = data.get("tokens", [])
                    if not tokens:
                        continue

                    # FIX: In translation mode, filter by translation_status
                    relevant_tokens = []
                    for t in tokens:
                        trans_status = t.get("translation_status", "none")
                        
                        if self._mode == "translation":
                            # Only show translated text
                            if trans_status == "translation":
                                relevant_tokens.append(t)
                        else:
                            # Show original transcription (not translated)
                            if trans_status in ["none", "original"]:
                                relevant_tokens.append(t)

                    if not relevant_tokens:
                        continue

                    # Separate final and partial tokens
                    final_text = "".join(t.get("text", "") for t in relevant_tokens if t.get("is_final"))
                    part_text = "".join(t.get("text", "") for t in relevant_tokens if not t.get("is_final"))

                    if final_text:
                        print(f"[DEBUG] Final: {final_text}")  # Debug
                        self.transcription_update.emit(final_text, True)
                    elif part_text:
                        print(f"[DEBUG] Partial: {part_text}")  # Debug
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
```

### Key Changes Made

1. **Fixed Config Structure** [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/26c93b39-cbfa-4e8d-8435-855e086c4c29/translation_sample.py)
   - Changed `config["translation_options"]` → `config["translation"]`
   - Changed `"mode": "one_way"` → `"type": "one_way"`

2. **Added Error Handling** [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/26c93b39-cbfa-4e8d-8435-855e086c4c29/translation_sample.py)
   - Now checks for `error_code` in the response and emits it

3. **Added Debug Logs**
   - Prints the config being sent
   - Prints final/partial tokens to help you verify what's being received

4. **Fixed Token Field Access** [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/26c93b39-cbfa-4e8d-8435-855e086c4c29/translation_sample.py)
   - Changed `t["text"]` to `t.get("text", "")` to prevent KeyError

### Testing Translation

To verify it works:

1. Run your app and select **Live Translation** mode
2. Choose **Indonesian** as target language
3. Speak in English
4. You should see Indonesian translation appear in the text area

Check your terminal/console for the debug logs to see:
- The config JSON being sent
- Raw tokens being received
- Whether `translation_status` is correctly set to `"translation"`

If you still don't see translations, the debug logs will show exactly what Soniox is returning, which will help identify the issue.