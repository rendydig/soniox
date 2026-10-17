# AGENTS.md

## Project
Desktop transcription/translation app (Python + PySide6) plus a Node.js WebSocket
server that broadcasts results to a web UI.

- `main.py` / `src/` — PySide6 desktop app (Soniox STT streaming + Gemini translation)
- `websocket-server/` — Node.js broadcast server + browser UI on `http://localhost:8765`

## Setup
```bash
# Python (venv already created with Python 3.13)
# Windows: venv/Scripts/python.exe · macOS/Linux: venv/bin/python
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
started it (a manually started server is left untouched). An adopted listener is
probed once with `GET /context`; when it does not serve that route (a leftover
process running older code) the manager logs a warning, because the Context pane
would otherwise just stay blank. To run the server
yourself instead:
```bash
cd websocket-server && npm start
```
Web monitor: `http://localhost:8765`. Gemini-only suggestion page: `http://localhost:8765/gemini`.

It also starts the **Go hub** the same way when nothing is listening on 8770
(`src/hub/manager.py`), writing to `logs/hub.log`, and stops it on close. The app
*owns* the hub (`HubManager(tie_lifecycle=True)`): a hub already listening is
adopted instead of ignored, so it is terminated on close either way, and on
Windows the hub (spawned or adopted) is put in a job object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` so the kernel kills it whenever the app dies
— including a crash or a Task Manager kill, where `closeEvent` never runs. A
listener that is not one of our hubs (foreign process, unknown pid) is left
alone with a warning. `tools/hubctl.py` and the `_tmp_hub_*` smokes use the
default `tie_lifecycle=False`, so a hub they start still outlives the command.
The hub is standalone-runnable: see "Central hub" below.
```bash
cd hub && go build -o hub.exe ./cmd/hub && ./hub.exe   # or just let the app start it
venv/Scripts/python.exe tools/hubctl.py state          # inspect (starts it if needed)
```

## Configuration
`.env` at the repo root (gitignored; see `.env.example`) must define:
- `SONIOX_API_KEY` — required (streaming STT)
- `GEMINI_API_KEY` — required when `AI_PROVIDER=gemini` (default)
- `GROK_API_KEY` — optional (grammar correction in `websocket-server/gemini-correction.js`)
- `SONIOX_WS_URL` — optional; overrides the Soniox WebSocket endpoint (default
  `wss://stt-rt.soniox.com/transcribe-websocket`). Used by the stress harness to point
  the app at a local fake Soniox server.
- `SELF_CONTEXT_FILE` / `SPEAKER_CONTEXT_FILE` — **seed + fallback only** since the Context
  pane landed: the live selection is owned by `websocket-server/context-store.js` and stored in
  `context_state.json` (gitignored). They are read once, on the first run, to seed the Host /
  Speaker selection, and read by the Python worker only while the web service is unreachable.
  Each role's file may live anywhere — inside or outside the repo.

Central hub (Go, `hub/`; started on demand like the Node server):
- `HUB_ADDR` — NDJSON/TCP listen address (default `127.0.0.1:8770`, loopback only)
- `HUB_HTTP_ADDR` — debug HTTP address (default `127.0.0.1:8771`; `-` disables). `/healthz` and `/state`
- `HUB_TOKEN` — optional handshake token; when set, every client must send it in its `hello` frame
- `HUB_BIN` — explicit path to the compiled binary; otherwise `hub/hub[.exe]` is used and a missing
  binary is built once with `go build` (skipped when `go` is not on PATH)
- `HUB_ENABLED` — `false` runs the app with no hub at all (every publish becomes a no-op)
- `HUB_EVENTS_PATH` (default `logs/hub-events.jsonl`) and `HUB_SNAPSHOT_PATH`
  (default `sessions/hub-state.json`) — the hub's JSONL event log and debounced snapshot

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
- `AUTO_REPLY_DEBOUNCE_MS` (1500) — debounce for a final **without** Soniox's `<end>` marker.
- `AUTO_REPLY_ENDPOINT_DEBOUNCE_MS` (1500) — delay for a final **with** `<end>` (true end of the
  utterance). It now debounces like the non-endpoint path instead of firing immediately. The
  `<end>` flag rides as the 4th arg of the `transcription_update` signal
  (`src/workers.py` → `src/controllers/transcription_controller.py` → `src/ui.py`).
- `SONIOX_MAX_ENDPOINT_DELAY_MS` (800; Soniox default 2000), `SONIOX_ENDPOINT_LATENCY_ADJUSTMENT_LEVEL`
  (2) and `SONIOX_ENDPOINT_SENSITIVITY` (0.4) — sent in the Soniox session config
  (`src/workers.py`) so endpoint detection emits `<end>` sooner. Aggressive preset: faster but
  can slightly reduce word-recognition accuracy and split long speech into more segments; lower
  them to trade speed back for accuracy.
- `AUTO_REPLY_FILLER_FILTER` (true) — when on, an utterance that is *nothing but* acknowledgments
  (`"Okay."`, `"Exactly. You nailed it."`) skips the AI call and emits `skipped`
  ("Filler utterance") instead of spending a suggestion on it (`src/filler_filter.py::is_filler`:
  a conservative closed list, and every sentence-sized segment must be one, so a short-but-real
  answer like "Right, but the brief still gets lost" is never filtered). The manual path
  (`Ctrl+R` / the pane's "Reply now") passes `allow_filler=True` and always answers.
- `AUTO_REPLY_CONTEXT_DIGEST` (false, `_env_bool`) — when on, the reply prompt carries the
  **session digest** the app already computed but used to throw away: the bullet list, the
  locked bullets, the extracted KYC speaker profile, the confirmed brief and its own prior
  suggestions (`src/reply_context.py::build_digest` → `gemini_worker._digest_block`, a
  `Context digest:` section placed after the profile lines and before `Objective:`). Opt-in so
  the change can be measured: with it off (or with an empty digest) the rendered system
  instruction is **byte-identical** to the pre-digest one (asserted in `[18]`). Caps:
  `AUTO_REPLY_MAX_BULLETS` (20, newest kept), `AUTO_REPLY_MAX_BULLET_CHARS` (160, per bullet
  and per prior suggestion), `AUTO_REPLY_MAX_PROFILE_ITEMS` (5, per KYC list field),
  `AUTO_REPLY_MAX_BRIEF_CHARS` (1200), `AUTO_REPLY_MAX_PRIOR_SUGGESTIONS` (3). The digest is
  rebuilt (pure, no AI call, no disk I/O) whenever the bullet list, the speaker profile or the
  confirmed brief changes and after each reply — the current brief is the *confirmed* one only.
  `_stream_reply` logs `System instruction: <n> chars (digest=on|off, objective_focus=on|off)` at
  DEBUG (markers only, never the prompt text), which is how the block is confirmed from the
  terminal while the app runs.
  Prior suggestions come from the conversation turns: `TranslationController._record_suggestion`
  stamps each finished reply onto the Speaker turn it answered (the analysis preamble is
  stripped, the turn is **replaced** rather than mutated so the session writer's shallow
  snapshot cannot race it), while `_build_messages` keeps ignoring the field.
  **Measured 2026-10-17** (`AUTO_REPLY_CONTEXT_DIGEST=1 AUTO_REPLY_LIVE_TESTS=1
  venv/bin/python tools/auto_reply_report.py --repeat 3 --out reports/auto-reply-digest.md`,
  deepseek-v4.1-flash via OpenRouter, reasoning off) against the flag-off baseline
  `reports/auto-reply-report.md`: two digest-on runs scored `OK=4` and `OK=6` of 14 cases versus
  `OK=4` for the baseline, with Bagian A identical in all three (it re-scores recorded answers).
  The per-scenario verdicts moved in **both** directions — L10 was `grounding_late` in the baseline
  and grounded in both digest runs, L2 slipped to `grounding_late` once — so this is directional
  evidence, not a proven win; the flag stays off by default. The report's appendix now prints
  whether the digest was on (`digest_enabled`) and that the `Objective focus:` block stays out of
  the prompt while nothing is tracked.
- Session objectives (the pane's Objectives tab) — `OBJECTIVE_DEBOUNCE_MS` (2000, re-armed by
  every finalized Speaker line), `OBJECTIVE_MIN_STREAK` (2, the hysteresis that keeps the
  tracker from flip-flopping), `OBJECTIVE_MAX_ITEMS` (20), `OBJECTIVE_MAX_HISTORY` (200),
  `OBJECTIVE_MAX_LINE_CHARS` (300) and `OBJECTIVE_WINDOW_LINES` (20).

Reference context (the four interpreting workers, see the Context pane section):
`REFERENCE_CONTEXT_MAX_CHARS` (6000) clips each role when the shared block is rendered, and
`CONTEXT_COMPACT_MIN_CHARS` (400) is the floor below which the Compact button refuses locally
(`too_short`) instead of spending a call.

"Last Picked Up" (the Bullet Points pane's third tab) uses its **own** pair of debounce
constants, separate from auto-reply: `LAST_PICKUP_DEBOUNCE_MS` (2000) and
`LAST_PICKUP_ENDPOINT_DEBOUNCE_MS` (2000). Every finalized **speaker** line re-arms the timer
(`src/ui.py` → `LastPickupController.schedule`), so a pickup AI call fires only once the speaker
pauses — the `<end>` path no longer fires at 0 ms. Host lines are buffered into the window but
never schedule a pickup; the whole rolling window (`LAST_PICKUP_MAX_LINES`, 40) is sent to the
AI (`src/last_pickup_worker.py::SYSTEM_INSTRUCTION`), which answers with the latest speaker
intent as one or two paragraphs separated by a blank line: first in natural Bahasa Indonesia,
then the same content prefixed with the speaker's language name (e.g. `English: ...`) — the
second paragraph only when that language is not Indonesian (otherwise one paragraph). The pane
renders both because `.pickup-text` (`index.css`) sets `white-space: pre-wrap` (the
`.live-text.pickup-view` default of `normal` would collapse the newlines).
Two manual triggers fire it on demand regardless of the auto toggle, both routed through
`MainWindow._trigger_last_pickup_now` (silent, no-op+log when the Bullet Points pane is hidden,
mirroring `CTRL+ALT+P`): the system-wide **`ALT+SHIFT+L`** hotkey and the pane's **"Pick up now"**
button on the Last Picked Up tab (`bullets-app.js` → `{"type":"trigger_last_pickup"}` →
`_handle_webview_message`). They call `LastPickupController.trigger_now()`, which runs the worker
even with `auto` off (`_maybe_run(force=True)`; a press mid-flight queues one forced rerun).

**"Summary"** (the Bullet Points pane's fourth tab) is a one-click, **one-shot** whole-session
summary. The **Summarize** button sends `{"type":"summarize"}`; `MainWindow._summarize_now` takes
one `session_store.snapshot()` and feeds the transcript lines (the same
`(source, text, timestamp)` mapping the rebuild uses), the bullet list and the speaker profile to
`SummarizeController.trigger_now` → `SummarizeWorker` (`src/summarize_worker.py`), which reuses the
`.env` provider/model with reasoning off. The reply is **structured markdown** — fixed sections
`## Overview` / `## Key Points` / `## Decisions` / `## Open Questions` / `## Next Steps` /
`## Speaker Highlights`, written in the conversation's language, with empty sections omitted — and
is broadcast as `{"type":"summary","text":...}` then rendered via the shared `<Markdown>` component
in `components/SummaryView.js`. Progress rides `{"type":"summary_status","status":...}` (`started`
→ "Summarizing…", `error`/`failed`, and `no_input` → "Nothing to summarize yet", auto-cleared after
2.5 s). There is **no timer and no auto mode** (button only, no hotkey); each line is truncated to
`SUMMARY_MAX_LINE_CHARS` (300). The finished text is persisted as the string session field
`summary`, so a pane reload / reconnect restores it through `session_state`
(`useTranscriptionHandlers.handleSummary` / `handleSessionState`).
The tab is also **editable**: it opens in **preview** (rendered markdown) and a **double-click**
inside it switches to an **edit** mode (a raw-markdown `<textarea>`). Typing auto-saves with an
800 ms debounce (`SummaryView.js` → `{"type":"summary_save","text":...}` → `_on_summary_updated`,
which persists and echoes the `summary` topic so every state view agrees); a **Back** button flushes
any pending edit and returns to preview. Switching tabs or the editor's `blur` also flushes, and a
"Saving…"/"Saved" chip shows the debounce state. The AI **Summarize** button is hidden while
editing; locking it out keeps an in-flight or generated summary from clobbering a manual edit.

**"Consulting"** (the Bullet Points pane's fifth tab) is a manual three-step pipeline:
**client-confirmed brief → gap analysis → execution roadmap**. It is deliberately one tab with
three stacked sections, **manual only** (one button per section, no timer/auto), so cost is bounded
per click. `ConsultingController` (`src/controllers/consulting_controller.py`) is modelled on
`SummarizeController` with a per-call `mode` in `("brief", "gaps", "roadmap")`; it runs **one worker
at a time** (busy guard), so the three buttons are mutually exclusive while a call is in flight.
`ConsultingWorker` (`src/consulting_worker.py`) picks one `SYSTEM_INSTRUCTION` per mode and assembles
the user message from the transcript lines (`[source] text`, truncated to `CONSULTING_MAX_LINE_CHARS`,
300), the speaker profile, the mirrored Speaker/Host context, an optional confirmed brief and the
flagged gaps; it reuses the `.env` provider/model with reasoning off (same as Summary).
- **Client brief** — the **Draft brief** button sends `{"type":"draft_brief"}`; the reply is
  structured markdown (`## Goals` / `## Pain Points` / `## Constraints` / `## Success Metrics` /
  `## Scope` / `## Open Questions`, empty sections omitted, grounded in the `[speaker]`'s own words).
  It is **editable** exactly like the Summary tab (preview → double-click → raw-markdown `<textarea>`,
  800 ms debounce → `{"type":"consulting_save","mode":"brief","text":...}` → `_on_consulting_updated`).
  **Confirm** sends `{"type":"confirm_brief"}`, which freezes the brief as the locked reference
  (`brief_meta = {"confirmed": true, "confirmed_at": iso}`) and echoes the chip state. **Any change to
  the brief — an AI (re)draft or a manual edit — clears the confirmation** (`brief_meta = {"confirmed":
  false}`), so a changed brief must be re-confirmed; the pane's chip shows `Draft` vs `Confirmed`.
- **Gap analysis** — the **Analyze gaps** button sends `{"type":"analyze_gaps"}`; the worker compares
  the conversation against the **confirmed brief** when present, else falls back to the speaker
  profile (+ Speaker context). It emits a markdown bullet per genuine gap (`**<flag>** — why it's a
  gap`, then `Ask: "<question>"`), covering only thin-answer-for-goal-complexity, contradictions,
  missing metrics and unstated constraints; empty when nothing. The section shows a reference badge
  (`Confirmed brief` vs `Speaker profile`).
- **Execution roadmap** — the **Generate roadmap** button (`{"type":"generate_roadmap"}`) is
  **disabled with a hint until the brief is confirmed**; it turns the confirmed brief + flagged gaps
  into a short summary line then 4–7 ordered steps (discovery/validation before build), folding every
  gap into a step.
- Each section renders via the shared `<Markdown>` component in `components/ConsultingView.js`
  (green heading overrides so the renderer matches the pane accent). Progress rides
  `{"type":"consulting_status","mode":...,"status":...}` (`started`, `error`/`failed`, `no_input` →
  per-section notice, auto-cleared after 2.5 s). Each finished section is broadcast as
  `{"type":"consulting","mode":...,"text":...,"confirmed":<bool for brief>}` and persisted as the
  string session fields `brief` / `gaps` / `roadmap` plus the object field `brief_meta`, so a pane
  reload / reconnect restores all of it through `session_state`
  (`useTranscriptionHandlers.handleConsulting` / `handleSessionState`). An empty transcript shows a
  `no_input` notice per section instead of a dead button; there is **no hotkey**. `_restore_session`
  seeds the controller, New Session clears + archives it, and `closeEvent` cleans the worker up.

**"Objectives"** (the Bullet Points pane's sixth tab) is the **session-level list of what the
conversation is working towards** — independent of the Purpose — plus which one is currently
active and a timeline of the transitions. `ObjectiveController`
(`src/controllers/objective_controller.py`) mirrors `LastPickupController` (lines are always
buffered for free into a rolling window of `OBJECTIVE_WINDOW_LINES`; every finalized Speaker line
re-arms a single-shot `OBJECTIVE_DEBOUNCE_MS` timer, so a prediction fires only once the speaker
pauses; one prediction at a time with a single queued rerun) and adds the bullet-points lock
semantics. Predictions come from `ObjectiveWorker` (`src/objective_worker.py`): **JEV first** —
its `current_objective` choice question is asked against the session objectives — and the **LLM
fallback** (one small `{"objective","confidence"}` classification call, reasoning off) when JEV is
disabled/unavailable/unconfident, so the default (`JEV_ENABLED=false`) user is tracked too. Both
paths carry the Host/Speaker **reference context** (the JEV path through `build_state`, the LLM
fallback through `render_reference_context`), with an instruction that it is interpretation only
and never an objective. The
reply worker's own JEV decision call answers the same question for free when a voice reply
happens (`GeminiAutoReplyWorker._run_objective_decision` → the `objective_observed` signal →
`MainWindow._on_objective_observed`).
- `src/objectives.py` holds the pure rules: `objective_key` (mirrors `purpose_store.slugify`),
  `align_locks`, `locked_index`, `resolve_active` (**a locked objective beats the prediction**;
  the resolved dict is `{index, text, locked, confidence, source}`, `{}` when nothing is tracked)
  and `observe` — the hysteresis: a transition commits only after `OBJECTIVE_MIN_STREAK` (2)
  consecutive agreeing predictions, an out-of-range/`-1` prediction resets the streak, and a lock
  pins the tracker immediately (`source: "lock"`, confidence 1.0). Locking commits the pin (meta
  plus one history entry); unlocking leaves the focus where it was. The tracker state is
  `objective_meta` (`{active, confidence, source, updated_at}` + the `pending`/`streak` hysteresis
  state) and every **committed** transition appends `{ts, index, text, confidence, source}` to
  `objective_history`.
- The reply prompt gains a soft `Objective focus:` block (`gemini_worker._objective_block`) naming
  the resolved objective, its confidence/source and — when locked — "This objective is locked by
  the user; serve it."; it renders only when something is tracked, so an unused tracker leaves the
  prompt byte-identical. JEV is asked about the objectives through
  `decision_client.build_questions(..., objectives=…)` / `build_state(..., objectives,
  active_objective)`, which also repurpose the previously-dead `objective_N` noul questions to the
  session list (the purpose's `objective_checklist` stays the fallback).
- Messages: the pane sends `add_objective` (empty/duplicate → an `objectives_status` `no_input`
  notice), `remove_objective`, `set_objective_lock` (`{index, text, locked}` — resolved by text
  first, mirroring the bullet locks) and `trigger_objective_prediction`; the app broadcasts
  `{"type":"objectives", items, locks, active, pending, satisfied}`,
  `{"type":"objectives_history", entry}` per committed transition and
  `{"type":"objectives_status", status, message?}` (`started` / `predicted` / `error` /
  `no_input` / `complete`). `_send_session_state` also carries `objective_active` and
  `objective_pending`, so a reloaded pane never re-implements the lock precedence in JavaScript.
- **"Predict now" is a manual, immediate prediction** (`ObjectiveController.predict_now`):
  - it commits the **first** answer (`observe(..., min_streak=1)`) instead of waiting for
    `OBJECTIVE_MIN_STREAK` agreeing ones — the hysteresis exists to stop the *automatic* tracker
    flip-flopping, not the user. The automatic path (debounce/`schedule`) still needs 2.
  - it **seeds the window from the persisted transcript** (`MainWindow._transcript_pairs()` →
    `predict_now(lines=…)`), because the tracker's rolling window only holds the current launch;
    after a restart a predict would otherwise run against nothing.
  - it **reports what it decided** via an `objectives_status` `predicted` frame with a message
    (`Predicted: <text> (p=0.62 · llm)` / `No objective fits the conversation yet` /
    `Still working on: <text>`), which the pane shows for 5 s. Before, the outcome was silent.
  - a manual result is committed even when the window moved on (an automatic one is still
    discarded as stale).
  - an empty objective list / an empty window answers with a `no_input` notice carrying a message
    ("Add an objective first" / "Nothing to predict from yet") instead of a raw status.
  - The **unconfirmed candidate** is broadcast as `objectives.pending` (`{index, text, streak}`,
    `{}` when none) and rendered as an amber "Candidate" row plus an item badge, so an *automatic*
    prediction that has not reached its streak yet is visible instead of looking like nothing
    happened.
- Persisted as the session lists `objectives` / `objective_locks` / `objective_history` and the
  object field `objective_meta` (`src/session_store.py`, capped via `SESSION_CAPS`); the pane
  restores them through `session_state`, `_restore_session` seeds the controller and mirrors it to
  the reply prompt, New Session clears + archives it and `closeEvent` cleans the worker up. The Go
  hub does **not** own objectives yet (a follow-up: it would need a topic in
  `hub/internal/store/store.go`).

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

Auto-reply **analysis preamble** (always on for voice auto-replies — not for image replies):
- Every reply is preceded by one **English** line, then a blank line, then the reply in the Speaker's
  language: `Speaker's move: <Assertive|Directive|Commissive|Expressive|Declarative> — what the
  Speaker asked/confirmed/stated`. Built by `_analysis_prompt_lines` / `_analysis_text`
  (`src/gemini_worker.py`) and emitted inside the same `gemini_result` text, so no frontend change was
  needed.
- The Speaker's act is **hybrid**: when JEV is enabled it answers a dedicated `speaker_act` `choice`
  question (`build_questions`, criteria from `speaker_act_criteria()` in `src/speech_acts.py`) and the
  label is pinned into the prompt so it cannot contradict the status line; otherwise the reply model
  classifies the utterance itself. `other`/low confidence falls back to the model.
- Note JEV's *existing* `speech_act` question is the act the **Host** should perform in the reply —
  it is not the Speaker's act. The `SPEECH_ACTS` criteria are Host-framed; `SPEAKER_ACT_CRITERIA` is
  the Speaker-side wording.
- `format_gemini_result` (`src/text_formatter.py`) knows the new header (plus `<Language> Text:`) and
  no longer prepends a newline when a header sits at position 0.

Auto-reply **prompt contract & gating** (F1/F2/F5/F6/F7, shipped with the regression suite below):
- **Grounding rule** (`_build_system_instruction`): when a Host context is attached, the prompt
  carries two bullets — `The Host profile is the source of truth for what the Host offers: answer the
  Speaker's question from it, and never invent product facts that are not in it.` and `Name the
  concrete product mechanism in your FIRST sentence, then explain it; never answer a product
  question in the abstract.` With **no** Host context the pair is replaced by its mirror image —
  `No profile of what the Host offers is available: do not invent product specifics (features,
  integrations, dashboards, pricing, roadmaps)…` — which deliberately avoids the phrase "Host
  profile": `_tmp_context_prompt_check.py` and offline scenario [7] assert that phrase is absent
  when the user selected no context.
  Measured effect: the live scenarios now lead with the product in the first sentence (L1-L4 were
  `OK` in the post-fix report, vs `OK`/`grounding_late` before).
- **Per-role style block** (`style` in `src/purposes.py` → `gemini_worker._style_block`): every role
  may carry `approach` / `tone` / `length` / `answer_first` / `structure`, rendered as a `Style:`
  section right after `Objective:`. `answer_first: true` emits *"If the Speaker asked a question,
  answer it in your first sentence; never open with an acknowledgment or a counter-question."*; the
  two Interviewer roles set it **false** (their job is to ask), so answer-first is per-persona rather
  than one global rule. A role with no `style` — an older `purposes.json` entry, an AI-synthesized
  role — falls back to `DEFAULT_ROLE_STYLE`, so the section is always rendered. The ad-hoc
  tone/length/structure sentences were moved out of each `objective` into that block.
- **Seed-authoritative purposes** (`src/purpose_store.py`): `BUILTIN_PURPOSES` is the immutable seed.
  `purposes.json` (gitignored, schema 2: `{"schema_version": 2, "overrides": {...}, "purposes":
  {...}}`) carries **only** non-built-in (user / AI-learned) entries: `_load()` ignores any on-disk
  copy of a built-in key (`Ignoring stale built-in copy of %r from purposes.json`) and `_write()`
  never dumps the built-ins. The legacy flat `{key: purpose}` shape still loads, and `overrides` is
  reserved for deliberate built-in edits (no UI for them yet). A stale file can therefore no longer
  shadow the seed — the old "editing `src/purposes.py` alone changes the tests, not the running app"
  caveat no longer applies.
- **History hygiene** (`_build_messages`): *all* leading host turns are dropped (not just one) so the
  message list starts with a `user` turn; speaker-side filler turns are dropped (host turns never
  are — what the Host said is the conversation the reply has to continue); and a repeated latest
  utterance is de-duplicated while staying the final user message (a host turn landing after the
  question used to send the question **twice**).
- **Filler filter**: see `AUTO_REPLY_FILLER_FILTER` in the constants list above.
- **Session digest + objective focus** (Phase 1 / Phase 2, both opt-in-ish): the digest above is
  gated on `AUTO_REPLY_CONTEXT_DIGEST`; the `Objective focus:` block (`gemini_worker._objective_block`)
  only renders when the tracker has a resolved objective, so an unused feature leaves the prompt
  byte-identical. It is *soft*: a locked objective is marked and the reply is told to serve it, but it
  never suppresses a reply.
- **Queued rerun** (`TranslationController`): a final arriving while a worker is running is queued
  (`_rerun_pending`) and re-run when that worker finishes — result, error or skip — instead of being
  dropped with no suggestion at all (mirrors `LastPickupController`'s `_run_pending`).

## Central hub (Go) — M0 + M1 shipped
`hub/` is a stdlib-only Go process that owns the **live session state** and the
**message bus**: publishers send topics, subscribers receive ordered events. It
never touches audio — all stream lifecycle stays in `SonioxWorker`/the capture
child — so nothing here can abort the PortAudio stream (see
`docs/crash-issu.txt.md`). It replaces the plan's in-process fan-out; the app
keeps working at every phase (M2-M6 in `plans/` are not done yet — the UI still
renders from the Qt signals).

```
hub/
  cmd/hub/main.go              # flags, listeners, graceful shutdown; Version 0.1.0
  internal/protocol/           # envelope, NDJSON framing, topic matching
  internal/server/             # accept loop; per-conn reader + writer goroutines
  internal/store/              # RWMutex state + generic bounded ring
  internal/bus/                # topic -> subscribers, per-subscriber queue
  internal/sched/              # Debounce + Ticker (M4 will own the timing)
  internal/dispatch/           # per-agent job queues + coalescing (M3)
  internal/persist/            # append-only JSONL + debounced snapshot
  internal/httpapi/            # /healthz, /state
src/hub/
  protocol.py                  # envelope helpers; constants mirror the Go side
  client.py                    # HubClient: daemon thread + asyncio loop (mirrors WebSocketClient)
  manager.py                   # HubManager: ensure_running()/stop(), auto-`go build`,
                               # tie_lifecycle (adopt a running hub + Windows job object)
  publisher.py                 # HubPublisher: named publishes, no-op when disconnected
tools/hubctl.py                # debug CLI: state/health/tail/publish/config/reset/restore
```
- **Transport**: NDJSON over loopback TCP — one JSON object per line, `\n`-terminated, max 16 MiB per
  frame (screenshot data URLs ride inside payloads). Chosen over Unix sockets because Python asyncio
  has no `create_unix_connection` on the Windows Proactor loop.
- **Envelope**: `{type, id, ts, topic, seq, role, name, token, topics, op, ok, error, job_id, action,
  text, result, payload}`; unused fields are omitted. Payloads decode with `json.Number` so a re-encoded
  frame is byte-comparable to what arrived (`1` never becomes `1.0`).
- **Handshake**: the first frame must be `{"type":"hello","role":...,"name":...,"token":...}` →
  `hello_ok` or `hello_err`. Roles: `publisher` / `ui` / `agent` / `bridge`.
- **Client → hub**: `publish` · `subscribe` (topic patterns: exact, `prefix.*`, or `*`) · `unsubscribe`
  · `request` (`op` = `snapshot` / `restore` / `reset`) → `response` · `result` / `result_chunk` (agents).
- **Hub → client**: `hello_ok` / `hello_err` · `ack` (subscribe) · `event` (`{topic, seq, payload}`) ·
  `response` · `error`.
- **Topics**: `transcription.partial` / `transcription.final` (`{source,text,endpoint,timestamp}`) /
  `translation.final` / `status` / `error` / `session.config` / `screenshots.add` / `screenshots.clear` /
  `bullets` (`{items,speaker,windows,locks}` — the bullet list, KYC speaker profile, per-update
  windows and per-item lock flags, which always change together) / `command` in; browser-bound mirrors (`gemini_result`,
  `gemini_stream`, `bullet_points`, `purpose_state`, `session_state`, …) fan out unchanged so the
  Node path stays byte-identical.
  **Partials are disposable** (any topic ending `.partial`); finals are never dropped.
- **Sequence numbers are per topic** (`seq` 1,2,3… on `transcription.final`) and ride every `event` so a
  subscriber can detect a gap or a restart.
- **Store** (`internal/store`): the `SessionStore` discipline ported — writers *replace* values, never
  mutate, and `Snapshot()` hands out deep copies. Every list is a fixed-capacity ring (no realloc), with
  the same caps as the Python side: transcriptions/translations 500, conversation 25 (=`MAX_HISTORY_TURNS`),
  `gemini_results` 100, screenshots 20. `bullets` + `bullet_windows`/`bullet_locks` are the exception: they are
  deliberately **uncapped** (append-only, one point per update), so they grow with the session.
  `session.config` and the purpose
  registry are application-level and survive both `reset` and `restore`. `conversation` is derived from
  `transcription.final` (one turn per final, `{text, role: source, suggestion: ""}`), and a publisher's
  `timestamp` is kept verbatim so persisted lines match `datetime.now().isoformat()` exactly.
- **Bus** (`internal/bus`): each subscriber gets its own queue + drain goroutine, so one stalled reader
  cannot block the hub or the others. On a saturated queue it **drops the oldest disposable frame and
  never drops a durable one**; a partial arriving at an all-finals queue drops itself; past `HardCap`
  (4096 pending) the subscriber is **evicted** and its connection closed (visible, never silent loss).
- **Server**: one writer goroutine per connection owns the socket. `c.close()` only signals it; the
  writer drains the outbound queue and then closes, so a final frame (e.g. `hello_err`) is flushed —
  with a 2 s grace timer (and a 10 s per-frame write deadline) bounding a peer that stops reading.
- **Persist** (`internal/persist`): every published topic is appended to `logs/hub-events.jsonl` with
  oversized string values elided (`<N bytes elided>`), and a debounced (2 s) snapshot is written
  atomically to `sessions/hub-state.json` in the `sessions/current.json` shape.
- **Python side**: `HubClient` mirrors `WebSocketClient` (daemon thread + asyncio loop, sends via
  `run_coroutine_threadsafe`, inbound frames marshalled onto the Qt main thread with
  `MainWindow.hub_message`, exactly like `webview_message`); it stays Qt-free. `HubPublisher` is a no-op
  whenever the hub is unreachable, so callers never check the connection. Lifecycle lives in
  `MainWindow.__init__` (right after `_server_manager.ensure_running()`) and `closeEvent`; the manager is
  built with `tie_lifecycle=True`, so the hub is adopted when one is already listening and dies with the
  app even on a force-kill (job object — see the "Run" section).
- **Wired today (M1 dual-write)**: `SonioxWorker` publishes `transcription.partial`,
  `transcription.final` and `translation.final` alongside its existing Qt signals (`_publish_partial` /
  `_publish_final` / `_publish_translation`; the publisher is injected via
  `TranscriptionController.set_hub`, defaulting to a no-op), and the controller publishes `status` /
  `error`. `MainWindow._on_bullet_points_updated` also publishes `bullets` (via
  `HubPublisher.bullets`) alongside the WebSocket frame, so the hub owns the same bullet list, speaker
  profile and windows the panes render. The hub therefore mirrors the same transcript the UI shows —
  verified by `_tmp_hub_pipeline_smoke.py`, which drives the real worker against the fake Soniox server
  and asserts the hub's finals equal the editor's lines.
- **Not done yet**: M2 (UI subscribes to the hub for display; the fan-out in
  `MainWindow._on_transcription_update` moves into the hub), M3 (agents as separate processes via
  `src/hub/supervisor.py` + `internal/dispatch`), M4 (debounce timers move to `internal/sched`), M5
  (persistence replaces `SessionStore`), M6 (fold the Node server in).

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
  with Screen Protection / Gemini Window / Live Window / Bullet Points / Context / Always on Top) · Settings button ·
  `SwitchButton` (shows/hides the input row) · stretch · `StatusBarWidget` · close. The main
  window has **no** output view; transcription output lives in the Live Window pane.
- The bar is **trimmed** to fit its fixed width: the Start button reads "Start"/"Stop" plus the
  session elapsed time, the Mode button reads "Mode" (active mode shown in its tooltip + the
  menu checkmark), and the `StatusBarWidget`'s mode and memory labels are hidden, leaving only
  the eliding `ElidedLabel` status text (`src/ui_components/elided_label.py`). Height is `BAR_HEIGHT`
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
  (`_set_always_on_top`). **The toggle governs all five windows**, not just the bar: it
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

## AI suggestion window
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
- Six **system-wide** hotkeys (work even when the app is unfocused), registered by
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
  - `ALT+SHIFT+L` → manual **"Last Picked Up"** update (`MainWindow._trigger_last_pickup_now`;
    silent, only when the Bullet Points pane is visible — see the Last Picked Up section).
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
  `_send_images_to_gemini` / `_trigger_bullet_points_now` / `_trigger_last_pickup_now` /
  `_toggle_all_panes` are the
  callbacks, and `unregister()` runs in `closeEvent`. The callbacks fire on the Qt main thread,
  so they may touch widgets/capture directly. All six shortcuts are editable in the Settings
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
  With auto on, a repeating `QTimer` (`BULLET_FLUSH_INTERVAL_MS`, 5 min) *polls* (ticks are free
  when the buffer is empty or a worker is running) and it also flushes early at
  `BULLET_MAX_BUFFER_LINES` (120). An idle/auto-off conversation costs **zero tokens**.
- Each call sends the **current list + current speaker profile + only the new lines** to
  `BulletPointsWorker` (`src/bullet_points_worker.py`), which reuses `AIClient.generate` and
  the same `.env` provider/model and returns a JSON **object**
  `{"bullets": [...], "speaker": {...}}` plus a `mode` field. The worker is **delta-aware**: an
  incremental call (`mode: "append"`) asks for and returns ONLY the new points, and the controller
  appends them (`BulletPointsController._merge_new_items`, which drops exact duplicates after
  casefolding/stripping punctuation and near-duplicates by Jaccard token similarity ≥ 0.8); a rebuild
  (`mode: "replace"`) returns the complete list and replaces it. `_parse_result_json` tolerates code
  fences/prose (and a bare JSON **array**, which falls back to bullets + empty profile); malformed
  output keeps the previous state and retries. **There is no cap** — the list grows monotonically
  (the old `BULLET_MAX_ITEMS` was removed, in `src/config.py` too). Every call also carries the
  shared **reference context** (`src/reference_context.py`) — for this worker the **Host half
  only**, because its output *is* the extracted speaker profile (see "The reference block" in
  the Context pane section); the KYC extractor will otherwise copy a pre-identified speaker
  profile into `name`/`occupation`/`location` and `facts`.
- **Windows / checkpoints**: every update also records one entry under `bullet_windows` (a separate
  session list, parallel to `bullets`, so bullets stay strings) —
  `{"mode": "auto"|"rebuild", "start", "end", "lines", "from_index", "to_index"}`. The time range
  is the ISO timestamps of the lines the update covered (`add_line` stamps each buffered line; the
  buffer holds `(source, text, ts)`), and the index range maps it to the bullets it produced. An append
  records `from_index = len(previous)`..`len(new) - 1` (skipped when nothing new); a rebuild **resets**
  the list to a single `rebuild` entry spanning the whole list, because it rewrote every bullet.
- **Per-item Lock (pinned-on-top rebuild)**: each bullet in the pane carries a padlock toggle. The
  lock flags live in a second **parallel** list `bullet_locks` (`list[bool]`, index-aligned with
  `bullets`), so the worker prompt, the `bullets` session list, and the pane's item shape stay
  untouched. Clicking the padlock sends `{"type":"set_bullet_lock","index":i,"text":<item>,"locked":bool}`;
  `MainWindow._handle_webview_message` routes it to `BulletPointsController.set_lock(index, text,
  locked)` (resolves by exact `text` first, else the bounds-checked `index`; returns falsy when the item
  is missing or unchanged), which flips the flag and re-emits `updated`, broadcasting the whole list +
  `locks` back to every pane. Locking is **Rebuild-only**: `hard_regenerate` hands `locked_items()` to the
  worker as the "already captured" block (the worker asks for only the *uncovered* points), and on a
  `mode == "replace"` result the controller composes `locked_items + ai_items` and sets
  `_locked = [True]*L + [False]*N` — a rebuild can therefore never drop or reword a locked point, and it
  can never destroy one (all items locked → the locked block is kept). "Fetch new" and the auto timer are
  untouched: the locked items are already in the current list sent as context and are protected by the
  near-duplicate merge, and `_locked` is only re-aligned (tail padded `False`) as the list grows. `reset()`
  clears the locks; `load_state(items, speaker, windows, locks)` and `_align_locks` pad a short/absent
  list (an older session file) with `False`.
- **Speaker (KYC) profile**: `speaker` in the worker output / session is a dict —
  `{name, location, occupation}` (labelled rows) plus `interests`, `goals`, `pain_points`,
  `facts` (short standalone items, ~8 each, `SPEAKER_MAX_LIST_ITEMS` in `src/config.py`,
  enforced in the prompt **and** by trimming the parsed result). Facts/pain points are only
  extracted from `[speaker]` lines (the host is "us", the speaker is the customer); profile
  fields update **only when the speaker reveals them** (never guessed), unknown = `""`/`[]`.
  `BulletPointsController` holds `_bullets` + `_locked` + `_speaker` + `_speaker_locks` +
  `_bullet_windows`, its `updated` signal is `Signal(list, dict, list, list, dict)` (items,
  profile, windows, locks, **speaker locks**), and
  `load_state(items, speaker, windows, locks, speaker_locks)` seeds all five from a restored
  session.
- **Speaker-profile locks** (pin a KYC value so the AI can never rewrite it): the flags live in
  a **parallel** structure `speaker_locks` — `{field: bool}` for the scalars (`name`, `location`,
  `occupation`) and `{field: [bool, …]}` for the list fields (`interests`, `goals`,
  `pain_points`, `facts`), index-aligned with the profile's items — so the worker prompt, the
  `speaker` dict and the session shape stay untouched.
  - `BulletPointsController.set_speaker_lock(field, index=None, item=None, locked=None)` resolves a
    list entry by exact `item` text first, then by the bounds-checked `index` (a scalar has no
    index and must already hold a value — locking an empty field would only freeze it empty, so it
    is refused); no-ops when nothing changed. `locked_speaker()` returns the locked part of the
    profile in the profile's own shape and is handed to the worker so the prompt can carry a
    `Locked speaker profile (already captured by the user …)` block (both modes).
  - **Enforcement is in `_merge_speaker(incoming)`**, which every AI answer is folded through
    (append *and* rebuild): a locked scalar keeps its current value, a locked list item is kept
    (before the AI's new items) so an update can neither overwrite, reword, reorder nor drop it —
    a locked item also outranks `SPEAKER_MAX_LIST_ITEMS`, since truncating must never discard a
    pinned item to make room for the model's. The flags are rebuilt alongside (the list shape
    changes), so they stay aligned; unlocked values are the AI's answer, as before.
  - Pane: `components/SpeakerProfile.js` renders a padlock on every identity row and every list
    item (reusing the `.bullet-lock` / `.bullet-item.locked` styling, so bullet, objective and
    profile locks read alike) and sends `set_speaker_lock {field, index?, item?, locked}`;
    `SpeakerProfile.js` addresses items by their **original** index, so a padlock click survives
    the empty-slot filtering. The app echoes the whole `bullet_points` frame (now including
    `speaker_locks`), persists it as the session object field `speaker_locks` (aligned to the
    profile's shape on every write and on load, so a stale/absent list cannot pin the wrong item)
    and restores it through `session_state`.
- **Auto / manual / checkpoint:** auto updates run only when the checkbox is on **and** the
  pane is visible; hiding the pane (Tool ▾ or its `−`) pauses the timer but keeps the current
  list as a checkpoint and keeps buffering. Re-showing broadcasts the checkpoint immediately
  and makes one catch-up call. **`CTRL+ALT+P`** (system-wide, `global_hotkeys.py`) does a
  **silent manual update** (`flush_now(force=True)`) that merges only the new buffered lines —
  it works with auto off, but is a no-op (logged) when the pane is hidden (never auto-shows it).
  The bullets tab's **"Fetch new"** button is the same incremental catch-up without the hotkey:
  it sends `{"type":"trigger_bullet_points"}`, `MainWindow` calls
  `flush_now(force=True)`, and when nothing is buffered (and no call is in flight) the app replies
  with a `bullet_points_status` `no_new` notice ("Nothing new yet") that the pane clears itself
  after 2.5 s — so the button never looks dead. It is not a rebuild: the existing list is kept.
- `MainWindow` wires it: `_on_transcription_update` buffers final lines via `add_line`
  (unconditional); `_trigger_bullet_points_now` is the `CTRL+ALT+P` callback (the webview
  `trigger_bullet_points` message routes to the same `flush_now(force=True)`);
  `_on_bullet_points_updated(items, speaker, windows, locks, speaker_locks)` broadcasts
  `{"type":"bullet_points","items":[...],"speaker":{...},"windows":[...],"locks":[...],
  "speaker_locks":{...}}` (persisted via
  `set_bullets` + `set_speaker` + `set_bullet_windows` + `set_bullet_locks` +
  `set_speaker_locks`, and mirrored to the hub via
  `self.hub.bullets`) and
  `_send_bullet_status(status, message="")` broadcasts
  `{"type":"bullet_points_status","status":...}` over the WebSocket (`send_message`, rebroadcast by
  the server). Pane control messages: `hide_bullet_points_window`, `set_bullet_points_window_edge`,
  `regenerate_bullet_points`, `trigger_bullet_points`, `set_bullet_lock`, `set_speaker_lock`.
- **Auto-flush countdown**: `BulletPointsController.countdown_changed = Signal(bool, float)`
  carries `(auto, next_flush_at)` where `next_flush_at` is the epoch deadline of the
  controller's own `QTimer` (`BULLET_FLUSH_INTERVAL_MS`, 5 min). It is re-armed only in
  `_on_interval_tick` (and on `set_auto`), so an early/manual flush never shifts the
  cadence, and cleared to `(False, 0.0)` when auto turns off (checkbox **and** pane
  visible). `MainWindow._send_bullet_countdown` broadcasts
  `{"type":"bullet_points_countdown","auto":bool,"next_flush_at":s,"interval_ms":ms}`,
  also pushed from `_send_session_state` so a reloaded pane resumes the same number.
  The pane (`bullets-app.js`) ticks locally off that absolute deadline (shared by both
  sides) and renders `Next update in 4:32` as `.bullet-countdown` under the tab row
  (left-aligned beneath the *Bullet Points* tab title) — **only while auto is on**.
- `BulletPointsWindow` (`src/ui_components/bullet_points_window.py`) mirrors
  `GeminiWindow`/`LiveWindow` (frameless, always-on-top, `Tool`, drag + width/height resize,
  dock left/right, own `set_capture_protection`) but starts **free-floating** on the right
  (not edge-docked) to avoid colliding with the docked panes. Its web view loads
  `http://localhost:8765/bullets` → `public/bullets.html` + `public/bullets-app.js`
  (server route `/bullets`), rendering `components/BulletPointsList.js` with a custom
  CSS-drawn checkmark. The pane has **six tabs** — Bullet Points / **Speaker** /
  Last Picked Up / **Summary** / **Consulting** / **Objectives**; the Speaker tab renders `components/SpeakerProfile.js` (identity
  rows + `.kyc-*` sections, `.kyc-pain` accent for pain points, shares the update status line and
  an empty-state hint), the Summary tab renders `components/SummaryView.js` (a Summarize button
  plus the markdown summary in preview, or a double-click-to-edit autosaving textarea; green
  overrides so the renderer matches the pane accent), and the Consulting tab renders
  `components/ConsultingView.js` (three stacked sections — brief / gaps / roadmap — see the
  "Consulting" paragraph above), and the Objectives tab renders
  `components/ObjectivesView.js` (see the "Objectives" paragraph below). The bullets
  tab carries two text buttons: **Fetch new** (incremental — merges only the newly buffered lines,
  keeps the list; `trigger_bullet_points`) and **Rebuild** (regenerates the list from the whole
  transcript; also refreshes the profile, since it is one AI call). Each item also carries a padlock
  toggle (`BulletPointsList.js`, a `currentColor` inline SVG with `aria-pressed` and a
  "Lock this point (kept on Rebuild)"/"Unlock" title) that sends `set_bullet_lock`; locked items get the
  `.bullet-item.locked` tint and the amber `.bullet-lock.locked` styling in `index.css`.
- Persisted in `ui_state.json`: `settings.bullet_points` (auto, default false),
  `settings.bullet_points_window_visible` (default false) and a `bullet_points_window`
  geometry block. `_set_pane_edge` swaps any docked pane on the target edge across all three
  panes.

## Sessions (persistence, resume, new session)
- A **session** is the conversation state persisted to `sessions/current.json` (gitignored):  `bullets`, `bullet_windows`, `bullet_locks`, `objectives`, `objective_locks`, `objective_history`, `conversation`, `transcriptions`, `translations`, `gemini_results`, `screenshots`
  (each capped in `src/config.py` except `bullets`/`bullet_windows`/`bullet_locks`, which are uncapped) plus the
  dict-typed `speaker` profile, `speaker_locks` (its lock flags), `brief_meta` and `objective_meta`
  and the strings `last_pickup`, `summary`, `brief`, `gaps` and `roadmap`.
  `_normalize` keeps only the keys of `_new_session_data()`, so a field missing from
  `SESSION_FIELDS` / `SESSION_OBJECT_FIELDS` is silently dropped on load — and `objective_locks`
  is re-aligned (padded/trimmed) to `objectives` there, and `speaker_locks` to the `speaker`
  profile's shape, so an older session file still loads.
 `SessionStore` (`src/session_store.py`) holds it in memory and
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
- **Restore on launch**: `MainWindow._restore_session` seeds
  `BulletPointsController.load_state(bullets, speaker)`,
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
- **Session timer** (inside the Start/Stop button): the button label is composed by
  `_update_start_button_text` as `Start HH:MM:SS` / `Stop HH:MM:SS` (the checked state picks
  the verb, `_format_duration` formats the elapsed time). `MainWindow` owns the state —
  `_session_elapsed_seconds` (accumulated) plus `_session_run_started` (a `time.monotonic()`
  stamp) — and a 1 s `QTimer` (`_session_timer`, `SESSION_TIMER_INTERVAL_MS`) whose timeout is
  wired straight to `_update_start_button_text`. `_on_transcription_started` →
  `_start_session_timer`, `_on_transcription_stopped` (and the error path) →
  `_pause_session_timer` (freezes, keeps the value shown), and `_new_session` →
  `_reset_session_timer`; a launch always starts at `00:00:00` (never persisted). Elapsed time
  comes from monotonic deltas, not tick counting, so a delayed tick can't drift. Because the
  label is natural-width, the button (and the bar's `minimumSizeHint`) grows by the readout;
  proportional digits can make it twitch by a pixel per second (a monospace font on
  `btn_start` is the fix if that bothers).

## Context pane (Host / Speaker context)
The **Context** pane (Tool ▾, hotkey `Ctrl+Alt+C`; macOS `Meta+Alt+C`) edits the two
"pre-identifier" profiles the reply prompt uses: **Host** (`- Host profile (pre-identified): …`)
and **Speaker** (`- Speaker profile: …`). The text it resolves is used by **every AI call that
interprets the conversation or writes a reply** — voice auto-reply, image reply and the JEV
decision call (which always did), the consulting pipeline's Speaker context, and the four
workers that had no context before: **bullet points / KYC profile**, **Last Picked Up**,
**objectives** and **Summary** (see "The reference block" below). Manual translate
(`GeminiWorker`) is deliberately untouched.

- **Ownership**: the Node web service owns the context files
  (`websocket-server/context-store.js`), not Python. It keeps the selection, a 10-entry
  re-select history, the chosen **variant** per role, and a `context_state.json` (repo root,
  gitignored); each role's file may live **anywhere** (inside or outside the repo) and is stored
  repo-relative when it is inside. Nothing here touches the Go hub.
- **Python only mirrors**: every `context_state` broadcast lands in
  `MainWindow._handle_webview_message` → `_apply_context_state`, which mirrors the resolved text
  into `TranslationController.set_context(effective, full=contents)` and fans the same value out
  to `BulletPointsController` / `LastPickupController` / `ObjectiveController` /
  `SummarizeController` (`set_context`), each of which hands it to its worker. No thread, no file
  read on any of those paths. `context_get` is requested on the `connection` frame, so a
  reconnect re-syncs the mirror.
- **Three states, deliberately distinct**: `context is None` = nothing has arrived yet → the
  reply worker falls back to `_load_self_context()` / `_load_speaker_context()` (`.env`, the
  original behaviour); `""` = the user picked **no context** for that role → the prompt line (and
  the reference block) is omitted; a string = the text. Do not collapse these.
- **Missing file is not an error**: `problems[role] = "missing"` (or `"too_large"` for >64 KB),
  `contents[role] = ""` (no context) and the pane shows a red **file not found** badge — the
  selection is kept so the user can see which path to fix. A save to a missing/oversized file is
  rejected with a `context_status` message instead of failing silently.
- **Saving is debounce-on-typing**: 800 ms after the last keystroke the pane sends one
  `context_save`, which **only overwrites the role's currently selected file** (or that file's
  derived `.compacted` sibling — see below) — it never creates one (that is `context_new`,
  driven by a native Save dialog) and never deletes anything. The draft is flushed early on tab
  switch, selection change, variant change, **Compact**, **Save** now, hiding the pane and app
  close (the app sends `context_flush`; `beforeunload` is unreliable in Qt WebEngine). Writes are
  atomic (`tmp` + `rename`), so a reader never sees a half-written file.
- **Live reload**: the store watches the folders of the selected + recent files (`fs.watch`,
  250 ms debounce) and rebroadcasts on an external edit (VS Code); a content signature keeps our
  own writes from bouncing back as a loop.

### The compacted variant ("Compact")
A long context file can be rewritten as a shorter, fact-complete copy with one AI call; the copy
lives **beside** the real file as `<selected>.compacted` and the user chooses which one the AI
receives.

- **Path safety, not a loosened allow-list**: the `.compacted` extension is outside
  `ALLOWED_EXTENSIONS` on purpose. `context-store.js` has a dedicated **derived-path validator**
  (`validateCompactedTarget`) whose only accepted target is exactly
  `resolvePath(selection[role]) + '.compacted'` (with the real file still present); `save()`
  accepts either the selection or that derived path, and rejects anything else with
  `context_status: invalid`. `context_compacted` additionally rejects a `base` that is no longer
  the current selection (`The context changed while compacting`), so a compaction that finishes
  after the user switched files cannot be written to the wrong sibling.
- **The AI call is Python's** (`src/context_compact_worker.py`, one call per press, reasoning
  off, `ai_debug` site `context_compact`); the Node service owns the **writing**. The pane sends
  `compact_context {role, path, text}` (the *real* file's text, so the call never races the
  save-then-broadcast of a keystroke still in flight), `MainWindow._compact_context` runs the
  worker, and the finished text goes back as `context_compacted {role, base, text}`.
  `src/controllers/context_compact_controller.py` mirrors `SummarizeController` (busy guard,
  `started`/`complete`/`error` statuses, `cleanup`).
- **Two variants, one active**: the pane shows an **Original / Compacted** radio pair — mutually
  exclusive — and the editor follows whichever one is active (so each is editable, and the
  autosave target is the active one's path). `context_set_variant {role, variant}` is rejected
  with `missing` while no compacted copy exists. The store reports both the user's `variant` and
  the **`active`** one actually used (a `compacted` choice with no file falls back to `full`),
  plus `effective` — the text the AI calls receive (the reply mirror and the four workers all use
  `effective`), `compacted_path`, `compacted_contents`, `compacted_problem`,
  `compacted_revision`, `compacted_available` and `compacted_stale`.
- **Stale is only badged, never blocked**: `compacted_source_revision[role]` records the real
  file's mtime when the copy was built; a later edit to the real file sets `compacted_stale` and
  the pane shows an amber **out of date** badge — the copy stays selectable and is still used.
  `context_new`/`context_select`/`context_clear_selection` reset the variant to `full`.
- **Empty/short files cost nothing**: `CONTEXT_COMPACT_MIN_CHARS` (400) and an empty request are
  refused locally with a `context_compact_status` notice (`no_input` / `too_short`) instead of
  spending a call, and a compacted result larger than 64 KB is rejected (`too_large`).

### The reference block (the interpreting workers)
`src/reference_context.py` renders the same `Reference context (use it to interpret the
conversation; do NOT copy or restate anything from it as a finding):` block — `Host (us): …` /
`Speaker: …` — into the user message of `LastPickupWorker`, `ObjectiveWorker` (the LLM
fallback; the JEV path got it through `build_state` all along) and `SummarizeWorker`, and into
`BulletPointsWorker` (append **and** rebuild). Each of those system instructions gained a rule
that the block is interpretation only, so a pre-identified profile cannot leak back out as an
"extracted" finding. With **no** context every one of those prompts is **byte-identical** to
the pre-feature one (asserted in `_tmp_context_compact_check.py`). Each role's text is clipped
to `REFERENCE_CONTEXT_MAX_CHARS` (6000, with an explicit `…[truncated at N chars]` marker)
because the objective tracker re-arms on a couple of seconds' debounce — the Compact button is
the intended way to bring a long file under that bound.

**`BulletPointsWorker` gets the Host half only.** Its output *is* the extracted speaker
profile, so handing it a pre-identified speaker profile invites it straight into
`name`/`location`/`occupation` and the `facts` list. Measured with
`_tmp_bullet_kyc_live_check.py` (a synthetic conversation whose speaker identity appears only
in the context): with the full block the profile came back as `name: "Zorblax Quintenhall"`,
`occupation: "CTO of Northwind Turbines"`, `location: "Reykjavik"` — and a stronger prompt rule
(an explicit traceability clause: "a value that appears only in the Reference context was not
said") **reduced but did not remove** it (it recurred in 3 of 3 runs of one batch). The worker
therefore renders the block from `{"host": …, "speaker": ""}`, which is dead reliable and costs
nothing: the host half (what we offer, jargon, project names) is the part that actually helps
interpret the conversation. The other three workers carry both roles (asserted in the same
offline suite).

- **Protocol** (all over the existing :8765 WebSocket, like every other pane):
  Node-handled `context_get` · `context_select {role, path}` · `context_clear_selection {role}` ·
  `context_new {role, path}` · `context_save {role, path, text}` · `context_forget {role, path}` ·
  `context_compacted {role, base, text}` · `context_set_variant {role, variant}`;
  Qt-handled `context_browse {role}` (opens `QFileDialog.getOpenFileName`) ·
  `context_new_request {role}` (opens `getSaveFileName`) · `context_flush` ·
  `compact_context {role, path, text}`;
  Node → all `context_state` (selection · problems · history · contents · revision · the
  compacted block · `variant`/`active`/`effective`) · `context_status`
  (`saved` / `missing` / `invalid` / `too_large` / `no_target`, now carrying `role`) and, from
  the app, `context_compact_status {role, status, message?}` (`started` / `complete` / `error` /
  `no_input` / `too_short`).
  `server.js` serializes the Node-handled ops through a promise queue, so a `context_save`
  followed by a `context_select` cannot interleave.
- **Pane parity**: `ContextWindow` (`src/ui_components/context_window.py`) is a copy of the
  Bullet Points pane (frameless, always-on-top, drag/resize/dock, `⇤`/`⇥`/`−` buttons, screen
  protection). Its visibility is persisted as `settings.context_window_visible` (the Gemini/Live
  panes always start shown), it joins `Ctrl+Shift+M`'s hide-all set, the Always on Top and Screen
  Protection toggles, the webview heap health line (`webview_context_heap_mb`) and the
  edge-collision swap in `_set_pane_edge`. The HTML editor is
  `websocket-server/public/context.html` + `context-app.js`, with a Write/**Preview** toggle
  (Markdown, reusing `components/Markdown.js`), the Original/Compacted radio row (**Compact**
  button + `out of date` badge), and the footer naming which variant is in use.

## Pane layout (free-floating geometry, persisted)
- Every pane (Gemini, Live, Bullet Points, Context) is **free-floating**: a top `PaneDragHandle`
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
- A pane is **docked** (edge-pinned at full height, `is_docked()`) by default — except Bullet
  Points and Context, which start free-floating; moving or resizing un-docks it
  (`_docked = False`). Every pane carries a top-right control
  cluster (`.gemini-controls` / `.pane-controls`): `⇤` (dock left) · `⇥` (dock right) ·
  `−` (hide). The edge buttons send
  `{"type": "set_<pane>_window_edge", "edge": "left" | "right"}` over the WebSocket (same
  rebroadcast path as the hide messages).
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
  `bullet_points_window_visible` (default false), `context_window_visible` (default false), and
  `screen_protection` (default true). `MainWindow._apply_settings_state` restores them (guarding bad values) after the
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
  - **All audio capture runs in a separate process.** `SonioxWorker._capture_supervisor`
    spawns `src/audio_capture_process.py` (`sys.executable -u`, no console window) and
    streams raw int16 mono PCM back over its stdout, forwarding it into the same audio
    queue. This covers **both** the host (microphone, `sounddevice`) and speaker
    (loopback, PyAudioWPatch) workers. It is deliberate: the audio stack can hit a
    **native access violation** — observed in `logs/faulthandler.log`, and reproduced
    only when the *same Bluetooth headset* is used as Host (its mic → HFP) **and**
    Speaker (its loopback → A2DP), i.e. an A2DP↔HFP profile switch — which cannot be
    caught in Python and would otherwise kill the whole app. In a child process it only
    kills the child: the supervisor detects the exit and **restarts it** (backoff,
    `_CAPTURE_MAX_RESTARTS` = 5); past the cap it stops that worker only
    (`_stop_flag = True`). The child's stderr goes to `logs/audio-capture.log`. If the
    child cannot be spawned it falls back to the in-process capture
    (`_in_process_capture`).
  - Clean shutdown: the parent `terminate()`s the child (`_stop_capture_child`) — safe
    because it is a separate process. The in-process fallback keeps the strict order
    `stop_stream()`/`stop()` → `join()` → `close()` → `PyAudio().terminate()`, and
    **skips `close()` if the capture thread is still alive** (closing under a blocked
    native read would itself crash).
- **System audio (macOS)** → CoreAudio/PortAudio has **no loopback API**, so system audio
  is read from the *input* side of a virtual device (BlackHole recommended; Soundflower /
  Loopback Audio also match `MACOS_SYSTEM_AUDIO_HINTS`). Descriptors are dicts:
  `{"backend": "input", "index": int, "rate": int, "name": str}` with the device's
  native rate (48 kHz); the worker opens them through `sounddevice` (the `"input"` branch
  in `SonioxWorker.__init__`). BlackHole 2ch accepts a mono 48 kHz stream, so no channel
  fallback is needed. The user must route output to it (a Multi-Output Device keeps
  playback audible) — the app cannot do that for them.

## Microphone mute (soft mute)
- The control bar has a checkable **mic button** between Start/Stop and New
  (`ControlButtonsWidget.btn_mic`, a `QToolButton` with a painted `mic_icon()`); toggling it calls
  `MainWindow._on_mic_muted_toggled` → `TranscriptionController.set_mic_muted`. **Only the host
  (microphone) worker is muted** — the Speaker (system-audio loopback) keeps streaming. **Not
  persisted** (no `ui_state.json` key), so the app always launches unmuted; the state *is* re-applied
  to the worker the next `start_session()` creates.
- It is a **soft mute**, matching Google Meet: `SonioxWorker.set_muted` only stops the sender from
  sending PCM. The capture child process keeps running (see "Audio capture architecture" — restarting
  the audio stack is exactly the fragile path the child exists to isolate) and the device is never
  opened exclusively, so other apps can keep using the mic. The OS still shows the mic as in use.
- While muted the sender **drains the audio queue** (so it can't back up) and sends
  `{"type": "keepalive"}` — a **text** JSON control frame, never binary — every
  `SONIOX_MUTE_KEEPALIVE_MS` (10 s). That is mandatory: Soniox closes an idle stream after ~20 s
  with no audio (`WebSocket status 1001`), after which unmuting would silently do nothing. Unmuting
  resumes PCM on the next chunk with no reconnect.
- Soniox bills the stream duration regardless of audio, so muting lowers what is transcribed, not the cost.

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
- **Crash/long-run diagnostics** (`src/logging_setup.py::_install_crash_handlers`,
  installed by `setup_logging`): `faulthandler` dumps a per-thread Python stack to
  `logs/faulthandler.log` on a native fault (SIGSEGV/SIGABRT/…), and `sys.excepthook` +
  `threading.excepthook` append unhandled exceptions to `logs/crash.log`.
  `MainWindow._log_health` (every `HEALTH_LOG_INTERVAL_MS`, 30 s) appends a sample to
  `logs/health.log` — RSS, thread count, editor block count, session-file size, and each
  pane's webview JS heap (`performance.memory.usedJSHeapSize`) — so growth over a
  multi-hour session is measurable. `QWebEnginePage.renderProcessTerminated` is logged too.
- **Debug prompt dump** (`src/ai_debug.py`): while the root logger runs at `DEBUG`
  (i.e. `LOG_LEVEL` unset or `DEBUG`, the default), every AI call appends one
  human-readable block to `logs/ai-prompt.log` — the full system instruction, the
  messages, the call metadata (including the `AUTO_REPLY_CONTEXT_DIGEST` flag, rendered
  `digest_flag=true|false`), **the exact request payload the provider client is about to
  send** (`--- payload (exact request) ---`: model, `contents`/`messages`, the generation
  config / `extra_body` and `stream`), and the reply. The payload is reported by the
  clients themselves (`src/ai_client.py` calls `ai_debug.log_payload(...)` right before the
  SDK request, so it is what was really sent, not a paraphrase); the request block is
  buffered per thread between `log_request` and `log_payload`/`log_reply` so the payload
  always lands inside its own request, and a request that never reports a payload is still
  flushed by `log_reply`. `LOG_LEVEL=INFO` turns it off; there is no
  separate env var. Images are base64 data URLs, so only their **count** is dumped and any
  data URL embedded in the payload is replaced by `<image data URL: N chars elided>`.
  The module is pure file I/O (`enabled()` = `isEnabledFor(DEBUG)`; `log_request`
  returns a `call_id` used by `log_reply`, all writes swallow `OSError`), so it never
  changes what is sent to the model. Wired at each worker call site, not in
  `src/ai_client.py`, because the metadata lives in the workers: `auto_reply` (the
  stream in `GeminiAutoReplyWorker._stream_reply`), `other_flow` (`_synthesize`),
  `translation` (`GeminiWorker.run`), `bullet_points`, `last_pickup`, `objective`,
  `summary`/`consulting` and `context_compact` (`ContextCompactWorker`), plus `jev_decision`
  (`DecisionClient.decide`, whose exact
  `{model, state, questions}` POST body rides as the payload). Concurrent workers each write a
  single block per call and request/reply are correlated by `call_id`, so interleaving
  stays readable.

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

## Pane opacity (translucent panes)
- The four always-on-top panes (`GeminiWindow` / `LiveWindow` / `BulletPointsWindow` /
  `ContextWindow`) composite at a configurable **whole-window opacity**, default **70%**
  (`PANE_OPACITY`, `.env`-overridable). `src/pane_opacity.py` owns the clamp
  (`MIN_PANE_OPACITY` 0.3 .. `MAX_PANE_OPACITY` 1.0) and the `apply`; each pane keeps an
  `_opacity`, exposes `apply_opacity()` / `get_opacity()`, and re-applies it in `showEvent`
  (a flag change / re-show recreates the `NSWindow`).
- **Why whole-window opacity (`QWidget.setWindowOpacity`)**: Qt maps it onto
  `NSWindow.alphaValue` on macOS and a layered window on Windows, so the whole window —
  web content included — composites at the requested alpha. Per-pixel translucency
  (`WA_TranslucentBackground` + a transparent `QWebEnginePage`) is **rejected**: QtWebEngine
  renders transparent areas as **black** on macOS. Qt stores the opacity in an 8-bit field,
  so `windowOpacity()` reads back quantized (0.7 → 178/255 ≈ 0.698); `macos_window.py`
  gains `get_opacity()` (a `CGFloat` `objc_msgSend` readback) for the native check.
- Controls are mirrored: the **Tool ▾ ▸ Pane Opacity** submenu (`PANE_OPACITY_PRESETS`
  = 100/90/80/70/60/50%, an exclusive `QActionGroup`) and the Settings dialog's **Pane
  Opacity** slider (30–100, with a `%` label). `_set_pane_opacity()` applies to all four
  panes and `_mirror_pane_opacity()` syncs both controls (relaxing the group's exclusivity
  while a slider value matching no preset is applied); the slider applies live on
  `valueChanged` and persists on `sliderReleased`. Persisted as `settings.pane_opacity` in
  `ui_state.json`; the control bar is out of scope and stays fully opaque.

## Verification
```bash
venv/Scripts/python.exe -m py_compile src/*.py src/controllers/*.py src/ui_components/*.py src/hub/*.py
node --check websocket-server/server.js websocket-server/context-store.js
cd hub && go vet ./... && go test ./...        # add -race for the bus/server tests
```
Manual: launch the app, set Host = mic and Speaker = a `[Loopback]` output, Start,
play audio → `[SPEAKER]` lines should appear in the app and at `http://localhost:8765`.

### Hub smoke tests (throwaway)
- `_tmp_hub_smoke.py` — protocol/lifecycle end-to-end against a real hub: handshake, subscribe,
  ordered events with `seq`, fan-out to two subscribers, `snapshot`/`restore`/`reset`, the JSONL event
  log, the debounced snapshot, and `/healthz` + `/state`. It redirects the hub's artefacts to a temp dir
  and skips the storage checks when a hub it did not start is already running. 31 checks.
- `_tmp_hub_app_smoke.py` — the app-level lifecycle: `MainWindow` starts the hub, publishes through
  `w.hub` (read back by an independent client), and closing the app stops the hub it started. 11 checks.
- `_tmp_hub_pipeline_smoke.py` — M1: the real `SonioxWorker` against the fake Soniox server, asserting
  the hub's finals equal the Live Window editor's lines and that the snapshot holds the same transcript.
  13 checks; `--seconds N` sets the session length.
- `_tmp_hub_lifecycle_smoke.py` — who owns the hub: spawn→`stop()` frees the port; a process that starts
  a hub and then dies (`os._exit`) takes the hub with it (the job object, no `closeEvent`); a
  hand-started hub is adopted (no second process) and killed on `stop()`; a non-hub listener on the port
  is never adopted or killed; `tools/hubctl.py` still leaves its hub running after the command exits.
  26 checks; runs on throwaway ports so the real 8770 hub is untouched.

### Context pane smoke tests (throwaway)
Start a server first for the ones that talk to it (any port works, e.g.
`cd websocket-server && PORT=8790 node server.js`); the pane checks open a window for a
few seconds, because Qt WebEngine cannot render on the offscreen platform here.
- `_tmp_context_prompt_check.py` — the three context states in the reply prompt (`None` →
  `.env` fallback, `""` → line omitted, text → used) plus the JEV `host_profile`/
  `speaker_profile` and the image-reply path. No server needed. 16 checks.
- `_tmp_context_compact_check.py` — Context compaction + the shared reference block, all
  offline (the AI client is stubbed): `src/reference_context.py` (`normalize`, `has_context`,
  the labelled block, the per-role clip at `REFERENCE_CONTEXT_MAX_CHARS` with its marker, the
  reference-only wording); the **four** interpreting workers really carry the block *and*, with
  no context, each prompt is **byte-identical** to the pre-feature one (`BulletPointsWorker`
  append **and** rebuild — which renders the **Host half only**, its Speaker half deliberately
  blanked so a pre-identified speaker profile cannot land in the extracted KYC fields;
  `LastPickupWorker`, `ObjectiveWorker`, `SummarizeWorker` — which carry **both** halves);
  `ContextCompactWorker` (one call, the document in the user message, reasoning off, the
  fact-completeness rule, an empty reply is an error) and `ContextCompactController`
  (`no_input` / `too_short` / `invalid` guards, `started` → `compacted` → `complete`, the busy
  guard, the error path, `reset`/`cleanup`). No server needed. 54 checks.
- `_tmp_context_smoke.py` — the protocol end-to-end with two peers (an "editor" that
  mutates and an "app" that only listens, i.e. the path the reply pipeline uses):
  `context_get` shape, the `.env` seed, `context_new`/`context_save` reaching disk,
  save-only-to-the-selected-file, missing/oversized degradation, the 10-entry MRU history,
  external-edit rebroadcast, `clear_selection`/`forget`, host/speaker independence, and the
  **compacted variant**: the new payload keys (`compacted_path` is exactly
  `<selection>.compacted`, `compacted_available`, `compacted_stale`, `variant`/`active`/
  `effective`), `context_set_variant` refused as `missing`/`invalid`, `context_compacted`
  writing the sibling and becoming active, the foreign-`.compacted`/stale-base rejections, the
  derived path being editable in place, an edit to the real file only badging the copy
  (`stale` yet still `active` and still `effective` — never blocked), switching back and forth,
  and the reset on clear. It restores the previous selection and deletes everything it created.
  86 checks; `CONTEXT_WS_URL` points it at another port.
- `_tmp_context_app_check.py` — the app-side pane parity: builds a real `MainWindow` and
  exercises all twelve `ui.py` places that enumerate the panes (Tool ▾ action, hotkey
  callback, visibility toggle + persistence, dock/edge-swap, always-on-top, screen
  protection, hide-all, `_save_state`, the message handlers, and the Browse/New dialogs with
  `QFileDialog` stubbed) plus the context fan-out: a `context_state` mirrors `effective` into
  the reply path *and* all four interpreting controllers while `contents` (the real file) stays
  reachable for Compact, an empty payload is "no context" (distinct from a malformed one),
  `compact_context` reaches the controller with the pane's text, the mirrored real file is the
  fallback when the message carries none, `_on_context_compacted` sends `context_compacted`, and
  the status/error broadcasts ride the real signal wiring. `ui_state.json`, the session store
  and the purpose store are redirected to a temp dir, and the hub is disabled. 48 checks.
- `_tmp_context_pane_check.py` — the pane really renders: loads `/context` in a
  QWebEngineView and asserts the Preact DOM, the WS connection, the selected path and that the
  editor's text equals the selected file on disk. It first points the Host context at a managed
  temp file, so it no longer depends on which file the machine happens to have selected, and it
  covers the compacted *variant* UI: the Original/Compacted radio pair (the editor follows the
  active one), the Compact button sending `compact_context` with the real file's text, and an
  injected compacted + stale `context_state` frame painting the `out of date` badge, switching
  the radio and sending `context_set_variant` when the other radio is clicked. 27 checks.
- `_tmp_context_autosave_check.py` — the debounce-on-typing loop: selects a temp file, types
  into the textarea, asserts nothing is written during the debounce window, then that the
  file holds exactly the typed text and the pane shows `Saved`. 8 checks.

### Bullet points (throwaway)
- `_tmp_bullet_delta_check.py` — the delta/append contract with the worker start stubbed
  (no AI calls): `_merge_new_items` drops exact + near duplicates but keeps low-overlap
  phrases, `_build_user_message` differs between append and rebuild (and accepts 2- and
  3-tuple lines, naming the locked block when a rebuild carries locked points), an append grows
  the list and fills `from_index`/`to_index` while recording
  no window when nothing is new, a rebuild resets `bullet_windows`, and a payload with no
  `mode` defaults to `replace`. Locks: `set_lock` toggles by index/text and no-ops on the same
  value, a rebuild with two locked items composes `[locked…] + ai` with `_locked ==
  [True,True,False…]`, an append pads `_locked` with `False`, and `load_state`/`reset` keep it
  aligned. Speaker-profile locks: `load_state` pads the flags to the profile's shape, locking a
  scalar / a list item (by text or index) toggles and refuses an empty scalar or an unknown field,
  a locked value survives an AI update and an empty answer (append *and* rebuild) while an unlocked
  one takes the AI's value, a locked item is never dropped by `SPEAKER_MAX_LIST_ITEMS`, the flags
  stay aligned after a merge, and the worker prompt carries the `Locked speaker profile` block in
  both modes (and none when nothing is locked). No server needed. 66 checks.
- `_tmp_bullet_kyc_live_check.py` — the **live re-baseline** of the KYC extraction after the
  worker gained the reference context (opt-in, real provider: `BULLET_KYC_LIVE_TESTS=1`,
  `--repeat N`; exits 0 with a notice when the flag is unset or the provider cannot be built).
  It runs the real worker on a synthetic conversation that says plenty about pain/goals and
  **nothing** about who the speaker is, twice: the no-context baseline and a run whose context
  names a speaker identity it never states (`Zorblax Quintenhall, CTO of Northwind Turbines,
  Reykjavik`) alongside the real `docs/helpy.context.txt` as the Host role. It asserts the trap
  tokens and the Host product terms never appear in the profile or the bullets, that no >=6-word
  run of the context is copied verbatim into a finding, and that the spoken pain points are
  still captured (no degradation). **This is the check that caught the regression**: with the
  full block the model filled `name`/`occupation`/`location` straight from the context, and a
  stronger prompt rule did not fix it reliably — which is why the worker now blanks the Speaker
  half. Verified 2026-10-17 (deepseek-v4.1-flash via OpenRouter): the full-block prompt leaked
  in 3/3 runs, the Host-only prompt in **0/7**.
- `_tmp_bullet_manual_check.py` — the pane's **Fetch new** button, app-side: builds a real
  `MainWindow` (worker start stubbed, no network) and drives `{"type":"trigger_bullet_points"}`.
  An empty buffer replies with a `bullet_points_status` `no_new` notice (with a message) instead
  of a silent no-op; buffered lines start an **incremental** update (`rebuild=False`) carrying the
  existing list + the whole buffered window; `_send_bullet_status` forwards an optional message;
  Rebuild still routes to a `rebuild=True` call from an empty list; a `set_bullet_lock` webview
  message echoes a `bullet_points` frame carrying `locks` and persists it, a `set_speaker_lock`
  message echoes `speaker_locks` and persists them (an unknown field broadcasts nothing), and a
  rebuild with a locked item receives it as `current_bullets`. No server needed. 28 checks.
- `_tmp_bullet_pane_check.py` — the pane really renders (needs a server: `PORT=8793 node
  server.js`): loads `/bullets` in a QWebEngineView, asserts the bullets tab shows Fetch new +
  Rebuild inside `.bullet-header-actions` (pane controls still present), stubs `WebSocket.send`,
  clicks both, and checks the app sent `trigger_bullet_points` and `regenerate_bullet_points`.
  It then pushes a `bullet_points` frame (one item locked) from a second WS client and asserts one
  padlock per bullet, the `.bullet-item.locked` tint + `aria-pressed`, and that clicking a padlock
  sends `set_bullet_lock`. It opens the Speaker Profile tab on a frame with a profile + flags and
  asserts one padlock per identity row and per list item, the `.locked` tint and the scalar
  `aria-pressed`, that clicking a row padlock sends `set_speaker_lock {field, item, locked:true}` and
  clicking a locked list item sends `{field, index, item, locked:false}` (the index is the item's own,
  not the filtered one). Covers the htm template, which `node --check` cannot. 24 checks.
- `_tmp_session_store_smoke.py` — `bullet_locks` round-trips through `current.json` (normalized to
  booleans), is cleared by `new_session`, and an older session file without the field normalizes to
  `[]`; `speaker_locks` round-trips aligned to the `speaker` profile's shape (a short/absent list
  pads with `False`, an absent scalar coerces to `False`).

### Summary tab (throwaway)
- `_tmp_summary_check.py` — `SummarizeWorker` + `SummarizeController` with the AI client stubbed
  (no network): `_build_user_message` carries the transcript, bullets JSON and speaker JSON (lines
  truncated to `SUMMARY_MAX_LINE_CHARS`), `trigger_now([])` returns False and emits `no_input`, a
  normal run emits `started` → `updated` (reasoning off, one call), `load_summary` seeds without
  broadcasting, `reset()` emits `""`, a failed call emits `error` + `status_changed("error")`, and
  the `summary` field lands in `current.json` and survives in the archived session file. 30 checks.
- `_tmp_summary_app_check.py` — the app-side wiring in a real `MainWindow` (worker start stubbed):
  `{"type":"summarize"}` maps the transcript (non-empty lines, `(source, text, timestamp)`) plus the
  bullet list and speaker profile into the controller, an empty transcript sends the
  "Nothing to summarize yet" notice, `_on_summary_updated` broadcasts **and** persists, `_restore_session`
  seeds the tab, a `summary_save` edit persists and is echoed, and New Session clears + archives it.
  No server needed. 13 checks.
- `_tmp_summary_pane_check.py` — the pane really renders (needs a server: `PORT=8794 node server.js`):
  loads `/bullets`, clicks the Summary tab, asserts the `.summary-view` body + Summarize button +
  empty-state hint, that clicking sends `summarize`, that an incoming `summary` frame (pushed by a
  second WS client) renders as markdown with green h2 headings, and the edit flow — a **double-click**
  opens the `.summary-editor` textarea seeded with the preview, typing sends a debounced `summary_save`,
  and **Back** returns to preview showing the edit. 19 checks.

### Consulting tab (throwaway)
- `_tmp_consulting_check.py` — `ConsultingWorker` + `ConsultingController` with the AI client stubbed
  (no network): the brief prompt carries the transcript + speaker profile + Speaker context; the gaps
  prompt carries the **confirmed brief** when present and the profile + context when not; the roadmap
  prompt carries the reference + flagged gaps (lines truncated to `CONSULTING_MAX_LINE_CHARS`); each
  mode returns False and emits `no_input` on an empty transcript; a normal run emits
  `started` → `updated(mode, text)` → `complete` (reasoning off, one call); the busy guard rejects a
  second call without a notice; `load_state` seeds without broadcasting; `reset()` emits `""` for all
  three modes; a failed call emits `error` + `status_changed(mode, "error")`; and
  `brief`/`gaps`/`roadmap`/`brief_meta` land in `current.json` and survive archiving. 56 checks.
- `_tmp_consulting_app_check.py` — the app-side wiring in a real `MainWindow` (worker start stubbed):
  `draft_brief` maps the transcript (non-empty lines, `(source, text, timestamp)`) + speaker profile +
  mirrored context; `analyze_gaps` uses the confirmed brief as the reference and `""` when unconfirmed;
  `generate_roadmap` passes reference + gaps; an empty transcript sends a `no_input` notice per mode;
  `_on_consulting_updated` broadcasts **and** persists (and clears the brief's confirmation);
  `confirm_brief` sets `brief_meta.confirmed` + echoes it; `consulting_save` persists + echoes;
  `_restore_session` seeds the controller; New Session clears + archives. No server needed. 31 checks.
- `_tmp_consulting_pane_check.py` — the pane really renders (needs a server: `PORT=8795 node server.js`):
  loads `/bullets`, opens the Consulting tab, asserts the three sections + buttons, that the roadmap
  button starts **disabled** and enables once a confirmed `consulting` frame arrives, that clicking
  Draft brief / Analyze gaps sends the right messages, that incoming frames render as markdown with
  the Confirmed badges, that Confirm is locked while confirmed and sends `confirm_brief` after an edit,
  and the brief edit flow (double-click → type → debounced `consulting_save` → Back shows the edit).
  28 checks.

### Session objectives tab (throwaway)
- `_tmp_objective_check.py` — the offline gate: the pure helpers (`objective_key`, `align_locks`,
  `locked_index`, `resolve_active` precedence including "a lock beats the prediction", the
  `observe` hysteresis — one prediction does not commit, the second agreeing one does, a different
  index starts a new streak, returning to the active index or an out-of-range/`-1` prediction
  resets it, a lock pins immediately), the controller (list editing, `set_lock` by text/index,
  meta pruning and index shifting on removal, the cap, the debounce interval, **a manual
  `predict_now` that commits the first answer and reports `predicted` with a message**, the
  *automatic* path still needing two agreeing answers, the **seeded** window
  (`predict_now(lines=…)`) with its guards, the stale-window discard (automatic only), the busy
  guard's queued rerun, the JEV observation path, the history cap), the JEV plumbing
  (`current_objective` + the repurposed `objective_N` questions, the `objectives` /
  `active_objective` state fields) and the session round-trip (the fields survive `_normalize`, a
  short lock list is padded, a missing `objective_meta` degrades to `{}`, `new_session` clears and
  archives). No server needed. 97 checks.
- `_tmp_objective_app_check.py` — the app-side wiring in a real `MainWindow` (the prediction worker
  stubbed): `add_objective` broadcasts / persists / mirrors to the reply prompt (a duplicate is
  refused with a `no_input` notice), locking pins the focus in the frame + meta + history + prompt,
  `remove_objective` updates all three, `trigger_objective_prediction` reaches the tracker and
  **seeds it from the persisted transcript** (`_transcript_pairs()`), the mirrored
  objectives/locks/meta reach the **voice** worker and are kept out of the image path, a finalized
  speaker line fills the window and arms the debounce (a host line does neither), `session_state`
  carries the list/locks/history plus the derived `objective_active` and `objective_pending`, and
  restore / New Session / archive / the reply worker's JEV observation all behave. No server
  needed. 44 checks.
- `_tmp_objective_pane_check.py` — the pane really renders (needs a server: `PORT=8796 node
  server.js`): loads `/bullets`, opens the Objectives tab, asserts the add form + Predict now, that
  clicking sends `trigger_objective_prediction` and the submitted text sends `add_objective`, that an
  incoming `objectives` frame renders both items with the tracked one highlighted, the amber lock
  tint and the Locked badge, that a `pending` candidate shows the amber "Candidate" row + item tint,
  that an `objectives_history` frame appends to the timeline, that a padlock sends
  `set_objective_lock` and the × sends `remove_objective`, and that the console stays clean. It
  caught exactly the kind of bug `node --check` cannot: a conditional block in the middle of the
  render tree made Preact throw `insertBefore` and drop the timeline (the component now keeps every
  block in the DOM and hides the empty ones with an `empty` class). 24 checks.

### Microphone mute (throwaway)
- `_tmp_mute_check.py` — the soft-mute sender loop against a **fake `websockets` connection**
  (no real API): live chunks go as binary frames; while muted nothing binary is sent, the queue
  drains, and a `{"type": "keepalive"}` text frame arrives within the interval; unmuting resumes
  PCM; stopping still sends the end-of-stream frame. Also the controller contract
  (`set_mic_muted` reaches the live worker; a worker from `start_session` is muted before `.start()`)
  and the painted icon (live vs muted differ, muted has the red slash). 22 checks.
- `_tmp_mute_app_check.py` — the bar-side wiring: builds a real `MainWindow` and asserts the button
  is in the control row, starts unchecked, toggles the controller state + icon + tooltip + status
  label, and is absent from `ui_state.json`. 16 checks.

### Pane opacity (throwaway)
- `_tmp_pane_opacity_check.py` — whole-window pane opacity, app-side: builds a real
  `MainWindow` (no session), asserts `clamp_opacity` (0.1→0.3, 1.5→1.0, `"0.7"`→0.7,
  `None`→the 0.7 default, 0.55→0.55), that all four panes start at 70% (and, on macOS,
  that the native `NSWindow.alphaValue` really got it via `macos_window.get_opacity`), that
  a flag change + re-show keeps the opacity, the Tool ▾ "Pane Opacity" submenu (6 presets,
  70% checked) and the Settings slider (70, label `70%`), `_set_pane_opacity` driving every
  pane + both controls (0.5 / 0.73 / clamped 0.1), the slider applying live and persisting on
  `sliderReleased`, and `settings.pane_opacity` round-tripping into a fresh `MainWindow`.
  Qt quantizes `windowOpacity()` to 8 bits, so the comparisons use a 1/255 tolerance.
  No server needed. 40 checks.

### Long-run stress test (throwaway)
`_tmp_long_transcription_test.py` drives the real app with **real audio** through a
**local fake Soniox** server (no real API, AI forced off) to reproduce/measure long-run
behavior:
```bash
# 10 minutes, full app (webviews + Node server); speak into the mic for the run
venv/Scripts/python.exe _tmp_long_transcription_test.py --minutes 10
# Python+audio only (no browser panes / Node server)
venv/Scripts/python.exe _tmp_long_transcription_test.py --minutes 10 --mode pipeline
# flags: --mode full|pipeline, --host <devid>, --no-speaker, --port <n>
```
It redirects the session store to a temp dir, backs up `ui_state.json`, stubs the global
hotkeys, and prints a start/peak/end report; samples land in `logs/health.log`, a native
crash in `logs/faulthandler.log`, and the capture child's stderr in
`logs/audio-capture.log`.
**Verified 20-min run** (full mode, the crash scenario — same BT headset as Host mic
`--host 1` and Speaker loopback `--speaker-index 66`): completed cleanly. RSS flat
(523→685 warm-up then oscillated 613–685, slope ≈ **-1.2 MB/min**, no upward trend),
threads constant 15, webview heaps constant 9.5 MB, editor blocks capped at 500, **no
child restarts, no new `faulthandler.log` block, empty `audio-capture.log`/`crash.log`**,
146.3 MB PCM reached the fake Soniox (≈153.6 MB expected → both streams flowed the whole
run), clean shutdown with no orphaned capture children.

### Auto-reply (AI suggestion) regression tests (throwaway)
Two-tier suite for the auto-reply pipeline. The offline tier drives the real
`GeminiAutoReplyWorker.run()` with a stubbed `generate_stream` (no network) and
asserts the *contract of what we send*; the live tier runs the real provider and
asserts the reply text. Both draw on the same 16-case scenario table from the flow
review (sample conversation, question, answer→ack→question, filler, trailing host
turn, context states, endpoint debounce, history cap, trigger-drop, manual reply,
image reply, pinned role under JEV), split across the two tiers.
- `_tmp_auto_reply_prompt_check.py` — offline, deterministic, the merge gate.
  Scenarios 1, 2, 2b, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17. Hard `check()`
  assertions plus `witness()` observations of the known causes, plus section **[18]** (the session
  digest: flag off → prompt byte-identical, flag on → bullets/locked markers/KYC profile/confirmed
  brief/prior suggestions, every cap enforced, `_record_suggestion` on the answered turn without
  mutating the shared history objects, the voice-vs-image worker plumbing, and
  `MainWindow._rebuild_reply_digest` taking the *confirmed* brief only) and **[19]** (the
  `Objective focus:` block: absent with no objectives or no tracked focus, the tracked objective
  with its confidence/source, a lock beating the prediction and adding the serve-it line, the JEV
  `current_objective` question/state, the `objective_observed` emission, and the low-confidence /
  unknown-key / no-objectives guards). **121 checks, all 7
  witnesses ABSENT** (verified 2026-10-17, after F1/F2/F5/F6/F7 and the per-role style
  block landed): both grounding bullets (source-of-truth **and** first-sentence), the
  no-context anti-invention rule (which still never says "Host profile"), the per-role
  `Style:` block (`answer_first` honoured, an Interviewer omits the directive, two roles
  render different styles, a style-less role falls back to `DEFAULT_ROLE_STYLE`), F2
  answer-first via the role style, the schema-2 purpose store (a stale built-in copy can
  no longer shadow the seed, a synthesized role keeps its own tone, only non-built-in
  entries are written back), *all* leading host turns dropped, speaker-side
  fillers dropped, the question sent once, the filler filter (a filler makes **no** AI call,
  a run of acknowledgments counts as one, an explicit `allow_filler=True` request still
  answers, and "Right, but the brief still gets lost" is not mistaken for a filler), the
  queued rerun, and `maya.context.txt` aligned with the extracted profile. The recorded
  session's always-empty `suggestion` field is a documented data fact rather than a
  witness (no code change can flip it). `AUTO_REPLY_STRICT=1` turns every witness into a
  failure and **passes** — run that as the gate. No server needed.
- `_tmp_auto_reply_live_check.py` — opt-in, real model. Gated by
  `AUTO_REPLY_LIVE_TESTS=1`; exits 0 with a notice when the flag is unset or the
  provider cannot be built (missing key), so it is a no-op without credentials.
  Scenarios L1 (replay the recorded failing question), L2, L3 (grounding),
  L4 (role inversion), L5 (now asserts the filler **skip**, 1 ms, no model call),
  L7, L10 (Indonesian). Prints each reply and the latency, since the model output is
  non-deterministic. `AUTO_REPLY_STRICT` has no effect here; `AUTO_REPLY_LIVE_REPEAT=N`
  repeats the L1 headline replay N times.
  **Verified 2026-10-17** (deepseek-v4.1-flash via OpenRouter, reasoning ON): **15/15
  checks pass, all 5 witnesses ABSENT**; L1-L4 now lead with the product in the first
  sentence. Earlier baseline (2026-10-16, 2 full runs + an ON/OFF A/B): 14/14 and the
  reported symptom **did not reproduce** — L1 was grounded in **8/8** samples, and the
  24-turn history the worker sends contains **zero** product terms, so
  "brief"/"capture"/"helpy" can only come from the attached Host profile. Reasoning ON vs
  OFF both scored 3/3 grounded; the only measured effect of reasoning was latency
  (~5.8 s avg ON vs ~1.8 s OFF, with a 13–26 s tail), which weakens F4. Known harness
  limitation: the L7 invented-product detector is under-sensitive (it missed "upload your
  data … ranked results", "a live dashboard" and "30-second call … two-week cycles" by
  hand), and it can also false-positive on a process metaphor ("Helpy's consulting
  pipeline") — see the report's caveats.
- `_tmp_auto_reply_record.py` — re-records Bagian A: it pairs each stored answer in
  `sessions/current.json` with the same trigger the report uses, rebuilds the history the
  reply saw, and re-runs the REAL worker on it through today's prompt, writing a **new**
  session-shaped file (`reports/auto-reply-replay-session.json`). `sessions/current.json` is
  never modified. A trigger the current pipeline intentionally skips (F6 filler) spends no
  call and writes no entry, so the replay can hold fewer results than the source; the skipped
  triggers are listed in the file's `replay` block. Point the report at it:
  `tools/auto_reply_report.py --recorded-only --session reports/auto-reply-replay-session.json`.
  Verified 2026-10-17: same 7 triggers → 4×`OK` + 1×`CATATAN` and 2 skips, vs 4
  `PERLU DIPERHATIKAN` + 3 `CATATAN` in the original record.
- `tools/auto_reply_report.py` — the **evidence report** (Markdown + JSON sidecar under
  `reports/`): per case what was asked, what the AI answered, and a deterministic verdict
  (`OK` / `CATATAN` = low-severity notes only / `PERLU DIPERHATIKAN`) with the reason and the
  ranked cause it belongs to. Bagian A replays the 7 recorded answers from
  `sessions/current.json`, pairing each with its trigger utterance (the merged run of
  fragments since the previous result, which is what exposes the filler triggers); Bagian B
  runs the live scenarios under the same `AUTO_REPLY_LIVE_TESTS=1` gate; Bagian C aggregates;
  `--session PATH` scores a different record (default `sessions/current.json`; the replayed one
  comes from `_tmp_auto_reply_record.py`) and the header prints the file it actually read;
  the appendix reports the prompt contract (both grounding bullets, the no-context anti-invention
  rule, the per-role `Style:` block, the answer-first directive, leading-turn,
  duplicate-question) so a symptom can be tied to its structural cause — plus a
  `stale_builtin_copy` warning when `purposes.json` still holds a stale built-in copy
  (`runtime_purpose()` mirrors the schema-2 load, so the contract now reflects the app).
  Its `invented` detector no longer flags ambiguous words (`api`, `crm`, `platform`,
  `pipeline`) in a sentence that names a real product, and now catches capability claims
  (`it syncs`, `automatically`, `you get a … report`, `weekly report`, `free trial`).
  This is an evidence tool, not a gate — it always exits 0.
```bash
venv/bin/python _tmp_auto_reply_prompt_check.py
AUTO_REPLY_STRICT=1 venv/bin/python _tmp_auto_reply_prompt_check.py
AUTO_REPLY_LIVE_TESTS=1 venv/bin/python _tmp_auto_reply_live_check.py
venv/bin/python tools/auto_reply_report.py                              # Bagian A saja (gratis)
AUTO_REPLY_LIVE_TESTS=1 venv/bin/python tools/auto_reply_report.py      # + Bagian B (memanggil model)
venv/bin/python _tmp_auto_reply_record.py                               # re-record Bagian A (memanggil model)
```
Evidence for the reported symptom lives in `sessions/current.json` (`gemini_results`:
7 suggestions on 2026-10-16, the last — the answer to "How do we stop that from
happening?" — gave generic design advice instead of naming the product mechanism), and in
the report's Bagian A, which scores those same 7 answers deterministically (A1 flagged
`role_inversion` + `ungrounded`, A5/A6 flagged `filler_trigger`, A7 `grounding_late`).
