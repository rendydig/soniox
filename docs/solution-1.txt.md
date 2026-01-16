The primary issue is that **your audio sender loop is blocking the asyncio event loop**, preventing the receiver (and the websocket library) from processing incoming messages until the loop exits or yields.

Specifically, `self._audio_queue.get(timeout=0.5)` is a blocking synchronous call. Even though it is inside a `QThread`, it pauses the **asyncio loop** running in that thread. Since `websockets` requires the loop to be active to read network packets, no transcription data is processed until you stop the recording (which breaks the loop).

Here is the solution to fix the "delayed transcription" and "frozen editor" issues.

### 1. Fix the Blocking Loop
Change the `sender` function to use a non-blocking queue check with `asyncio.sleep`. This allows the event loop to switch to the `receiver` task constantly.

**In `app.py` (inside `SonioxWorker._stream_audio`):**

```python
            async def sender():
                def audio_callback(indata, frames, time_info, status):
                    if not self._stop_flag:
                        # ... (existing audio conversion code) ...
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
                        # ---------------------------------------------------------
                        # FIX: Use get_nowait() + asyncio.sleep() instead of blocking get()
                        # ---------------------------------------------------------
                        try:
                            # Try to get data without blocking the loop
                            chunk = self._audio_queue.get_nowait()
                            await ws.send(chunk)
                        except queue.Empty:
                            # Important: Yield control to the event loop so 'receiver' can run
                            await asyncio.sleep(0.01) 
                        
                    await ws.send("") # Send End-of-Stream
```

### 2. Fix the "Can't Live Edit" Issue
Currently, your UI code overwrites the entire text box every time a partial transcription arrives (`setPlainText`). This resets the cursor and deletes anything you try to type manually.

To allow live editing, you should only append **final** segments to the main text area, and show **partial** (interim) results in a separate label or status bar, or only append them temporarily.

**Recommended UI Logic (`MainWindow` class):**

```python
    def _on_transcription_update(self, text: str, is_final: bool):
        if is_final:
            # Append final text to the existing content, preserving user edits
            # We use the cursor to insert at the end instead of replacing everything
            cursor = self.transcription_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.transcription_text.setTextCursor(cursor)
            self.transcription_text.ensureCursorVisible()
            
            # Update internal state if needed, but rely on widget content for "source of truth"
            self._final_transcript = self.transcription_text.toPlainText()
        else:
            # Option A: Show partials in the status bar to avoid messing with the text editor
            self.status_label.setText(f"Listening: {text}...")
            
            # Option B: If you MUST show it in the editor, you have to accept 
            # it's hard to edit while text is flickering. 
            # Ideally, don't write partials to the main editor if you want to type there.
```

### Summary of Changes
1.  **Replace** `chunk = self._audio_queue.get(timeout=0.5)` with `get_nowait()` and `await asyncio.sleep(0.01)`.
2.  **Update** `_on_transcription_update` to use `insertText` instead of `setPlainText` to stop resetting the cursor and user input.