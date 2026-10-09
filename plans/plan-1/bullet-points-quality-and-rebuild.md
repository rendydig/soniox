# Plan — Bullet Points: meaningful content, crossfade, and a Rebuild button

Status: proposed (not implemented)
Area: `src/bullet_points_worker.py`, `src/controllers/bullet_points_controller.py`,
`src/ui.py`, `websocket-server/public/components/BulletPointsList.js`,
`websocket-server/public/index.css`

## Problem

The rolling bullet list currently restates the conversation one bullet per line
(e.g. a 6-line chat produced 5 bullets like "Host pauses to gather thoughts")
instead of extracting substance. Auto-update works (15 s timer / flush at 12
buffered lines), but there is no way to rebuild the list from the whole
conversation, and updates swap text with no visual transition.

## Decisions (confirmed)

- Prompt: **strict** — only substance.
- Animation: **true crossfade** (fade old out, fade new in).
- Rebuild button: label **"Rebuild"**.
- Rebuild scope: **entire** session transcript.
- During rebuild: **keep** the current list visible until the new one arrives.

## Part A — Meaningful bullets (prompt only)

File: `src/bullet_points_worker.py` — rewrite `SYSTEM_INSTRUCTION`.

- Extract only **topics, decisions, facts, numbers, open questions, action items**.
- Explicitly ignore greetings, filler, acknowledgements, and turn-by-turn
  narration ("host pauses", "speaker agrees").
- Merge aggressively; prefer **fewer, denser** bullets; an empty/short list is
  acceptable for pure small talk — do **not** pad to one bullet per line.
- Keep the existing contract: max ~12 words each, `<= BULLET_MAX_ITEMS`,
  clear English, output **ONLY a JSON array of strings**.

No change to `_parse_bullet_json`, the controller, WebSocket messages, or the
session format.

## Part B — Crossfade animation

Files: `websocket-server/public/components/BulletPointsList.js`,
`websocket-server/public/index.css`.

- Add a `BulletItem` sub-component (`text`, `index`) that:
  - holds `shown` text + a phase (`idle` / `out` / `in`) in state;
  - on a same-index text change: fade old out (`opacity -> 0`, ~180 ms), swap
    `shown`, fade new in, then return to `idle`.
  - New indices (beyond the previous list) start in `in` (fade in on first paint).
- Keep the `<span class="bullet-number">` marker **outside** the animated span so
  the number doesn't move.
- `index.css`: `.bullet-text { transition: opacity 180ms ease }` plus `.out` /
  `.in` classes; add a `@media (prefers-reduced-motion: reduce)` override that
  swaps instantly.

## Part C — "Rebuild" button (full rebuild from the whole conversation)

### Backend — `src/controllers/bullet_points_controller.py`

Add `hard_regenerate(self, lines)` where `lines` is a list of `(source, text)`:

- Clear `_buffer` and `_inflight_lines` (the full transcript supersedes anything
  buffered).
- If a worker is running: `stop()` it, move it to `_old_workers`, set
  `_worker = None`, cleanup — so its suppressed result can't overwrite the rebuild.
- If `lines` is empty: log + emit a status, return (no-op).
- Otherwise `_start_worker([], lines)` — empty current list + entire transcript =
  rebuild from scratch. Works with auto on/off (like the hotkey).
- Keep the existing list visible until the result arrives; `_start_worker` emits
  `"started"` (UI shows "Updating…"), `_on_result` emits `"complete"` and persists
  via `_on_bullet_points_updated` -> `session_store.set_bullets`.

### Backend — `src/ui.py`

- `_handle_webview_message`: add
  `elif msg_type == "regenerate_bullet_points": self._regenerate_bullet_points()`.
- New `_regenerate_bullet_points(self)`: read
  `session_store.snapshot()["transcriptions"]`, map to
  `[(e.get("source"), e.get("text"))]`, call
  `bullet_points_controller.hard_regenerate(lines)`.

### Frontend — `websocket-server/public/bullets-app.js`

- Wrap `<h2>☑ Bullet Points</h2>` in a small header row and add a text button
  **"Rebuild"** that sends `{ type: 'regenerate_bullet_points' }`, styled like the
  existing `.pane-control-btn` controls.

### Worker (optional, cosmetic)

- Add a `rebuild: bool` flag to `BulletPointsWorker` so the user message reads
  "Full conversation transcript:" and the prompt treats the empty current list as
  a from-scratch rebuild. Behavior is correct without it.

## No changes needed

- `websocket-server/server.js` — unknown message types are already rebroadcast
  (`server.js:214`), reaching the Python app.
- WebSocket protocol and `sessions/current.json` format.

## Verification

```bash
venv/Scripts/python.exe -m py_compile \
  src/bullet_points_worker.py \
  src/controllers/bullet_points_controller.py \
  src/ui.py
```

Open `http://localhost:8765/bullets`, click **Rebuild**, confirm
status -> "Updating…" -> new list crossfades in.

## Notes / tradeoffs

- Rebuild sends the **entire** transcript (up to `SESSION_MAX_TRANSCRIPT_LINES`,
  500) in one call — most faithful, but can be large/costly and may approach
  context limits on very long sessions. Accepted.
- With auto on, a normal timer flush is skipped while the rebuild worker runs
  (`_maybe_flush` guards on `_worker.isRunning()`); buffered lines are cleared at
  rebuild time, so nothing is double-counted.
- Removed/merged bullets disappear instantly (only text changes at a given index
  crossfade); list-length changes are not animated. Accepted for simplicity.
