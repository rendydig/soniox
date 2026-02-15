The crash is happening inside PortAudio/CoreAudio (used by `sounddevice`) and is very likely caused by the way streams are opened/closed and threads are cleaned up in your code, not by your Python logic directly. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/99c7da34-0ba3-4a8b-b4b4-d9683c902340/workers.py)

## Where it is most likely coming from

Looking at your code:

- You have `SonioxWorker` and `RecorderWorker`, both subclasses of `QThread`, each creating their own `sd.InputStream`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/99c7da34-0ba3-4a8b-b4b4-d9683c902340/workers.py)
- You sometimes run two input streams at once (host + speaker) from the same process and from different threads. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/e869ff28-13a8-4811-a375-a9e0335dc3d6/recording_controller.py)
- On errors or stop, you do a mix of:
  - calling `self.stream.stop()` and `self.stream.close()` inside the callback/loop,
  - calling `self.stop()` from outside,
  - calling `deleteLater()` on the QThread objects from different places. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/b74525d5-0c53-4f3a-adf6-dd27d1a259a7/transcription_controller.py)

On macOS, PortAudio with CoreAudio is very sensitive to multi‑thread and multi‑stream misuse; running multiple input streams in different threads and stopping/closing them from multiple places can lead to double‑free or “!obj” AUHAL errors. That matches your `PaMacCore (AUHAL) ... !obj` plus `malloc: Double free of object` crash. [blog.csdn](https://blog.csdn.net/normanbeita/article/details/106499473)

## Concrete fixes to try in your code

Below are the minimal, surgical changes you can apply.

### 1. Ensure each `InputStream` is closed exactly once, from the same thread

In both `SonioxWorker` and `RecorderWorker`, remove extra `stop/close` calls and centralize cleanup in one place.

In `SonioxWorker`:

```python
class SonioxWorker(QThread):
    # ...

    def stop(self):
        self.stopflag = True

    def run(self):
        if not SONIOX_API_KEY:
            self.error.emit("SONIOX_API_KEY missing", self.inputsource)
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.streamaudio())
        except Exception as e:
            self.error.emit(f"Worker error {e}", self.inputsource)
        finally:
            # Ensure stream closed exactly once from worker thread
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            loop.close()

    async def streamaudio(self):
        # ...
        def audiocallback(indata, frames, timeinfo, status):
            if self.stopflag:
                return   # do NOT stop/close stream here
            # existing queue logic...

        self.stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype='float32',
            callback=audiocallback,
            blocksize=1024,
            device=self.deviceid,
        )
        self.stream.start()

        try:
            while not self.stopflag:
                # sending loop...
                await asyncio.sleep(0.01)
        finally:
            # don't close stream here; it is done in run()
            pass
```

Key ideas:

- `stop()` only flips a flag, it does not touch `self.stream`.
- Only `run()` (the worker thread) stops/closes `self.stream` in `finally`.
- No `stop/close` calls inside callbacks or from other threads.

Apply the same pattern to `RecorderWorker`:

```python
class RecorderWorker(QThread):
    # ...

    def stop(self):
        self.stopflag = True

    def run(self):
        try:
            self.status.emit("Opening audio stream...")
            try:
                deviceinfo = sd.query_devices(self.deviceid)
                if deviceinfo["maxinputchannels"] < self.channels:
                    self.error.emit(
                        f"Device only supports {deviceinfo['maxinputchannels']} channels, "
                        f"requested {self.channels}"
                    )
                    return
            except Exception as e:
                self.error.emit(f"Failed to query device {e}")
                return

            with sf.SoundFile(
                self.filepath,
                mode="w",
                samplerate=self.samplerate,
                channels=self.channels,
                subtype="PCM24",
                format="WAV",
            ) as wavfile:

                def callback(indata, frames, timeinfo, status):
                    if status:
                        self.status.emit(f"Audio status {status}")
                    if self.stopflag:
                        return
                    try:
                        self.q.put_nowait(indata.copy())
                    except queue.Full:
                        self.status.emit("Warning Audio queue full, dropping frames")

                self.stream = sd.InputStream(
                    samplerate=self.samplerate,
                    channels=self.channels,
                    device=self.deviceid,
                    dtype="float32",
                    blocksize=self.blocksize,
                    callback=callback,
                )
                self.stream.start()

                self.status.emit("Recording...")
                while not self.stopflag or not self.q.empty():
                    try:
                        data = self.q.get(timeout=0.2)
                        wavfile.write(data)
                    except queue.Empty:
                        if self.stopflag:
                            break
                        continue
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            self.saved.emit(self.filepath)
```

Again: no cross‑thread `stop/close`, only via `stopflag`.

### 2. Do not call `deleteLater()` right after stopping workers

In `RecordingController` and `TranscriptionController` you already call `deleteLater()` in `onworkerfinished`. But you also call `deleteLater()` immediately when restarting: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/e869ff28-13a8-4811-a375-a9e0335dc3d6/recording_controller.py)

```python
if self.hostrecorder is not None:
    self.hostrecorder.stop()
    self.hostrecorder.wait(1000)
    self.hostrecorder.deleteLater()
    self.hostrecorder = None
```

This can double‑delete the QThread (and its underlying C++ object) if the `finished` signal also triggers `onworkerfinished`. To avoid that: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/e869ff28-13a8-4811-a375-a9e0335dc3d6/recording_controller.py)

- Remove the explicit `deleteLater()` in the “Clean up any existing recorders first…” section.
- Let `onworkerfinished` be the single place that calls `deleteLater()`.

Same for `hostworker`/`speakerworker` in `TranscriptionController`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/b74525d5-0c53-4f3a-adf6-dd27d1a259a7/transcription_controller.py)

For example, in `RecordingController.startrecording` change to:

```python
if self.hostrecorder is not None:
    self.hostrecorder.stop()
    self.hostrecorder.wait(1000)
    self.hostrecorder = None
# no deleteLater here
```

and keep:

```python
def onworkerfinished(self, inputsource: str):
    if inputsource == "host" and self.hostrecorder is not None:
        self.hostrecorder.deleteLater()
        self.hostrecorder = None
    elif inputsource == "speaker" and self.speakerrecorder is not None:
        self.speakerrecorder.deleteLater()
        self.speakerrecorder = None
```

Do the same pattern in `TranscriptionController.onworkerfinished`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/b74525d5-0c53-4f3a-adf6-dd27d1a259a7/transcription_controller.py)

### 3. Avoid two simultaneous `InputStream`s on macOS while debugging

To confirm this is multi‑stream related, temporarily disable the “speaker” recording/stream:

- In `RecordingController.startrecording` and `TranscriptionController.startsession`, skip creating the `speakerrecorder` / `speakerworker` (comment those blocks out). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/e869ff28-13a8-4811-a375-a9e0335dc3d6/recording_controller.py)
- Only use the host input device.

If the crash disappears with only one `InputStream`, you’ve confirmed the multi‑stream concurrency is the trigger. [github](https://github.com/spatialaudio/python-sounddevice/issues/120)

### 4. Check macOS audio device configuration and permissions

On macOS, `PaMacCore (AUHAL)` errors also happen when:

- The selected device has no input channels, or was removed while streaming.
- Sample rates between devices (e.g., mic vs BlackHole virtual device) don’t match. [youtube](https://www.youtube.com/watch?v=-1NvzPFHCz0)
- Terminal/Python does not have microphone permission. [stackoverflow](https://stackoverflow.com/questions/63543101/error-trying-to-record-audio-using-python-mac)

So also:

- Open **Audio MIDI Setup** and ensure your selected input (and any aggregate device) uses consistent sample rate (e.g. 48 kHz) and has input channels enabled. [youtube](https://www.youtube.com/watch?v=-1NvzPFHCz0)
- Make sure the `deviceid` you pass is really an input device with at least one input channel (`maxinputchannels > 0`). You already check this in `RecorderWorker`, but not in `SonioxWorker`; add the same guard there. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/99c7da34-0ba3-4a8b-b4b4-d9683c902340/workers.py)
- Verify macOS privacy settings include your terminal/IDE in “Microphone”. [stackoverflow](https://stackoverflow.com/questions/63543101/error-trying-to-record-audio-using-python-mac)

### 5. If it still crashes

If, after:

- Single‑threaded stream close,
- No double `deleteLater`,
- Single `InputStream` only,

you still get the same double free, then it is almost certainly a PortAudio/sounddevice bug on your exact macOS + hardware combo. [github](https://github.com/spatialaudio/python-sounddevice/issues/581)

In that case, try:

- Upgrading `sounddevice` and `portaudio` to latest versions.
- As a workaround, switching your recording code to `soundfile` + `pyaudio` or to `ffmpeg` via subprocess, and keeping `sounddevice` only for live streaming to Soniox.

If you paste the exact traceback around the `RecorderWorker`/`SonioxWorker` run method (if any), I can pinpoint the exact lines to change in your files.