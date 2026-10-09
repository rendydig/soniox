# Plan 2.4 — "Other": persona synthesis and asynchronous purpose learning

Status: proposed (not implemented)
Area: `src/gemini_worker.py`, `src/purpose_store.py`,
`src/controllers/translation_controller.py`, `src/ui.py`

## Trigger

The Other flow runs when either:
- JEV `speech_act` = `other`, or
- JEV `speech_act` confidence `< JEV_MIN_CONFIDENCE`.

In Smart role mode, a low-confidence `host_role` also escalates.

## Step 1 — Persona Synthesis (LLM, structured JSON)

A dedicated LLM call (non-streaming, reasoning disabled) with a meta-prompt
that returns JSON only:

```json
{
  "new_category": {
    "key": "crisis_mediation",
    "label": "Crisis Mediation",
    "persona": "You are a calm facilitator helping the Host defuse a conflict...",
    "objective": ["Acknowledge both sides", "Propose a concrete next step"],
    "speech_act": "directive",
    "criteria": "Two parties in conflict; Host must de-escalate.",
    "counterpart": "Disputing party",
    "confidence": 0.62
  },
  "reply": "<the exact words the Host should say, in the resolved language>"
}
```

Contract:
- Output **only** the JSON object (tolerate code fences; keep the previous/fall
  back to a plain reply on malformed output).
- `reply` is streamed as the answer; `new_category` is the learning payload.
- If the model decides the existing acts *do* cover it, it may return
  `"new_category": null` and just provide `reply`.

## Step 2 — Dedup pre-check (JEV/LLM)

Before registering:
- Ask JEV `noul`: "Does the existing category set already cover this situation?"
  with the candidate `criteria` and the current purpose labels as `state`.
- If yes (or the slug already exists), skip registration and just use `reply`
  (optionally set the matched purpose as a one-shot override).
- If no, proceed.

## Step 3 — Register in memory first

```python
key = purpose_store.register(new_category)   # memory updated immediately
```

- `register()` adds metadata (`dynamic, created_at, source="ai",
  confidence_at_creation, schema_version`), emits `purposes_changed`, and marks
  dirty.
- The very next JEV call (next turn) includes the new category in the
  `speech_act`/role `criteria`, so the system no longer escalates for the same
  situation — this is the learning loop.
- Enforce `MAX_DYNAMIC_PURPOSES` (prune oldest dynamic entries).

## Step 4 — Persist asynchronously

- The `PurposeStore` daemon writer flushes `purposes.json` after
  `SESSION_WRITE_DEBOUNCE_MS` (reuse the constant or add
  `PURPOSES_WRITE_DEBOUNCE_MS`).
- The UI never waits on the write; reads always come from memory.

## Step 5 — UI reflection

- `PurposeStore.purposes_changed` is connected in `MainWindow` to
  `_on_purpose_added(key)`, which inserts a new item into `purpose_combo`
  labelled `"{label} (auto)"` (data = key), without disturbing the current
  selection.
- The Settings `I am:` combo updates when that auto purpose is later selected
  (its `roles` come from `new_category` → single role).
- Status text briefly notes: "Learned new persona: Crisis Mediation".

## Data shape: dynamic purpose

```json
{
  "crisis_mediation": {
    "label": "Crisis Mediation (auto)",
    "dynamic": true,
    "source": "ai",
    "created_at": "2026-10-09T10:00:00+00:00",
    "confidence_at_creation": 0.62,
    "schema_version": 1,
    "default_role": "mediator",
    "roles": {
      "mediator": {
        "label": "Mediator",
        "persona": "...",
        "objective": ["..."],
        "counterpart": "Disputing party"
      }
    },
    "speech_act_policy": ["directive", "expressive"],
    "objective_checklist": ["Has the conflict been de-escalated?"],
    "extra_format": []
  }
}
```

## Edge cases

- **Malformed JSON** → keep previous purposes, reply with the raw text (or
  re-ask once), log a warning.
- **Duplicate slug** → suffix `-2`; but the dedup pre-check should usually
  prevent reaching this.
- **Empty `reply`** → fall back to a generic Host line, still register the
  category if it passed dedup.
- **Threading** → `register()` is called from `GeminiAutoReplyWorker`
  (QThread); the store's lock guards memory, `purposes_changed` is queued to the
  Qt main thread, and the file write happens on the store's own daemon thread.
- **Session vs global** → dynamic purposes are **global** (persist across
  sessions), unlike session state. `New Session` does not clear them.

## Verification

- Force `speech_act=other` (temporary threshold or a contrived utterance) →
  confirm: new entry appears in the Purpose combo marked `(auto)`, `purposes.json`
  gains the entry after the debounce, and the next turn no longer escalates.
- Kill the app during the debounce → entry is still in memory for the running
  turn; on restart it is absent only if the write never completed (acceptable;
  memory-first means the current session never lost it).
