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
# Desktop app — auto-starts the Node server if 8765 is down
venv/Scripts/python.exe main.py
```
The app spawns `node server.js` on startup when nothing is listening on 8765
(`src/websocket_server_manager.py`), writing server output to
`logs/websocket-server.log`, and stops it on close — but only if the app
started it (a manually started server is left untouched). To run the server
yourself instead:
```bash
cd websocket-server && npm start
```
Web monitor: `http://localhost:8765`. Gemini-only suggestion page: `http://localhost:8765/gemini`.

## Configuration
`.env` at the repo root (gitignored; see `.env.example`) must define:
- `SONIOX_API_KEY` — required (streaming STT)
- `GEMINI_API_KEY` — required (translation/auto-reply)
- `GROK_API_KEY` — optional (grammar correction in `websocket-server/gemini-correction.js`)

## UI structure
- `MainWindow` (`src/ui.py`) is a **bottom bar**: a normal framed window, full usable
  width and `BAR_HEIGHT` (90px) tall, pinned just above the Windows taskbar. Positioning
  uses `QScreen.availableGeometry()` (the taskbar is already excluded) in
  `_snap_to_bottom`; it re-snaps on `showEvent` (frame metrics are only valid once shown)
  and on the primary screen's `availableGeometryChanged`, so taskbar show/hide/resize is
  followed automatically. No taskbar measurement is needed. For top-level windows,
  `move()` positions the **frame** (including the title bar), so `_snap_to_bottom` moves
  to the frame's top-left directly and resizes the client to `avail − chrome`.
- There is **no menu bar** and no `QStackedWidget`. The single horizontal row
  (`_init_ui`) holds: Start/Stop (`ControlButtonsWidget`) · Mode ▾ (`QToolButton` + `QMenu`
  with the Live Transcription/Translation actions) · Tool ▾ (`QToolButton` + `QMenu` with
  Screen Protection / Gemini Window / Live Window) · Settings button ·
  `TranslationSectionWidget` (stretch) · `StatusBarWidget`. The main window has **no**
  output view; transcription output lives in the Live Window pane.
- `Settings` opens a **separate `QDialog`** (`_open_settings`) hosting
  `SettingsViewWidget` (`src/ui_components/settings_view.py`): reuses
  `DeviceSettingsWidget` + `LanguageSelectionWidget` and adds View mode (default
  **Webview**), AI Reply Language, Purpose, Pronunciation, and Screen Protection. The
  dialog is created eagerly (hidden) so the widget getters stay valid; its `Back` button
  closes it, and `_set_screen_protection` gives it its own `set_capture_protection` call.
- `view_mode_combo` (Settings) drives the **Live Window**'s internal `view_stack` via
  `get_view_stack().setCurrentIndex`; index 0 = text editor, index 1 = Webview (default).
- `TranslationSectionWidget` is a compact horizontal row: a fixed-height (~32px)
  `QTextEdit` input plus the `SwitchButton` pill that shows/hides it (visible by default).
  `StatusBarWidget` shows the live status, a short mode label
  ("Transcription"/"Translation"), and the memory readout on the right.
- Widgets are reached via getters in `_setup_widget_references`; moving a control between
  views only requires repointing the getter, not changing session/translation logic.
- Device changes apply on the next **Start** (combos are read in `_start_session`).

## Gemini suggestion window
- `GeminiWindow` (`src/ui_components/gemini_window.py`) is a **separate top-level window**
  (no Qt parent), frameless + `WindowStaysOnTopHint` + `Tool`, pinned to the primary
  screen's right edge: `GEMINI_WINDOW_WIDTH` (480px) wide and full screen height
  (`_position_on_screen`). It hosts a `QWebEngineView` loading `http://localhost:8765/gemini`.
- It shows **only** the Gemini card. The card was removed from `public/app.js`; the
  Gemini-only page is `public/gemini.html` + `public/gemini-app.js` (reuses
  `WebSocketManager`, `useWebSocketHandler`, `useTranscriptionHandlers`, `GeminiDisplayer`;
  the server maps `/gemini` → `gemini.html` in `server.js`).
- Toggled from the `Tool ▾` button's `Gemini Window` item (`_set_gemini_window_visible`);
  created in `MainWindow.__init__` and shown at startup. Closed in `MainWindow.closeEvent`.
- The pane's top-right button (`public/gemini-app.js`) sends `hide_gemini_window`; the
  handler unchecks `gemini_window_action`, which hides the pane and keeps the menu item
  in sync (unchecked = hidden). Checking the item restores it. Since the window is a
  `Qt.Tool` with no taskbar entry, this menu item is the restore path.
- Hide/show only toggles visibility — the `QWebEngineView` is created once and never
  recreated or `reload()`ed, so the page and its WebSocket connection persist (no reload).
- Because it is a distinct top-level window, it needs its **own** `set_capture_protection`
  call: `_set_screen_protection` forwards to `gemini_window.apply_screen_protection`, and
  `GeminiWindow.showEvent` re-applies after re-shows.

## Screenshot hotkeys
- Two **system-wide** hotkeys (work even when the app is unfocused), registered by
  `src/global_hotkeys.py` (`GlobalHotkeys`, a `QAbstractNativeEventFilter`) using the
  Windows API `RegisterHotKey` via ctypes — **no third-party dependency**:
  - `ALT+SHIFT+K` → capture the **primary screen**, downscale to `SCREENSHOT_MAX_WIDTH`
    (680px, height follows the aspect ratio), JPEG-encode at quality 80, base64 → `data:`
    URL (`src/screenshot.py::capture_screen_data_url`), then send
    `{"type": "screenshot", "image": <data-url>}` over the WebSocket.
  - `ALT+CTRL+SHIFT+K` → send `{"type": "clear_screenshots"}`.
- Wiring lives in `MainWindow` (`src/ui.py`): `GlobalHotkeys` is created/registered in
  `__init__` (after `websocket_client.start()`), `_capture_screenshot` / `_clear_screenshots`
  are the callbacks, and `unregister()` runs in `closeEvent`. The callbacks fire on the Qt
  main thread, so they may touch widgets/capture directly.
- `WebSocketClient.send_message(dict)` is the generic send used for these messages; the
  server needs no change (`server.js` rebroadcasts any unrecognized `type` to other clients).
- The Gemini pane (`public/gemini-app.js`) appends each image to a
  `ScreenshotGallery` (`public/components/ScreenshotGallery.js`, rendered **above**
  `GeminiDisplayer`); handlers `handleScreenshot` / `handleClearScreenshots` live in
  `useTranscriptionHandlers.js` and are dispatched by `useWebSocketHandler.js`. Images are
  stored at 680px wide; the gallery is hidden when empty.
- The gallery is a **4-column grid** (`repeat(4, 1fr)`) of square `object-fit: cover`
  thumbnails. Clicking one opens `ScreenshotLightbox` (`components/ScreenshotLightbox.js`),
  a `position: fixed` overlay filling the pane: zoom in/out/reset (1x–10x) with a percentage
  label, **Ctrl/Cmd + wheel** zoom, **drag-to-pan** once the image overflows, and
  **prev/next** via the side buttons or Left/Right arrows (Escape closes; a plain wheel
  scrolls). The lightbox is rendered inside `.screenshot-gallery`, which is fine because a
  fixed element escapes the scroll container. Zoom sets the image's inline `width` to
  `min(naturalWidth, containerWidth) * zoom` (same technique as `mermaid-zoom.js`); the
  scroll box uses `display:flex` + `margin:auto` on the image so centering does not clip
  the overflow.
- `capture_screen_data_url` uses `QGuiApplication.primaryScreen().grabWindow(0)`; construct
  `QBuffer()` **without** a temporary `QByteArray` argument or `save()` segfaults.
- Since the app's own windows use `WDA_EXCLUDEFROMCAPTURE`, they appear black in the capture
  (expected); screenshots are in-memory only (cleared on reload/close).

## Live view window
- `LiveWindow` (`src/ui_components/live_window.py`) mirrors `GeminiWindow` on the
  opposite edge: frameless + `WindowStaysOnTopHint` + `Tool`, pinned to the primary
  screen's **left** edge, `LIVE_WINDOW_WIDTH` (480px) wide and full height. It is the
  output window: a `QStackedWidget` holding the transcription `QTextEdit` (index 0) and
  a `QWebEngineView` → `http://localhost:8765/live` (index 1); the Settings View mode
  combo switches it. `MainWindow.transcription_editor` points at this editor.
- Its web view shows the **full** live view (Live Transcription + Live Translation).
  The Preact `App` component now lives in `public/components/App.js`; `public/app.js`
  is a thin entry rendering it, and `public/live.html` + `public/live-app.js` render the
  same component with `hideControlType="hide_live_window"` (the server maps `/live` →
  `live.html`). `live.html` adds flex overrides so both cards share the pane.
- Toggled from the `Tool ▾` button's `Live Window` item (`_set_live_window_visible`);
  created in `MainWindow.__init__` and shown at startup. Closed in `MainWindow.closeEvent`.
- Same hide/menu sync as Gemini: the pane's top-right button sends `hide_live_window`,
  which unchecks `live_window_action`. Hide/show only toggles visibility (the webview is
  never reloaded), and `_set_screen_protection` forwards to
  `live_window.apply_screen_protection`.

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
  `Tool ▾ > Screen Protection` item or the Settings checkbox; `_set_screen_protection`
  keeps both controls in sync (enabled by default). Only the top-level window is
  protected; separate popups/dialogs need their own call — the `GeminiWindow` pane is
  covered via `apply_screen_protection` and its own `showEvent`, and the Settings dialog
  gets one from `_set_screen_protection` / `_open_settings`.

## Verification
```bash
venv/Scripts/python.exe -m py_compile src/*.py src/controllers/*.py src/ui_components/*.py
```
Manual: launch the app, set Host = mic and Speaker = a `[Loopback]` output, Start,
play audio → `[SPEAKER]` lines should appear in the app and at `http://localhost:8765`.
