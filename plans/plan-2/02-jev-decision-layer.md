# Plan 2.2 — JEV decision layer and reply pipeline

Status: proposed (not implemented)
Area: `src/decision_client.py` (new), `src/gemini_worker.py`,
`src/controllers/translation_controller.py`

## 1. `src/decision_client.py` (new)

Thin client for the TypeSafe JEV Decisions API on OpenRouter. It is **not** an
OpenAI-compatible chat call — it hits a different path:

```
POST {JEV_BASE_URL}/alpha/decisions
Authorization: Bearer {JEV_API_KEY or AI_API_KEY}
Content-Type: application/json

{ "model": "typesafe/jev-1.13",
  "state": { ...unstructured state... },
  "questions": {
    "should_reply": { "type": "noul",   "instructions": "...", "criteria": {"true": "...", "false": "..."} },
    "host_role":    { "type": "choice", "instructions": "...", "criteria": {"candidate": "...", "interviewer": "..."} },
    "speech_act":   { "type": "choice", "instructions": "...", "criteria": { ...SPEECH_ACTS criteria... } },
    "reply_language": { "type": "choice", "instructions": "...", "criteria": {"English": "...", "Indonesian": "..."} },
    "objective_0":  { "type": "noul",   "instructions": "<checklist item>", "criteria": {...} }
  } }
```

Response `answers`:
- `noul` → `{"type": "noul", "noul": 0.96}` (probability of yes);
- `choice` → `{"type": "choice", "choice": "payments", "confidence": 0.67, "probabilities": {...}}`;
- `score` → `{"type": "score", "score": 1.99, "confidence": 0.99, "probabilities": {...}, "legend": {...}}`.

```python
class DecisionClient:
    def __init__(self): ...            # raises/no-ops if not configured
    @property
    def available(self) -> bool
    def decide(self, state: dict, questions: dict, timeout: float = 4.0) -> dict | None
```

Behavior:
- Use the standard library (`urllib.request`) to avoid adding a dependency, or
  reuse the already-installed `openai` package's HTTP layer if preferred.
  Prefer `urllib.request` (no new dep).
- Parse `data["answers"]`.
- On any failure (disabled, no key, timeout, HTTP error, malformed JSON) log a
  warning and return `None`. The caller then skips the gate entirely.

## 2. Question builder (pure functions, testable)

`build_questions(purpose, roles, speech_acts, checklist, smart_role: bool, languages: list)`
returns the `questions` dict:

- `should_reply` (noul): "Should the Host respond to the Speaker's latest
  utterance now, rather than stay silent (the Speaker may be thinking aloud or
  unfinished)?"
- `host_role` (choice): only included when `smart_role` is True; criteria from
  the selected purpose's `roles`.
- `speech_act` (choice): criteria from `SPEECH_ACTS` (includes `other`), with
  the purpose's `speech_act_policy` mentioned in `instructions`.
- `reply_language` (choice): the Speaker's detected language + the configured
  target language + a small allow-list.
- `objective_N` (noul): one per `objective_checklist` item (only for the active
  purpose).

`state` carries: `host_profile` (self context), `speaker_profile`
(may be empty), `purpose`, `host_role` (if manual), and the last few combined
turns plus the latest utterance.

## 3. Pipeline integration — `src/gemini_worker.py`

`GeminiAutoReplyWorker.__init__` gains: `purpose_store`, `host_role` ("smart" or
a role key), `jev_enabled: bool`.

`run()` order:
1. Resolve `purpose` and `role` (see plan 2.3).
2. If `self._jev_enabled` and the client is available: call `decide()`.
   - If `should_reply.noul < JEV_SHOULD_REPLY_MIN` → emit a short status and
     return without generating (no reply). *Only* when the "Smart Decision
     (JEV)" toggle is on.
   - If `host_role` mode is smart → set the role from the `host_role` answer
     (fall back to `default_role` when confidence < `JEV_MIN_CONFIDENCE`).
   - Record `speech_act` (and confidence). If `other` or confidence low → go to
     the Other flow (plan 2.4).
   - Record `reply_language`.
3. Build `system_instruction` with the resolved persona/objective, the chosen
   speech act (as a "Perform this act" line), and the language block.
4. Stream via `client.generate_stream(...)` as today (`gemini_worker.py:254-268`).

Degradation: if JEV is off/unavailable, step 2 is skipped and behavior equals
today's auto-reply.

## 4. Controller wiring — `src/controllers/translation_controller.py`

- Hold a `purpose_store` reference and `_host_role`, `_jev_enabled` state with
  setters (`set_host_role`, `set_jev_enabled`).
- `_trigger_auto_reply` (`:176`) → before starting the worker, if
  `_jev_enabled`, the JEV gate runs inside the worker (kept off the UI thread).
  The worker emits either a reply or a "no reply" status; the controller already
  handles `result`/`error`/`chunk`.
- Add a new signal `reply_skipped = Signal(str)` (reason) so the pane can show
  "No reply needed" without persisting a result.

## 5. Latency / cost

- JEV adds ~70–500 ms before generation. Acceptable; can later be parallelized
  with context assembly.
- Input-only billing (~$42 / billion tokens); output free. Conversation state
  is small.

## Verification

- With `JEV_ENABLED=true` + an OpenRouter key: force `speech_act` questions and
  assert the chosen act appears in the built prompt.
- With `JEV_ENABLED=false`: pipeline output is byte-identical in shape to the
  current behavior.
- `decide()` returns `None` on a simulated 500/timeout and the reply still
  happens.
