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
- `GEMINI_API_KEY` — required when `AI_PROVIDER=gemini` (default)
- `GROK_API_KEY` — optional (grammar correction in `websocket-server/gemini-correction.js`)

AI provider (translation/auto-reply/image reply, `src/ai_client.py`):
- `AI_PROVIDER` — `gemini` (default) or `openai` (any OpenAI-compatible endpoint:
  OpenRouter, x.ai, OpenAI, local servers)
- `AI_MODEL` — model name; falls back to `GEMINI_MODEL`, then `gemini-2.5-flash`
- `AI_BASE_URL` + `AI_API_KEY` — required only when `AI_PROVIDER=openai`
  (e.g. `https://openrouter.ai/api/v1`; screenshot replies need a vision-capable model)
- `DISABLE_MODEL_REASONING` — default `true`; when on, the provider client requests no
  "thinking"/reasoning tokens (Gemini `thinking_budget=0`; OpenRouter `reasoning.effort=none`),
  roughly halving reply latency. Set `false` to re-enable reasoning.

Auto-reply latency (constants in `src/config.py`):
- `AUTO_REPLY_DEBOUNCE_MS` (1200) — debounce for a final **without** Soniox's `<end>` marker.
- `AUTO_REPLY_ENDPOINT_DEBOUNCE_MS` (0) — delay for a final **with** `<end>` (true end of the
  utterance; endpoint detection already waited out the silence), so replies fire almost
  immediately. The `<end>` flag rides as the 4th arg of the `transcription_update` signal
  (`src/workers.py` → `src/controllers/transcription_controller.py` → `src/ui.py`).
- `SONIOX_MAX_ENDPOINT_DELAY_MS` (800; Soniox default 2000), `SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL`
  (2) and `SONIOX_ENDPOINT_SENSITIVITY` (0.4) — sent in the Soniox session config
  (`src/workers.py`) so endpoint detection emits `<end>` sooner. Aggressive preset: faster but
  can slightly reduce word-recognition accuracy and split long speech into more segments; lower
  them to trade speed back for accuracy.

Auto-reply **streaming** (word-by-word, not SSE — it rides the existing WebSocket):
- `AIClient.generate_stream(system_instruction, messages)` (`src/ai_client.py`) is a generator:
  Gemini uses `models.generate_content_stream`, OpenAI-compatible clients use
  `chat.completions.create(..., stream=True)` and yield `delta.content`. The base class falls back
  to one non-streaming `generate()` so every provider works.
- `GeminiAutoReplyWorker` (auto-reply **and** image reply) has a `chunk = Signal(str)`; its `run()`
  accumulates stream pieces and emits coalesced partial text at most every
  `AI_STREAM_CHUNK_INTERVAL_MS` (60, `src/config.py`), then emits the full `result` at the end.
  `GeminiWorker` (manual translate) stays non-streaming.
- `TranslationController.reply_chunk = Signal(str, bool)` (text, is_image) forwards each partial;
  `MainWindow._on_reply_chunk` → `_send_gemini_stream` broadcasts `{"type": "gemini_stream", ...}`
  (raw, unformatted text — the final `gemini_result` is still `format_gemini_result`-ed and
  **replaces** it). Partial chunks are **not** persisted to the session.
- Frontend: `useWebSocketHandler.js` dispatches `gemini_stream` → `handleGeminiStream`
  (`useTranscriptionHandlers.js`), which **updates the last item** when it is flagged `streaming`
  and the mode matches, otherwise appends a new streaming item; `handleGeminiResult` then replaces
  the list with the final item. `GeminiDisplayer` renders only the latest item, so it repaints live.

## UI structure
- `MainWindow` (`src/ui.py`) is a **bottom bar**: a frameless, always-on-top window with a
  **fixed default width** (`BAR_WIDTH`, 560px) and `BAR_HEIGHT` (40px). `_apply_bar_geometry`
  places it **bottom-centre** just above the Windows taskbar using
  `QScreen.availableGeometry()` (the taskbar is already excluded; no taskbar measurement is
  needed). The width is **user-resizable** via a right-edge `PaneResizeHandle` and the bar is
  movable via its `DragHandle`; its width and x/y are persisted in `ui_state.json`'s
  `main_window` and restored on launch, only re-clamped on-screen when the taskbar/screen
  changes (never re-centred). `_clamp_bar_width` floors the width at the trimmed control row's
  own `minimumSizeHint` (measured ~455px, so the bar shrinks well below `BAR_WIDTH` and a stored
  narrow width is restored as-is) and never exceeds the screen width; the `MIN_BAR_WIDTH`
  constant is only a fallback used before the layout exists. The bar no longer derives its
  width from the panes.
  `_apply_bar_geometry` runs on `showEvent` and on the primary screen's
  `availableGeometryChanged`.
- The bar's layout (`_init_ui`) is an outer `QHBoxLayout` of `[content] · [width handle]`,
  where `content` is a `QVBoxLayout`: the optional translation-input row
  (`TranslationSectionWidget`, hidden by default) above the single control row. The control
  row holds `DragHandle` · Start/Stop + New (`ControlButtonsWidget`) · Mode ▾ (`QToolButton` +
  `QMenu` with the Live Transcription/Translation actions) · Tool ▾ (`QToolButton` + `QMenu`
  with Screen Protection / Gemini Window / Live Window / Bullet Points / Always on Top) · Settings button ·
  `SwitchButton` (shows/hides the input row) · stretch · `StatusBarWidget` · close. The main
  window has **no** output view; transcription output lives in the Live Window pane.
- The bar is **trimmed** to fit its fixed width: the Start button reads "Start"/"Stop", the
  Mode button reads "Mode" (active mode shown in its tooltip + the menu checkmark), and the
  `StatusBarWidget`'s mode and memory labels are hidden, leaving only the eliding
  `ElidedLabel` status text (`src/ui_components/elided_label.py`). Height is `BAR_HEIGHT`
  (60px), growing to `BAR_HEIGHT + INPUT_ROW_HEIGHT` (100px) only while the translation-input
  row is shown, keeping the bottom edge fixed (`_on_manual_switch_toggled`).
- `Settings` opens a **separate `QDialog`** (`_open_settings`) hosting
  `SettingsViewWidget` (`src/ui_components/settings_view.py`): reuses
  `DeviceSettingsWidget` + `LanguageSelectionWidget` and adds View mode (default
  **Webview**), AI Reply Language, Purpose, Pronunciation, and Screen Protection. The
  dialog is created eagerly (hidden) so the widget getters stay valid; its `Back` button
  closes it, and `_set_screen_protection` gives it its own `set_capture_protection` call.
  It also carries its own `WindowStaysOnTopHint` so it stays above the top-most bar.
- The bar is **always-on-top** by default (mirrors the panes): `MainWindow` sets
  `Qt.WindowType.WindowStaysOnTopHint` from `ui_state.json`'s `main_window.always_on_top`
  (default true) and exposes it as the Tool ▾ **Always on Top** checkable action
  (`_set_always_on_top`). **The toggle governs all four windows**, not just the bar: it
  also calls each pane's `apply_always_on_top`, and the panes start in the persisted state
  (a loop right after they are constructed). Toggling re-sets the flag and calls `show()`
  (changing flags on a visible window hides it), which re-runs `showEvent`'s
  `_apply_bar_geometry` + capture protection, then re-asserts the native level via
  `set_always_on_top`. Each pane keeps its own `_always_on_top` flag (default True) that
  `showEvent` re-applies, so a re-show never silently re-pins an unpinned pane.
- **Always on top on macOS**: Qt already maps `WindowStaysOnTopHint` onto a floating
  `NSWindow` level (measured: 8 for every flag combination the app uses), so the flag is
  not Windows-only. `src/macos_window.py::set_always_on_top` makes it explicit and
  stronger — it pins the level to `NSFloatingWindowLevel` (3) and adds
  `NSWindowCollectionBehaviorFullScreenAuxiliary` so the window also stays above a
  *full-screen* app, clearing the bit again when disabled. It is re-applied from
  `showEvent` in `MainWindow` and all three panes (setting window flags recreates the
  `NSWindow`), and is a no-op off macOS.
- **Staying on top while the app is inactive**: a `Qt::Tool` window is an `NSPanel` whose
  `hidesOnDeactivate` defaults to **YES**, so macOS hid the panes the moment the app lost
  focus — the long-standing "always on top doesn't work on macOS" symptom. Each pane now
  sets `Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow` **before** `show()` (setting it after
  `show()` has no effect), and `macos_window.set_always_on_top` clears
  `hidesOnDeactivate` natively too, since Qt re-creates the `NSWindow` when flags change.
  The bar was never affected (a plain `Qt::Window` already has `hidesOnDeactivate = NO`).
- `view_mode_combo` (Settings) drives the **Live Window**'s internal `view_stack` via
  `get_view_stack().setCurrentIndex`; index 0 = text editor, index 1 = Webview (default).
- `TranslationSectionWidget` is a compact horizontal row: a fixed-height (~32px)
  `QTextEdit` input shown/hidden by the row's `SwitchButton` pill (hidden by default).
- Widgets are reached via getters in `_setup_widget_references`; moving a control between
  views only requires repointing the getter, not changing session/translation logic.
- Device changes apply on the next **Start** (combos are read in `_start_session`).

## Gemini suggestion window
- `GeminiWindow` (`src/ui_components/gemini_window.py`) is a **separate top-level window**
  (no Qt parent), frameless + `WindowStaysOnTopHint` + `Tool`, **free-floating** on the
  primary screen: `GEMINI_WINDOW_WIDTH` (400px) wide by default, movable via a top drag
  strip, resizable in width (inner edge) and height (bottom edge). It is docked to the
  left **or** right edge (default **right**, switchable at runtime) at full height by
  default. It hosts a `QWebEngineView` loading `http://localhost:8765/gemini`.
- It shows **only** the Gemini card. The card was removed from `public/app.js`; the
  Gemini-only page is `public/gemini.html` + `public/aireply-app.js` (reuses
  `WebSocketManager`, `useWebSocketHandler`, `useTranscriptionHandlers`, `GeminiDisplayer`;
  the server maps `/gemini` → `gemini.html` in `server.js`).
- Toggled from the `Tool ▾` button's `Gemini Window` item (`_set_gemini_window_visible`);
  created in `MainWindow.__init__` and shown at startup. Closed in `MainWindow.closeEvent`.
- The pane's top-right button (`public/aireply-app.js`) sends `hide_gemini_window`; the
  handler unchecks `gemini_window_action`, which hides the pane and keeps the menu item
  in sync (unchecked = hidden). Checking the item restores it. Since the window is a
  `Qt.Tool` with no taskbar entry, this menu item is the restore path.
- Hide/show only toggles visibility — the `QWebEngineView` is created once and never
  recreated or `reload()`ed, so the page and its WebSocket connection persist (no reload).
- Because it is a distinct top-level window, it needs its **own** `set_capture_protection`
  call: `_set_screen_protection` forwards to `gemini_window.apply_screen_protection`, and
  `GeminiWindow.showEvent` re-applies after re-shows.

## Screenshot hotkeys
- Five **system-wide** hotkeys (work even when the app is unfocused), registered by
  `src/global_hotkeys.py` (`GlobalHotkeys`) with a per-platform backend, both via ctypes
  — **no third-party dependency**: on **Windows** `RegisterHotKey` + a
  `QAbstractNativeEventFilter`; on **macOS** the Carbon framework's
  `RegisterEventHotKey`; any other platform logs a warning and registers nothing. On a
  Mac the `Alt` modifier maps to the Option key:
  - `ALT+SHIFT+K` → capture the **primary screen**, downscale to `SCREENSHOT_MAX_WIDTH`
    (1200px, height follows the aspect ratio), JPEG-encode at quality 80, base64 → `data:`
    URL (`src/screenshot.py::capture_screen_data_url`), then send
    `{"type": "screenshot", "image": <data-url>}` over the WebSocket.
  - `ALT+CTRL+SHIFT+K` → send `{"type": "clear_screenshots"}`.
  - `CTRL+ALT+SHIFT+G` → send **all** captured screenshots to Gemini (see below).
  - `CTRL+ALT+P` → manual **bullet points** update (`MainWindow._trigger_bullet_points_now`;
    silent, only when the Bullet Points pane is visible — see the bullet points section).
  - `CTRL+SHIFT+M` (Cmd+Shift+M on macOS — Qt maps the portable `Ctrl` to Command there)
    → toggle **hide/restore all open panes** (`MainWindow._toggle_all_panes`). It snapshots
    which of the Gemini / Live / Bullet Points Tool ▾ actions are checked, unchecks them all
    (routing through the normal `_set_*_window_visible` setters so the menu stays in sync and
    bullet auto-updates pause), then on the next press re-checks exactly that set. State is
    tracked by `_all_panes_hidden` + `_panes_visibility_before_hide`. The main bar is never
    affected, and because it drives the real actions, the hide is persisted like a manual
    hide (e.g. `bullet_points_window_visible`) — no separate suppression.
- Wiring lives in `MainWindow` (`src/ui.py`): `GlobalHotkeys` is created/registered in
  `__init__` (after `websocket_client.start()`), `_capture_screenshot` / `_clear_screenshots` /
  `_send_images_to_gemini` / `_trigger_bullet_points_now` / `_toggle_all_panes` are the
  callbacks, and `unregister()` runs in `closeEvent`. The callbacks fire on the Qt main thread,
  so they may touch widgets/capture directly. All five shortcuts are editable in the Settings
  dialog's **Global Hotkeys** section (`settings_view.py::_HOTKEY_FIELDS`); the action names must
  match `src.global_hotkeys.HOTKEY_ACTIONS`.
- `MainWindow._screenshots` retains every capture as a data URL (appended in
  `_capture_screenshot`, cleared in `_clear_screenshots`) so Python can forward them to Gemini;
  it stays in sync with the webview gallery because both hotkeys are handled in Python.
- `CTRL+ALT+SHIFT+G` → `MainWindow._send_images_to_gemini` → `TranslationController.trigger_image_reply(images)`
  → `GeminiAutoReplyWorker(..., images=...)`, which reuses the auto-reply persona/purpose/format
  and conversation history. `gemini_worker._build_messages` attaches each screenshot to the
  final **user** turn (or appends a new user turn with a short screenshot prompt); the provider
  client (`src/ai_client.py`) then encodes them (`types.Part.from_bytes` for Gemini, an
  `image_url` data URL for OpenAI-compatible providers). The reply arrives on the new
  `image_reply_result` signal and is broadcast with mode `"image"` (badge "Image"); normal
  auto-replies still use `auto_reply_result`. An empty gallery shows "No screenshots to send."
  in the pane.
- `WebSocketClient.send_message(dict)` is the generic send used for these messages; the
  server needs no change (`server.js` rebroadcasts any unrecognized `type` to other clients).
- The Gemini pane (`public/aireply-app.js`) appends each image to a
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
- **macOS Screen Recording permission** (macOS 10.15+): the CoreGraphics API behind
  `grabWindow(0)` does **not** fail without permission — it silently returns only the desktop
  wallpaper + menu bar (the classic "screenshot is just the desktop" symptom). The permission
  belongs to the **responsible process** (the terminal/IDE that launched the app, *not* Python)
  and needs that app to be **quit and relaunched** after granting it. `src/screen_permission.py`
  wraps `CGPreflightScreenCaptureAccess` / `CGRequestScreenCaptureAccess` (ctypes, no third-party
  dependency; no-op + always-granted off macOS): `MainWindow.__init__` preflights and calls
  `request_permission()` once so the system dialog appears, `capture_screen_data_url` returns `""`
  with a warning when permission is missing, and `_capture_screenshot` broadcasts a `gemini_status`
  hint to the pane. Fix path: System Settings → Privacy & Security → Screen & System Audio
  Recording (macOS 15 name) → enable the terminal/IDE → restart it.
- Since the app's own windows use `WDA_EXCLUDEFROMCAPTURE`, they appear black in the capture
  (expected); screenshots are in-memory only (cleared on reload/close).

## Live view window
- `LiveWindow` (`src/ui_components/live_window.py`) mirrors `GeminiWindow` on the
  opposite edge: frameless + `WindowStaysOnTopHint` + `Tool`, **free-floating** on the
  primary screen, `LIVE_WINDOW_WIDTH` (480px) wide by default, movable via the same top
  drag strip and resizable in width/height; docked to the left **or** right edge (default
  **left**, switchable at runtime) at full height by default. It is the output window: a
  `QStackedWidget` holding the transcription `QTextEdit` (index 0) and a `QWebEngineView`
  → `http://localhost:8765/live` (index 1); the Settings View mode combo switches it.
  `MainWindow.transcription_editor` points at this editor.
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

## Bullet points (rolling conversation summary)
- Optional feature. The Settings dialog's **Auto Bullet Points** checkbox
  (`settings_view.py`, default off) controls the *automatic* timer only; checking it also shows
  the pane. The Tool ▾ **Bullet Points** action (checkable, default unchecked) shows/hides the
  pane. Both funnel through `MainWindow._update_bullet_points_auto()`.
- `BulletPointsController` (`src/controllers/bullet_points_controller.py`) keeps the list as
  **state** and **always buffers** finalized lines during a session (capped at
  `BULLET_PAUSED_BUFFER_MAX`, oldest dropped) — buffering is free, only AI calls cost tokens.
  With auto on, a repeating `QTimer` (`BULLET_FLUSH_INTERVAL_MS`, 15 s) *polls* (ticks are free
  when the buffer is empty or a worker is running) and it also flushes early at
  `BULLET_MAX_BUFFER_LINES` (12). An idle/auto-off conversation costs **zero tokens**.
- Each call sends the **current list + only the new lines** to `BulletPointsWorker`
  (`src/bullet_points_worker.py`), which reuses `AIClient.generate` and the same `.env`
  provider/model and returns the full updated list as JSON (`_parse_bullet_json` tolerates
  code fences; malformed output keeps the previous list and retries). Cost stays flat
  (O(list + delta)) instead of re-sending the whole transcript (O(N²)). The list is capped at
  `BULLET_MAX_ITEMS` (12).
- **Auto / manual / checkpoint:** auto updates run only when the checkbox is on **and** the
  pane is visible; hiding the pane (Tool ▾ or its `−`) pauses the timer but keeps the current
  list as a checkpoint and keeps buffering. Re-showing broadcasts the checkpoint immediately
  and makes one catch-up call. **`CTRL+ALT+P`** (system-wide, `global_hotkeys.py`) does a
  **silent manual update** (`flush_now(force=True)`) that merges only the new buffered lines —
  it works with auto off, but is a no-op (logged) when the pane is hidden (never auto-shows it).
- `MainWindow` wires it: `_on_transcription_update` buffers final lines via `add_line`
  (unconditional); `_trigger_bullet_points_now` is the `CTRL+ALT+P` callback;
  `_on_bullet_points_updated` broadcasts `{"type":"bullet_points","items":[...]}` and
  `_send_bullet_status` broadcasts `{"type":"bullet_points_status","status":...}` over the
  WebSocket (`send_message`, rebroadcast by the server). Pane control messages:
  `hide_bullet_points_window`, `set_bullet_points_window_edge`.
- `BulletPointsWindow` (`src/ui_components/bullet_points_window.py`) mirrors
  `GeminiWindow`/`LiveWindow` (frameless, always-on-top, `Tool`, drag + width/height resize,
  dock left/right, own `set_capture_protection`) but starts **free-floating** on the right
  (not edge-docked) to avoid colliding with the docked panes. Its web view loads
  `http://localhost:8765/bullets` → `public/bullets.html` + `public/bullets-app.js`
  (server route `/bullets`), rendering `components/BulletPointsList.js` with a custom
  CSS-drawn checkmark.
- Persisted in `ui_state.json`: `settings.bullet_points` (auto, default false),
  `settings.bullet_points_window_visible` (default false) and a `bullet_points_window`
  geometry block. `_set_pane_edge` swaps any docked pane on the target edge across all three
  panes.

## Sessions (persistence, resume, new session)
- A **session** is the conversation state persisted to `sessions/current.json` (gitignored):
  `bullets`, `conversation`, `transcriptions`, `translations`, `gemini_results`, `screenshots`
  (each capped in `src/config.py`). `SessionStore` (`src/session_store.py`) holds it in memory and
  a **background daemon thread** JSON-dumps snapshots on a debounce
  (`SESSION_WRITE_DEBOUNCE_MS`, 2 s) via a temp file + `os.replace`, so file I/O never blocks the
  UI. `flush()` writes synchronously; `close()` (called from `closeEvent`) stops the thread after
  a final flush. The store only ever *replaces* list values (never mutates in place), so a shallow
  snapshot is safe to serialize off-thread.
- **Stop → Start resumes** the same session (the editor/history/bullets clears were removed from
  `_start_session`).
- **New Session**: the bar's **New** button (`ControlButtonsWidget.new_session_clicked`) →
  `MainWindow._new_session` confirms via a top-most, capture-protected `QMessageBox`, then
  `SessionStore.new_session()` archives the current session to `sessions/<id>.json` (when
  non-empty) and starts a fresh `current.json`; the editor/history/bullets/screenshots are cleared
  and an **empty `session_state`** is broadcast so every pane resets.
- **Restore on launch**: `MainWindow._restore_session` seeds `BulletPointsController.load_bullets`,
  `TranslationController.load_conversation_history`, `MainWindow._screenshots` and the
  transcription `QTextEdit`. Webviews restore their slice by sending
  `{"type":"request_session_state"}` when they receive the server's `connection` message;
  `MainWindow` replies with `{"type":"session_state", ...}` (rebroadcast by the server).
  `handleSessionState` in `useTranscriptionHandlers.js` applies each slice to the setters the page
  provides (`noop`/absent setters are skipped).
- `MainWindow` pushes state at the existing points: final transcriptions/translations,
  `_send_gemini_result` (gemini_results), `_capture_screenshot` (screenshots),
  `_on_bullet_points_updated` (bullets), plus the conversation-history mirror.
- Worker cleanup: `BulletPointsController.cleanup()` now stop → wait → terminate (like
  `TranslationController`) so a worker blocked in a synchronous HTTP call isn't destroyed while
  running (`QThread: Destroyed while thread is still running`).

## Pane layout (free-floating geometry, persisted)
- Both panes are **free-floating**: a top `PaneDragHandle`
  (`src/ui_components/pane_drag_handle.py`, a 12px strip) drags the window anywhere on the
  primary screen, and eight `PaneEdgeHandle` border grips
  (`src/ui_components/pane_edge_handle.py`) resize it freely from **any edge or corner**
  (`left`/`right`/`top`/`bottom` + the four corners). The handles live in the pane's layout
  (a `QGridLayout` with the content in the centre cell and the grips around it) because the
  `QWebEngineView` consumes mouse events. The top-centre cell is the drag strip; its two
  corner grips still resize from the top edge. Drag → `window.begin_edge_resize(direction,
  pos)` / `perform_edge_resize(pos)` / `end_edge_resize()` for resize and `move_to()` for
  move; release → persists via `finish_resize()` / `finish_move()`. Resizing anchors the
  **opposite** edge (so dragging an edge past a limit stops instead of sliding the pane).
  Width is clamped to `[MIN_WINDOW_WIDTH (200), screen width]`, height to `[MIN_WINDOW_HEIGHT
  (120), screen height]`, and x/y are clamped onto the primary screen. (`PaneResizeHandle` is
  still used only by the bottom bar's width handle.)
- A pane is **docked** (edge-pinned at full height, `is_docked()`) by default; moving or
  resizing un-docks it (`_docked = False`). Both panes carry a top-right control
  cluster (`.gemini-controls` / `.pane-controls`): `⇤` (dock left) · `⇥` (dock right) ·
  `−` (hide). The edge buttons send
  `{"type": "set_gemini_window_edge" | "set_live_window_edge", "edge": "left" | "right"}`
  over the WebSocket (same rebroadcast path as the hide messages).
- `MainWindow._handle_webview_message` routes them to `_set_pane_edge(window, edge)`, which
  re-docks a floating pane to that edge at full height (a same-edge **docked** pane is a
  no-op) and **auto-swaps** the other pane only if it is itself docked to the same edge, so
  two docked panes never overlap.
- The bar has a fixed width and does **not** follow the panes, so a docked pane may overlap
  its ends (both are always-on-top).
- Panes emit `geometry_changed` (live resize / move / edge change) and `state_changed`
  (drag release / edge change → `MainWindow._save_state`).
- Pane geometry is persisted per pane to a gitignored `ui_state.json` at the repo root
  (`src/ui_state.py`), loaded in `MainWindow.__init__` and restored on the next launch;
  `closeEvent` saves once more. Each pane stores `{edge, docked, width, height, x, y}`; the
  same file stores the bar's `main_window` block — `always_on_top` (default true),
  `width` (default 560), and `x`/`y` (default: bottom-centre) — and a `settings` section,
  written by `_save_state` alongside the panes. A missing/corrupt file (or legacy
  `{edge, width}`-only state, which has no `docked` key) falls back to the defaults
  (Gemini = right/400, Live = left/480, docked full height, bar = 560px bottom-centre,
  always-on-top = true).
  `_set_gemini_window_visible` / `_set_live_window_visible` re-apply the stored geometry
  (not a re-dock) when a pane is re-shown.
- The `settings` section persists the Settings dialog's non-device options — `view_mode`
  (default 1 = Webview), `ai_reply_language` (default "English"), `purpose` (default
  `language_learning`), `pronunciation` (default false), `bullet_points` (auto, default false),
  `bullet_points_window_visible` (default false), and `screen_protection` (default true). `MainWindow._apply_settings_state` restores them (guarding bad values) after the
  widget/controller connections are wired, and `_connect_settings_signals` saves on every
  change. Purpose is applied **before** pronunciation because `_on_purpose_changed` resets
  pronunciation to the purpose's `include_pronunciation_default`. Device selection and the
  Speech Translation Target are intentionally not persisted (device combos populate
  asynchronously).

## Audio capture architecture
- **Host** input → `sounddevice.InputStream` (microphone), streamed at 16 kHz mono.
- Device discovery is **split by OS** in `DeviceController.populate_devices`
  (`src/config.py` exposes `IS_WINDOWS` / `IS_MACOS`): `_query_host_devices` is shared,
  then `_query_windows_loopback_devices` or `_query_macos_system_audio_devices` fills the
  speaker/system-audio combo. `missing_speaker_message()` gives the OS-specific
  "not found" status text, `DeviceSettingsWidget` swaps its labels (and shows a BlackHole
  setup hint only on macOS), and both descriptors are consumed by `SonioxWorker`.
- **Speaker (Windows)** → **output loopback** via `PyAudioWPatch`, so it can capture any
  playback device, including Bluetooth headphones (Stereo Mix only covers the Realtek
  card, so it misses Bluetooth).
  - Device descriptors are dicts: `{"backend": "loopback", "index": int, "rate": int, "name": str}`.
  - Loopback streams open at the device's native rate (usually 48 kHz); Soniox accepts
    `sample_rate: 48000` directly, so no resampling is needed.
  - Virtual outputs (Voicemeeter, VB-Audio, Voice.ai, NVIDIA Broadcast) are filtered out
    of the Speaker list via `WINDOWS_VIRTUAL_OUTPUT_HINTS` in `device_controller.py`.
  - Clean shutdown order matters: `stop.set()` → `stream.stop_stream()` (unblocks the
    blocking `read`) → `join()` → `close()` → `PyAudio().terminate()`.
- **System audio (macOS)** → CoreAudio/PortAudio has **no loopback API**, so system audio
  is read from the *input* side of a virtual device (BlackHole recommended; Soundflower /
  Loopback Audio also match `MACOS_SYSTEM_AUDIO_HINTS`). Descriptors are dicts:
  `{"backend": "input", "index": int, "rate": int, "name": str}` with the device's
  native rate (48 kHz); the worker opens them through `sounddevice` (the `"input"` branch
  in `SonioxWorker.__init__`). BlackHole 2ch accepts a mono 48 kHz stream, so no channel
  fallback is needed. The user must route output to it (a Multi-Output Device keeps
  playback audible) — the app cannot do that for them.

## Logging
- All errors/warnings and diagnostics go to the **terminal** via Python `logging`;
  there are **no `QMessageBox` popups** (the worker error that used to show
  `[speaker] Worker error: received 1000 (ok)...` is now logged, not shown).
  `src/logging_setup.py::setup_logging()` (called first in `main.py`) installs a
  stdout `StreamHandler` with the format `%(asctime)s [%(levelname)s] %(name)s: %(message)s`;
  the level comes from the `LOG_LEVEL` env var (default `DEBUG`), and
  `websockets`/`urllib3`/`asyncio` are pinned to `WARNING`.
- Each module uses `logger = logging.getLogger(__name__)`. Add new diagnostics as
  `logger.<level>(...)` with lazy `%`-style args, **not** `print()`, so they flow
  through the same console.

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
  (`WDA_EXCLUDEFROMCAPTURE`, needs Win10 build 19041+). **macOS** has no exact
  equivalent: it delegates to `src/macos_window.py`, which sets
  `NSWindow.sharingType = NSWindowSharingNone` through the Objective-C runtime
  (`ctypes`, no third-party dependency). Verified on this Mac: an excluded window
  disappears completely from the app's own `QScreen.grabWindow(0)` screenshots
  (`ALT+SHIFT+K`). Two caveats — Apple deprecated `sharingType` and ScreenCaptureKit
  capturers on macOS 15+ may ignore it, and it is effectively **one-way**: once a window
  is `None` it cannot be made shareable again, so `set_capture_exclusion(..., False)`
  reports False and the window stays excluded until recreated.
- The macOS module only acts under the Cocoa platform plugin (guarded via
  `QGuiApplication.platformName()`), so the offscreen plugin and other OSes are safe
  no-ops. `is_supported()` reflects this.
- `MainWindow` applies it in
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
