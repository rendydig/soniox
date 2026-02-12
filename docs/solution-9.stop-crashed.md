You’re right about the double-close risk, and your `stop()` changes are in the right direction, but there are still two important issues to fix: ensuring the stream is only stopped/closed once in all code paths, and ensuring the WAV file actually gets audio written before the worker exits. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

## 1. Make stream closing single‑owner

Right now, both `stop()` and the `finally` blocks may try to stop/close the same `sd.InputStream`, even though you’re setting `_stream = None` in `stop()`. In concurrent code, it’s safer to make *one* place responsible for closing the stream and let `stop()` only signal termination. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

**Recommended pattern:**

### SonioxWorker

```python
class SonioxWorker(QThread):
    ...

    def stop(self):
        # Only signal loop to end; do NOT touch the stream here
        self._stop_flag = True

    async def _stream_audio(self):
        async with websockets.connect(WS_URL) as ws:
            ...
            async def sender():
                def audio_callback(indata, frames, time_info, status):
                    if not self._stop_flag:
                        pcm16 = np.clip(indata[:, 0] * 32767, -32768, 32767).astype(np.int16).tobytes()
                        try:
                            self._audio_queue.put_nowait(pcm16)
                            self._queue_overflow_count = 0
                        except queue.Full:
                            ...
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
                    # when _stop_flag is set, exit loop and fall through
                finally:
                    if self._stream is not None:
                        try:
                            self._stream.stop()
                            self._stream.close()
                        except:
                            pass
                        self._stream = None

            async def receiver():
                ...
            await asyncio.gather(sender(), receiver())
``` 

Key idea: `stop()` just flips `_stop_flag`; the `sender()`’s `finally` owns closing the stream. No double-close, no race. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

### RecorderWorker

Same pattern for `RecorderWorker`:

```python
class RecorderWorker(QThread):
    ...

    def stop(self):
        # Only signal termination
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
``` 

Again, `stop()` only sets `_stop_flag`; the `finally` closes the stream and sets it to `None`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

## 2. Fix empty/corrupted WAV files

The empty/corrupted file symptom usually comes from the worker exiting before the queue is drained or from stopping/closing the stream before final buffers are written. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

The current logic:

- Uses `while not self._stop_flag or not self._q.empty()` which is correct, but if `stop()` closes the stream early, the callback stops pushing samples and you may end up with very few frames. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)
- If `stop()` is called and also closes the stream right away, the callback will never run again, so you rely only on whatever is already in the queue. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

With the new pattern above:

- `stop()` just sets `_stop_flag`, so:
  - Input stream still runs until the loop finishes draining the queue (or until `_stop_flag` and `queue.Empty` break).
  - You don’t prematurely close the stream inside `stop()`, so no double-free and better chance of capturing tail audio. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

If you still get near‑empty files, you can:

- Increase `queue.Queue(maxsize=64)` to something like 256 for safety. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)
- Ensure you always wait for the worker to finish in the controller before reusing the device:

```python
# recording_controller.py
def stop_recording(self):
    if self._recorder_worker is not None:
        self._recorder_worker.stop()
        self.status_changed.emit("Stopping...")
        # Optionally: wait in a background-safe way, or rely on signals
``` 

## 3. Summary of what to change

1. In **both** `SonioxWorker` and `RecorderWorker`:
   - `stop()` should only set `_stop_flag`.
   - All `stop()/close()` calls on `_stream` should live in one `finally` block that checks `if self._stream is not None` and sets it to `None` afterwards. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)
2. Do not close the stream inside `stop()`; that’s what was causing PortAudio’s double-free. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)
3. Keep the draining loop (`while not _stop_flag or not queue.empty()`) intact so the WAV file gets all buffered audio written before the worker exits. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/7566a8e2-57a9-48b5-be68-f3682b4fb2b4/workers.py)

If you want, you can paste your updated `workers.py` and I can inline-edit it so you can drop it back into the project without further tweaking.