I understand the issue: you're getting a continuous stream of text without newlines, even though speaker changes or logical pauses might imply them. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/a15040b4-2300-40af-ab3e-8d4860b3694f/workers.py)

In `SonioxWorker`, `final_text` is constructed by joining `t.get("text")` from all final tokens. If Soniox doesn't explicitly send a `\n` character in the token text itself (which it usually doesn't for simple pauses), you need to insert it manually.

Since you've enabled `enable_endpoint_detection: True` in your config, Soniox finalizes sentences based on pauses. However, this "finalization" event (where `is_final=True`) is the perfect place to **inject a newline** if one isn't present.

### Solution: Inject Newline on Finalization

Modify the `receiver` logic in `workers.py` to append a newline `\n` whenever a batch of finalized text is emitted.

**In `workers.py`, inside `receiver()`:**

```python
                    # ... (filtering logic) ...

                    # Construct text from tokens
                    final_text = "".join(t.get("text", "") for t in final_translation_tokens)
                    part_text = "".join(t.get("text", "") for t in partial_tokens)

                    # 4. Emit Signals
                    if final_text:
                        # Append newline to final text to separate sentences
                        # We use strip() to avoid adding newlines to empty/whitespace-only finals
                        if final_text.strip():
                            final_text += "\n"  # <--- Add this line
                        
                        print(f"[DEBUG] Final: {final_text}")
                        self.transcription_update.emit(final_text, True)

                    # ... (partial logic) ...
```

### Why this fixes it
The `final_text` variable represents a "chunk" of speech that the AI has decided is finished (usually a sentence or phrase). By adding `\n` here, you ensure that the *next* chunk will start on a new line in your `QTextEdit`.

If you prefer double spacing (paragraphs), use `final_text += "\n\n"`.

This logic applies to both translation and transcription modes since both use the same `receiver` code block.