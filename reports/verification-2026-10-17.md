# Verification report — session digest + session objectives

Run: 2026-10-17 · repo `Soniox-project` · macOS · `venv/bin/python`
Provider: `AI_PROVIDER=openai`, `AI_MODEL=deepseek/deepseek-v4.1-flash` (reasoning off)
`JEV_ENABLED`: **unset → false** (so the objective tracker ran its **LLM fallback** path, i.e. the default-user path)

## Verdict

**All four gates pass — 265 checks, 0 failures.** The A/B on the digest is **directional, not a proven win** (one case up, one case down, net `OK` 4 → 5 of 14). Two findings worth acting on, neither a blocker: an uncapped locked-bullet list, and a flaky teardown segfault in the app-check harness that predates this change.

| Gate | Result |
| --- | --- |
| `_tmp_auto_reply_prompt_check.py` (offline, deterministic) | **121 / 121**, 7 witnesses **ABSENT** |
| `_tmp_objective_check.py` (offline, pure + controller + session) | **79 / 79** |
| `_tmp_objective_app_check.py` (real `MainWindow`, worker stubbed) | **44 / 44** — plus a flaky teardown segfault (see F2) |
| `_tmp_objective_pane_check.py` (real QWebEngine, server on 8796) | **21 / 21** |

Reproduce:

```bash
venv/bin/python _tmp_auto_reply_prompt_check.py
venv/bin/python _tmp_objective_check.py
venv/bin/python _tmp_objective_app_check.py
# pane check needs its own server:
cd websocket-server && PORT=8796 node server.js &
OBJECTIVE_PANE_PORT=8796 venv/bin/python _tmp_objective_pane_check.py
```

## A/B — digest off vs on (live, `--repeat 3`)

```bash
AUTO_REPLY_LIVE_TESTS=1 venv/bin/python tools/auto_reply_report.py --repeat 3 \
  --out reports/auto-reply-baseline.md --json reports/auto-reply-baseline.json
AUTO_REPLY_CONTEXT_DIGEST=1 AUTO_REPLY_LIVE_TESTS=1 venv/bin/python tools/auto_reply_report.py --repeat 3 \
  --out reports/auto-reply-digest.md --json reports/auto-reply-digest.json
```

Aggregate: baseline `OK=4 · CATATAN=5 · PERLU DIPERHATIKAN=4` (of 14) → digest `OK=5 · CATATAN=5 · PERLU DIPERHATIKAN=4`.

### Bagian B — per scenario

| Case | Baseline | Digest | Movement |
| --- | --- | --- | --- |
| L1 | OK | OK | — |
| L2 | OK | **CATATAN** (`grounding_late`) | **regressed** |
| L3 | **PERLU DIPERHATIKAN** (`invented; grounding_late`) | **OK** | **improved** |
| L4 | **CATATAN** (`grounding_late`) | **OK** | **improved** |
| L5 | CATATAN (`skipped`) | CATATAN (`skipped`) | — (filler filter, digest-independent) |
| L7 | OK | OK | — |
| L10 | OK | OK | — |

### Bagian A — replay of the recorded session

**Byte-identical between the two runs** (`diff` clean), as expected: replay re-scores recorded answers and never calls the model. So the entire delta above comes from Bagian B.

### Reading

- The digest fixed the **only `PERLU DIPERHATIKAN`** case (L3, the invented-feature flag) and one `grounding_late` case (L4).
- It **regressed L2** to `grounding_late` (still names the product, just not in the first recommendation — the detector's own low-severity class).
- With one case up and one down on a `--repeat 3` sample, this is **directional evidence**. Keeping `AUTO_REPLY_CONTEXT_DIGEST=false` by default is the right call until a larger sample says otherwise.
- The appendix confirms the gating worked: `digest_enabled` = ✅ for the digest run and ❌ for baseline, and `Objective focus:` is **absent in both** — i.e. with no objectives tracked the prompt is unchanged, so the objective feature costs nothing when unused.

## Findings

### F1 — Locked bullets are not capped (prompt-budget hole) — Medium

`src/reply_context.py::_split_bullets` caps only the rolling list:

```python
(locked if flag else rolling).append(text)
return locked, rolling[-AUTO_REPLY_MAX_BULLETS:]   # <-- `locked` unbounded
```

`bullets` / `bullet_locks` are deliberately **uncapped** in the session store (AGENTS.md), so a long session with many locks grows the prompt without bound. Measured:

```
40 bullets, all locked  -> MAX_BULLETS=20, locked rendered = 40
30 locked + 30 rolling  -> locked=30, rolling=20
```

Suggested fix: `return locked[-AUTO_REPLY_MAX_BULLETS:], rolling[-AUTO_REPLY_MAX_BULLETS:]`, and add a check in section `[18]`. Small and self-contained.

### F2 — Flaky teardown segfault in the app-check harness — Low (pre-existing)

`_tmp_objective_app_check.py` exits `139` (SIGSEGV) on some runs **after printing `ALL PASS`**.

- Frequency: **1/3** on the first batch, **0/6** on the repeat batch → ~1/9 overall.
- **Not introduced here:** the pre-existing tracked `_tmp_consulting_app_check.py` segfaults the same way, also after `ALL PASS`. `_tmp_summary_app_check.py`, `_tmp_context_app_check.py`, `_tmp_bullet_pane_check.py` all exited `0`.
- Because it happens at interpreter shutdown *after* every assertion, it does not invalidate the results — but it can mask a real crash and it makes the harness unreliable for CI. Worth a follow-up (likely a `QThread`/`QWebEngine` teardown race: an object destroyed after the `QApplication` is gone).

### F3 — Unlocking leaves `meta["source"] == "lock"` — Low, cosmetic

`ObjectiveController.set_lock(..., locked=False)` runs `_apply(None, 0.0, "lock")`. With no lock present, `observe` treats `index=None` as out-of-range and returns without touching `source`, so `meta["source"]` stays `"lock"` while `resolve_active` reports `locked: False`. The focus correctly stays where it was (documented behaviour), but `gemini_worker._objective_block` suppresses the confidence line whenever `source == "lock"`, so a previously-locked objective renders with **no** confidence/source in the prompt. Harmless today; a one-line reset (`meta["source"] = ""`) would tidy it.

## Process note — I overwrote `reports/auto-reply-report.json`

`tools/auto_reply_report.py` defaults its JSON sidecar to `reports/auto-reply-report.json`, and my first offline validation run wrote there before I noticed the `--json` flag. The previous file (34,720 B, 06:54) became 22,239 B. **`reports/` is untracked, so it is not recoverable from git.**

Intact and now backed up to `reports/_backup-20261017-1217/`: `auto-reply-report-before.json`, `auto-reply-report-after.json`, `auto-reply-replay.json`, `auto-reply-digest.json`, `auto-reply-replay-session.json`. All later runs in this report pass `--json` explicitly. The baseline numbers this report compares against are re-measured fresh (`auto-reply-baseline.json`), so the comparison does not depend on the lost file.

## Confirmed working

- **Byte-identical gating**: digest off (or empty) → prompt unchanged; no objectives → no `Objective focus:` block. Asserted in `[18]`/`[19]` and confirmed in the report appendix.
- **Caps enforced**: bullets 20 (newest kept), 160 chars/bullet, 5/profile field, 1200/brief, 3 prior suggestions — all asserted on the pure builder.
- **Suggestion recording**: the finished reply lands on the turn it answered, the `Speaker's move:` preamble is stripped, the host turn is untouched, and the shared history objects are **replaced rather than mutated** (so the session writer's shallow snapshot cannot race it). Image replies are not recorded.
- **Voice-only**: the digest and objectives reach the voice worker and are kept out of the image path.
- **Lock precedence**: a locked objective beats the prediction in both the tracker (`observe`) and the prompt (`resolve_active`), and is marked with the serve-it line.
- **Hysteresis**: one prediction does not commit, the second agreeing one does; a different index starts a new streak; an out-of-range/`-1` prediction resets it; a lock pins immediately (`source: "lock"`, confidence 1.0).
- **Persistence round-trip**: all four fields survive `_normalize`; a short lock list is padded; a missing `objective_meta` degrades to `{}`; `new_session` clears and archives them.
- **Pane**: renders the list, focus banner, `Locked` badge, add form, Predict now and the timeline; sends all four control messages; console clean (the Preact `insertBefore` bug the author hit is fixed by rendering every block and hiding empties with an `empty` class).
- **JEV plumbing**: `current_objective` choice question + repurposed `objective_N` nouls (purpose checklist stays the fallback); `objectives` / `active_objective` in the state; the reply worker's own decision call answers `current_objective` and forwards it as `objective_observed`.

## Not covered here

- **Live JEV path** — `JEV_ENABLED=false` in this environment, so only the LLM fallback was exercised end-to-end. The JEV question/state shapes are asserted offline in `_tmp_objective_check.py` `[6]` and `_tmp_auto_reply_prompt_check.py` `[19]`, but a real JEV decision call was not made.
- **Digest + objectives together on a live session** — the report scenarios run with no objectives tracked, so the interaction of a tracked focus with a live reply is untested outside the offline gate.
- **Hub parity** — the Go hub still does not own objectives (documented follow-up).
- **Multi-run statistics** — `--repeat 3` is a small sample; the L2/L3/L4 movements need a larger N before the flag default is revisited.
