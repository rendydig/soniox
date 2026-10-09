# Plan — UI polish: live header, pane backgrounds, gallery grid, bar buttons

Status: proposed (not implemented)
Area: `websocket-server/public/components/App.js`,
`websocket-server/public/components/StatusIndicator.js`,
`websocket-server/public/components/ScreenshotGallery.js`,
`websocket-server/public/index.css`, `src/ui.py`,
`src/ui_components/switch_button.py`, `src/ui_components/control_buttons.py`

## Clarification

`src/ui_components/live_window.py` contains **no** "Status / Enable Translation /
Enable Correction" controls — it only hosts a `QWebEngineView` loading
`http://localhost:8765/live`. Those controls live in the shared web frontend
(`components/App.js` + `components/StatusIndicator.js` + `index.css`). Likewise
the Gemini/Bullet backgrounds and the screenshot grid are web CSS. So those edits
are made in the web app, not in the Python pane classes.

`App.js` is shared by the main monitor page (`/`) and the live pane (`/live`);
`index.css` is shared by every page. Scope is handled per the decisions below.

## Decisions (confirmed)

- Status label: **hide only in the live pane** (keep it on the main monitor page).
- Backgrounds: **also remove the purple body gradient** (affects the monitor page).
- Bar button height: **24px** (matches the switch's current size).

## 1. Live pane header — compact status + toggles

- **`components/StatusIndicator.js`**: accept a prop (e.g. `showText = true`).
  When false, render **only the colored circle** (drop the `Status :` text and the
  `Connected/Disconnected - Reconnecting...` span). Keep the state in a
  `title`/`aria-label` so it isn't lost.
- **`components/App.js`**: pass `showText=${!hideControlType}` (the live pane is
  the only caller that passes `hideControlType`). Keep the circle and the two
  toggles in one row next to each other; optionally shorten labels to
  `Translation` / `Correction`.
- **`index.css`**: `.header { flex-wrap: nowrap; gap: 8px; }`; smaller
  `.status-indicator` (~10px); `.toggle-label { gap: 4px }`; checkbox 14px;
  `.toggle-text { font-size: 12px }` so it fits a ~360px pane.

## 2. Remove colored backgrounds

File: `websocket-server/public/index.css`.

- `.live-text.gemini-view` -> `background: transparent` (drop `#ede9fe`); remove
  the left accent border (part of the color).
- `.live-text.bullet-view` -> `background: transparent` (drop `#ecfdf5`); remove
  the left accent border.
- `.screenshot-gallery` + `.screenshot-gallery-header` -> transparent (drop
  `#f5f3ff`).
- `body` -> remove the purple gradient `linear-gradient(135deg, #667eea, #764ba2)`;
  use a plain/white background. (Confirmed: also affects the main monitor page.)

## 3. Screenshot gallery -> 7 per row

- **`index.css`**: `.screenshot-grid { grid-template-columns: repeat(7, 1fr);
  gap: 4px; }` (from `repeat(4, 1fr)`).
- **`components/ScreenshotGallery.js`**: update the "4-column grid" comment to
  7-column.

## 4. Main bar — equal button heights + adjacent dropdown arrow

- **`src/ui.py`**: define a shared `CONTROL_HEIGHT = 24` and
  `setFixedHeight(CONTROL_HEIGHT)` on `btn_start`, `btn_new`, `mode_button`,
  `tool_button`, `settings_button` (and `close_button` for consistency).
- **`src/ui_components/switch_button.py`**: keep the pill at 24px (already 24);
  no geometry change required at 24px. If a shared constant is preferred, expose
  the height so it can be set from `ui.py` without recomputation surprises.
- **Arrow placement**: set `mode_button.setText("Mode ▾")` /
  `tool_button.setText("Tool ▾")` and add
  `QToolButton::menu-indicator { image: none; width: 0; }` to the stylesheet in
  `_apply_styles`, so the `▾` sits immediately after the label instead of the
  native arrow pinned to the far right.
- **`src/ui_components/control_buttons.py`**: no logic change needed (heights set
  from `ui.py`), unless you prefer the height set inside the widget.

## Verification

```bash
venv/Scripts/python.exe -m py_compile \
  src/ui.py \
  src/ui_components/control_buttons.py \
  src/ui_components/switch_button.py
```

Launch the app, open `http://localhost:8765/live`, `/gemini`, `/bullets`, and the
main monitor page; confirm: compact circle-only status in the live pane, no
purple/green content backgrounds, 7-column gallery, and equal-height bar buttons
with the `▾` next to Mode/Tool.

## Notes / tradeoffs

- Removing the body gradient and shrinking the shared status row changes the main
  monitor page too (accepted for the gradient; the status text is kept there).
- `repeat(7, 1fr)` on a 400px default Gemini pane yields ~50px thumbnails; the
  pane is still user-resizable.
