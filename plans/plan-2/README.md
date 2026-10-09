# Plan 2 — JEV Smart Reply, PurposeStore, and Role Selector

Status: proposed (not implemented)
Area: `src/purposes.py`, `src/purpose_store.py` (new), `src/speech_acts.py` (new),
`src/decision_client.py` (new), `src/gemini_worker.py`, `src/config.py`,
`src/controllers/translation_controller.py`, `src/ui.py`,
`src/ui_components/settings_view.py`, `.env.example`, `.gitignore`

## Goal

Make the auto-reply **situation-aware** instead of always answering the same
way. Before the model writes text, a fast "System One" decision layer (JEV)
decides *whether* to reply, *as whom* (Host role), *which speech act* to
perform, and *in what language*. When the situation fits no known category
("Other"), the AI synthesizes a new persona, registers it in memory first and
persists it to JSON asynchronously, then answers using it.

The user also wants to be able to **pin their own role** ("I am: …") — e.g. in a
coding interview, Host = Interviewer *or* Candidate — with a **Smart (auto)**
default where JEV picks the role.

## Key concepts

- **System One (JEV)** = `typesafe/jev-1.13`, a decision model returning typed,
  probabilistic answers (`noul` / `choice` / `score`). No generated text.
  Called via `POST {JEV_BASE_URL}/alpha/decisions`. Two orders of magnitude
  faster than an LLM; output tokens are free.
- **System Two (LLM)** = the existing chat model (`AI_PROVIDER` /
  `AI_BASE_URL`). It still writes the actual reply.
- **Purpose** = persona + objective + role set (Host "am I").
- **Speech acts (Searle)** = Assertive, Directive, Commissive, Expressive,
  Declarative, plus **Other**.
- **PurposeStore** = in-memory source of truth for purposes, persisted to
  `purposes.json` by a background thread (mirrors `SessionStore`).

## Architecture

```
State (Host profile + Speaker profile + purpose + role + recent turns + latest utterance)
        │
        ▼
[TAHAP 1] JEV decision call (System One, parallel questions)
   ├─ should_reply      (noul)    → reply / stay silent
   ├─ host_role         (choice)  → only in Smart mode
   ├─ speech_act        (choice)  → 5 Searle acts + OTHER
   ├─ reply_language    (choice)  → Speaker language vs Host language
   └─ objective_checklist (noul ×N) → purpose-specific checklist
        │
        ├─ high confidence & act ≠ OTHER
        │      → [TAHAP 2] LLM writes only that act, with resolved role persona
        │
        └─ act = OTHER / low confidence
               → [TAHAP 2b] LLM "Persona Synthesis" returns JSON
                    { new_category, reply }
               → dedup pre-check (JEV/LLM)
               → purpose_store.register(new_category)   # memory FIRST
               → stream `reply`
               → daemon thread flushes purposes.json     # async
               → purposes_changed → Settings combo adds "(auto)"
```

## Confirmed decisions

| Topic | Decision |
| --- | --- |
| Purpose config | Built-ins stay in `purposes.py` as immutable seed; `purposes.json` is gitignored and holds user edits + AI-added entries |
| Auto purposes in UI | Shown in the Purpose dropdown, marked `(auto)` |
| Dedup | Pre-check via JEV/LLM before registering |
| "I am:" control | In Settings, directly under Purpose |
| Default "I am:" | `Smart (auto)` |
| `context_speaker.txt` | Optional; default empty/none, fill only when available |
| `should_reply` | May suppress a reply; gated by a Settings toggle "Smart Decision (JEV)", default on |
| Reply language | Priority: Speaker language > Host/target language |
| "Other" escalation | One synthesis call produces both the new category and the reply |

## File map / execution order

1. `plans/plan-2/01-purpose-store.md` — `speech_acts.py`, `purposes.py` schema,
   `purpose_store.py`, `config.py`.
2. `plans/plan-2/02-jev-decision-layer.md` — `decision_client.py`, pipeline,
   `should_reply` gate, controller wiring.
3. `plans/plan-2/03-role-selector-and-language.md` — `I am:` dropdown, roles,
   speaker context, language rule, persistence.
4. `plans/plan-2/04-other-flow.md` — Other escalation + async register.

Implement in the order above: data → decision layer → worker/UI → escalation.

## Verification

```bash
venv/Scripts/python.exe -m py_compile src/*.py src/controllers/*.py src/ui_components/*.py
```

Smoke checks:

- `PurposeStore.register()` → new purpose visible in memory immediately; JSON
  file written after the debounce.
- Changing `I am:` changes the persona in the built `system_instruction`.
- With `JEV_ENABLED=false` / no key, the pipeline degrades to today's behavior
  (plain auto-reply) without errors.
- `context_speaker.txt` absent → prompt omits the Speaker profile line.
