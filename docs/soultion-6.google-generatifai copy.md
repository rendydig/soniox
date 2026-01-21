The error occurs because the `GeminiWorker` class in your `workers.py` file is hardcoded to use the older `gemini-pro` model, which the API (specifically v1beta) is flagging as deprecated or not found.

You need to update `src/workers.py` to use the `gemini-2.5-flash` model as you requested.

### File: `src/workers.py`

Locate the `GeminiWorker` class (near the bottom of the file) and find the `run` method. Change the model name in the `genai.GenerativeModel` call.

**Change this line:**
```python
model = genai.GenerativeModel('gemini-pro')
```

**To this:**
```python
model = genai.GenerativeModel('gemini-2.5-flash')
```

### Full Context for the Fix

Here is the corrected section of code for `workers.py`:

```python
class GeminiWorker(QThread):
    # ... (signals and init remain the same)

    def run(self):
        try:
            if not GEMINI_API_KEY:
                self.error.emit("GEMINI_API_KEY not found in .env file")
                return

            genai.configure(api_key=GEMINI_API_KEY)
            
            # UPDATED: Changed from 'gemini-pro' to 'gemini-2.5-flash'
            model = genai.GenerativeModel('gemini-2.5-flash')

            prompt = f"""Translate the following text to {self._target_language}. Provide the response in this exact format:
            {self._target_language} Text: [Write the sentence using natural {self._target_language} script]
            Syllables/Pronunciation: [Provide the pronunciation in Latin alphabet with Indonesian spelling so I know how to speak it]
            English Translation: [Provide the meaning in clear English]
            Text to translate: {self._text}"""
            
            response = model.generate_content(prompt)
            self.result.emit(response.text)

        except Exception as e:
            self.error.emit(f"Gemini error: {str(e)}")
```

After saving this change, restart your application, and the 404 error should be resolved. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/7236203/722d198b-b15d-42b4-89c5-6f2cde121827/workers.py)