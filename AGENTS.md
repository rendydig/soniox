# AGENTS.md

## Project
Desktop transcription/translation app (Python + PySide6) plus a Node.js WebSocket
server that broadcasts results to a web UI.

- `main.py` / `src/` — PySide6 desktop app (Soniox STT streaming + Gemini translation)
- `websocket-server/` — Node.js broadcast server + browser UI on `http://localhost:8765`

## Setup
```bash
# Python (venv already created with Python 3.13)
venv/Scripts/python.exe -m pip install -r requirement.txt

# Node
cd websocket-server && npm install
```

## Run
```bash
# Terminal 1 — WebSocket server (port 8765)
cd websocket-server && npm start

# Terminal 2 — desktop app
venv/Scripts/python.exe main.py
```
Web monitor: `http://localhost:8765`.

## Configuration
`.env` at the repo root (gitignored; see `.env.example`) must define:
- `SONIOX_API_KEY` — required (streaming STT)
- `GEMINI_API_KEY` — required (translation/auto-reply)
- `GROK_API_KEY` — optional (grammar correction in `websocket-server/gemini-correction.js`)

## UI structure
- `MainWindow` (`src/ui.py`) hosts a `QStackedWidget` with two pages:
  - **Main** — `TextEditorsWidget`, `TranslationSectionWidget` (manual translate),
    `ControlButtonsWidget`, `StatusBarWidget`.
  - **Settings** — `SettingsViewWidget` (`src/ui_components/settings_view.py`): reuses
    `DeviceSettingsWidget` + `LanguageSelectionWidget` and adds AI Reply Language,
    Purpose, Pronunciation, and Screen Protection.
- A checkable `Settings` action is added directly to the `QMenuBar` (via
  `menuBar().addAction(...)`), so it appears next to `Mode` and `Tool` as a clickable
  item; the Settings page also has a `Back` button. Both drive
  `_on_settings_toggled` / `_show_main_view`.
- Widgets are reached via getters in `_setup_widget_references`; moving a control between
  views only requires repointing the getter, not changing session/translation logic.
- Device changes apply on the next **Start** (combos are read in `_start_session`).

## Audio capture architecture
- **Host** input → `sounddevice.InputStream` (microphone), streamed at 16 kHz mono.
- **Speaker** input → **output loopback** via `PyAudioWPatch`, so it can capture any
  playback device, including Bluetooth headphones (Stereo Mix only covers the Realtek
  card, so it misses Bluetooth).
  - Device descriptors are dicts: `{"backend": "loopback", "index": int, "rate": int, "name": str}`.
  - Loopback streams open at the device's native rate (usually 48 kHz); Soniox accepts
    `sample_rate: 48000` directly, so no resampling is needed.
  - Virtual outputs (Voicemeeter, VB-Audio, Voice.ai, NVIDIA Broadcast) are filtered out
    of the Speaker list via `VIRTUAL_OUTPUT_HINTS` in `device_controller.py`.
  - Clean shutdown order matters: `stop.set()` → `stream.stop_stream()` (unblocks the
    blocking `read`) → `join()` → `close()` → `PyAudio().terminate()`.

## Notes / gotchas
- `sounddevice` has **no** WASAPI loopback API; `soundcard` crashes (heap corruption) —
  don't use either for loopback. `PyAudioWPatch` is the working backend.
- The WASAPI `auto_convert=True` fallback in `workers.py` lets 16 kHz open on WASAPI
  devices (e.g. Stereo Mix) that reject it otherwise.
- The Speaker combo's item data is the loopback descriptor; `_start_session` reads
  `currentData()`, not the combo index (index→id mapping breaks once the list is filtered).

## Screen capture exclusion
- `src/screen_protection.py` wraps `user32.SetWindowDisplayAffinity` to hide the main
  window from Windows screen capture while keeping it visible on the physical monitor
  (`WDA_EXCLUDEFROMCAPTURE`, needs Win10 build 19041+). `MainWindow` applies it in
  `showEvent` (re-applies after flag/re-show resets). Toggled from either the
  `Tool > Screen Protection` menu item or the Settings checkbox; `_set_screen_protection`
  keeps both controls in sync (enabled by default). Only the top-level window is
  protected; separate popups/dialogs need their own call.

## Verification
```bash
venv/Scripts/python.exe -m py_compile src/*.py src/controllers/*.py src/ui_components/*.py
```
Manual: launch the app, set Host = mic and Speaker = a `[Loopback]` output, Start,
play audio → `[SPEAKER]` lines should appear in the app and at `http://localhost:8765`.
