# Plan 2.3 — "I am:" role selector, speaker context, and language rule

Status: proposed (not implemented)
Area: `src/ui_components/settings_view.py`, `src/ui.py`,
`src/gemini_worker.py`, `src/config.py`, `context_speaker.txt` (optional)

## 1. "I am:" control (Settings, under Purpose)

In `SettingsViewWidget._init_ui` (`settings_view.py:74-86`), add a row directly
below the Purpose combo:

```
I am:  [ Smart (auto) ▾ ]
```

- `self.host_role_combo = QComboBox()`; populated by
  `populate_host_roles(purpose)`.
- Options: first item `("Smart (auto)", "smart")`, then one entry per role in
  the selected purpose (`label`, `key`).
- If the purpose has a single role, the combo shows only `Smart (auto)` and is
  disabled (nothing to choose).
- Getters: `get_host_role_combo()`.

`MainWindow._on_purpose_changed` (`ui.py:1071`) already runs on Purpose change:
extend it to call `self._refresh_host_roles(purpose_key)`, which repopulates the
combo and restores the remembered role (or `smart`).

## 2. Persistence — `ui_state.json` settings

- Add `settings.host_role_by_purpose: {purpose_key: role_key}`.
- `_save_state` writes it; `_apply_settings_state` restores it.
- Validation: if the stored role is not in the current purpose's `roles`, fall
  back to `"smart"`.
- The combo's `currentIndexChanged` connects to a handler that updates the
  controller (`translation_controller.set_host_role`) and calls `_save_state`.

## 3. Worker resolution — `src/gemini_worker.py`

`GeminiAutoReplyWorker` gains a `host_role` argument. Replace the persona
resolution at `gemini_worker.py:198-201`:

```python
purpose = self._purpose_store.get(self._purpose)
roles = purpose_roles(purpose)                 # back-compat helper
role_key = self._host_role
if role_key == "smart":
    role_key = self._smart_role or purpose.get("default_role")
role = roles.get(role_key) or next(iter(roles.values()))
persona, objective = role["persona"], role["objective"]
counterpart = role.get("counterpart")
```

Prompt additions (inside the f-string at `:222-239`):
- `- You are acting as: {role['label']}.`
- `- The Speaker is acting as: {counterpart}.` (only when present)
- Speech act line when JEV chose one:
  `- Perform this speech act in your reply: {act_label}.`

## 4. Speaker context — default empty

- New `_load_speaker_context()` next to `_load_self_context()` (`:119`):
  returns the file contents when `SPEAKER_CONTEXT_FILE` is set, exists, and is
  non-empty; otherwise returns `""`.
- In the prompt, include `- Speaker profile: {speaker_context}` **only** when
  non-empty; otherwise include
  `- The Speaker profile is unknown; infer their role from the conversation.`
- Create `context_speaker.txt` as an optional (empty) placeholder, or simply do
  not create it — both must be safe. Document in `.env.example`.

Note: `context_sample.txt` (the Host profile) is only loaded when
`SELF_CONTEXT_FILE` is set in `.env`; otherwise `_load_self_context()` falls back
to `DEFAULT_SELF_CONTEXT` (`gemini_worker.py:16,119-124`). Plan to point
`SELF_CONTEXT_FILE=context_sample.txt` in `.env.example` for parity.

## 5. Language rule — Speaker first

Rewrite the `Language:` block at `gemini_worker.py:231-236`:

- Determine the reply language from the **latest `speaker` turn** (the language
  currently being spoken), not from previous `assistant` turns.
- Priority: JEV `reply_language` answer (when available) → detected Speaker
  language → `self._target_language`.
- Keep the rule that the first line is labelled with the actual language name
  (e.g. `Indonesian Text:` instead of `{target_language} Text:`), and adapt the
  pronunciation/sample text to that language.
- When the Speaker mixes languages, mirror the dominant one (or the JEV choice).

Because Soniox returns single finalized strings, detection is a lightweight
heuristic (script ranges / stopword hints) or delegated to JEV's
`reply_language` choice; no new dependency required.

## 6. UI polish

- Tooltip on `I am:`: "Who you (the Host) are in this conversation. Smart lets
  the AI decide."
- When the worker resolves a role/act in Smart mode, surface it in the status
  text (e.g. "Replying as Interviewer · Directive"), reusing
  `_send_gemini_status` (`ui.py:893`).

## Verification

- Switch Purpose → `I am:` repopulates with that purpose's roles.
- Pick `Interviewer` in Coding Interview → built `system_instruction` says the
  Host is the Interviewer and the Speaker is the Candidate.
- Remove `context_speaker.txt` → prompt omits the Speaker profile line.
- Speaker speaks Indonesian while target is English → host reply is Indonesian.
