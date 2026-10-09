# Plan 2.1 — PurposeStore, speech acts, and purpose schema

Status: proposed (not implemented)
Area: `src/speech_acts.py` (new), `src/purposes.py`, `src/purpose_store.py`
(new), `src/config.py`, `.gitignore`

## 1. `src/speech_acts.py` (new)

Searle's five speech acts + an `other` catch-all, each with a `criteria`
string ready to drop into a JEV `choice` question.

```python
SPEECH_ACTS = {
    "assertive":   {"label": "Assertive",
                    "criteria": "States a fact, report, confirmation, or belief the Speaker can verify."},
    "directive":   {"label": "Directive",
                    "criteria": "Asks a question, requests, commands, or suggests an action."},
    "commissive":  {"label": "Commissive",
                    "criteria": "Commits the Host to a future action — promises, offers, threatens."},
    "expressive":  {"label": "Expressive",
                    "criteria": "Expresses feelings or attitude — thanks, apology, congratulations, complaints."},
    "declarative": {"label": "Declarative",
                    "criteria": "Changes reality by its utterance — decisions, appointments, dismissals (needs authority)."},
    "other":       {"label": "Other",
                    "criteria": "The situation does not fit any of the standard acts above."},
}
OTHER_ACT = "other"
```

Helper `act_criteria()` returns the `{key: criteria}` dict for the JEV call.

## 2. `src/purposes.py` — schema change

- Rename `PURPOSES` → `BUILTIN_PURPOSES` (immutable seed). Keep
  `DEFAULT_PURPOSE = "language_learning"`.
- Each purpose gains:

```python
{
  "label": "Coding Interview",
  "default_role": "candidate",
  "roles": {
    "candidate":   {"label": "Candidate",   "persona": "...", "objective": [...], "counterpart": "Interviewer"},
    "interviewer": {"label": "Interviewer", "persona": "...", "objective": [...], "counterpart": "Candidate"},
  },
  "speech_act_policy": ["assertive", "directive"],   # preferred acts (JEV hint)
  "objective_checklist": [                            # JEV noul questions
    "Has the Host answered the question the Speaker just asked?",
    "Did the Host give a concrete, correct answer (not a deflection)?",
  ],
  "extra_format": [...],
  "include_pronunciation_default": False,
}
```

- **Back-compat shim**: `purpose_roles(purpose)` returns `purpose.get("roles")`
  or an implicit single role built from top-level `persona`/`objective`, so a
  purpose without `roles` still works.
- Role split to author:
  - `coding_interview` → candidate / interviewer
  - `general_interview` → candidate / interviewer
  - `consultation` → consultant / client
  - `language_learning` → learner (single)
  - `casual_networking` → participant (single)

## 3. `src/purpose_store.py` (new)

A `QObject` mirroring `SessionStore`'s pattern (`src/session_store.py:58`): the
in-memory dict is the single source of truth; a daemon thread JSON-dumps a
snapshot on a debounce via a temp file + `os.replace`.

```python
class PurposeStore(QObject):
    purposes_changed = Signal(str)   # emits the new/changed purpose key

    def __init__(self, path=None): ...
    # --- read (always memory) ---
    def get(self, key) -> dict
    def all(self) -> dict[str, dict]
    def keys(self) -> list[str]
    def labels(self) -> list[tuple[key, label]]
    def roles(self, key) -> dict[str, dict]     # via purpose_roles()
    # --- write ---
    def register(self, purpose: dict) -> str    # returns assigned key
    def flush(self)
    def close(self)
```

Load order:
1. seed `BUILTIN_PURPOSES`;
2. overlay `PURPOSES_PATH` (`purposes.json`): same-key entries **merge**, new
   entries are added. Built-in keys are never removed by the file.

`register(purpose)`:
- assign `key` = slug of `label` (dedupe with `-2`, `-3` if needed);
- add metadata: `dynamic: true`, `created_at` (UTC ISO), `source: "ai"`,
  `confidence_at_creation`, `schema_version`;
- update `_purposes` **immediately** (lock), set `_dirty`;
- `purposes_changed.emit(key)` (queued to the Qt main thread since `register`
  runs inside `GeminiAutoReplyWorker`);
- enforce `MAX_DYNAMIC_PURPOSES` (prune oldest dynamic entries on overflow).

Thread-safety: `threading.Lock` around the dict (calls originate from a QThread);
a separate `_write_lock` for file I/O, exactly like `SessionStore`.

## 4. `src/config.py` additions

```python
PURPOSES_PATH = os.path.join(  # repo root purposes.json (gitignored)
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "purposes.json")
SPEAKER_CONTEXT_FILE = os.environ.get("SPEAKER_CONTEXT_FILE")   # optional, default None

JEV_ENABLED     = _env_bool("JEV_ENABLED", False)   # opt-in
JEV_MODEL       = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
JEV_BASE_URL    = os.environ.get("JEV_BASE_URL", "https://openrouter.ai/api")
JEV_MIN_CONFIDENCE   = float(os.environ.get("JEV_MIN_CONFIDENCE", "0.55"))
JEV_SHOULD_REPLY_MIN = float(os.environ.get("JEV_SHOULD_REPLY_MIN", "0.5"))

MAX_DYNAMIC_PURPOSES = 30
```

`JEV_BASE_URL` intentionally differs from `AI_BASE_URL` (`/api/v1`): JEV lives
at `/api/alpha/decisions`.

## 5. `.gitignore` / `.env.example`

- `.gitignore`: add `purposes.json`.
- `.env.example`: document `JEV_ENABLED`, `JEV_MODEL`, `SPEAKER_CONTEXT_FILE`,
  and that `purposes.json` is generated/merged locally.

## Verification

- Unit-style smoke: construct `PurposeStore`, call `register()` with a fake
  category, assert `get(key)` returns it before any file write; wait > debounce
  and assert `purposes.json` contains it.
- `purpose_roles()` returns the implicit role for old-shaped purposes.
