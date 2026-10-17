"""Temp check: session objectives — OFFLINE tier.

Deterministic, no-network gate for the objective tracker (Phase 2). It drives the
REAL ``ObjectiveController`` with the prediction worker stubbed, and the real
``SessionStore`` against a temp directory, and asserts:

  * the pure helpers (``src/objectives.py``): slug keys, lock alignment,
    ``resolve_active`` precedence, the hysteresis in ``observe``;
  * lock pinning: a locked objective wins over both a prediction and a JEV choice;
  * the controller's debounce, busy guard, stale-window discard, history append
    and its cap, list editing (add / remove / lock / prune);
  * the session round-trip through ``SessionStore._normalize`` (the three list
    fields + ``objective_meta`` survive, locks are re-aligned, then New Session
    clears them and the archive keeps them);
  * the JEV plumbing in ``build_questions`` / ``build_state``.

Run from the repo root:
    venv/bin/python _tmp_objective_check.py
"""
import json
import os
import shutil
import sys
import tempfile

from PySide6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)

REPO = os.path.dirname(os.path.abspath(__file__))
os.chdir(REPO)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import src.controllers.objective_controller as oc_mod  # noqa: E402
import src.session_store as ss  # noqa: E402
from src.config import (  # noqa: E402
    OBJECTIVE_DEBOUNCE_MS,
    OBJECTIVE_MAX_HISTORY,
    OBJECTIVE_MAX_ITEMS,
    OBJECTIVE_MIN_STREAK,
)
from src.controllers.objective_controller import ObjectiveController  # noqa: E402
from src.decision_client import build_questions, build_state  # noqa: E402
from src.objectives import (  # noqa: E402
    align_locks,
    history_entry,
    locked_index,
    objective_key,
    observe,
    resolve_active,
)
from src.session_store import SessionStore  # noqa: E402

failures = []
n_pass = 0


def check(name, cond, detail=""):
    global n_pass
    ok = bool(cond)
    if ok:
        n_pass += 1
    else:
        failures.append(name)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))


# --- stub prediction worker ----------------------------------------------
class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot, *args, **kwargs):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _FakeWorker:
    """Records how the controller builds it; results are emitted by the test."""

    running = False
    instances = []

    def __init__(self, lines, objectives, locks=None, meta=None, **kwargs):
        self.lines = list(lines)
        self.objectives = list(objectives)
        self.locks = list(locks or [])
        self.meta = dict(meta or {})
        self.result = _FakeSignal()
        self.error = _FakeSignal()
        self.started = False
        _FakeWorker.instances.append(self)

    def start(self):
        self.started = True

    def isRunning(self):
        return _FakeWorker.running

    def stop(self):
        pass

    def wait(self, ms=0):
        return True

    def deleteLater(self):
        pass


_RealWorker = oc_mod.ObjectiveWorker
oc_mod.ObjectiveWorker = _FakeWorker


def new_controller(objectives=None, locks=None, meta=None):
    ctrl = ObjectiveController()
    if objectives is not None:
        ctrl.set_objectives(objectives, locks)
    if meta is not None:
        ctrl._meta = dict(meta)
    return ctrl


def last_worker():
    return _FakeWorker.instances[-1] if _FakeWorker.instances else None


# =====================================================================
# [1] Pure helpers
# =====================================================================
print("[1] Pure helpers — keys, lock alignment, resolution")
check("objective_key slugs a label", objective_key("Confirm the rollout timeline")
      == "confirm_the_rollout_timeline")
check("objective_key never returns an empty key", objective_key("  ") == "objective")
check("align_locks pads a short lock list",
      align_locks(["a", "b", "c"], [True]) == [True, False, False])
check("align_locks trims a long lock list",
      align_locks(["a"], [True, True, True]) == [True])
check("locked_index finds the first lock",
      locked_index(["a", "b", "c"], [False, True, True]) == 1)
check("locked_index is None with no locks", locked_index(["a"], [False]) is None)

_objs = ["Confirm the timeline", "Agree on the data scope", "Fix the owner"]
check("resolve_active prefers the tracked index when nothing is locked",
      resolve_active(_objs, [False, False, False], {"active": 1, "confidence": 0.7,
                                                    "source": "llm"})
      == {"index": 1, "text": "Agree on the data scope", "locked": False,
          "confidence": 0.7, "source": "llm"})
check("resolve_active lets a lock beat the prediction",
      resolve_active(_objs, [False, False, True], {"active": 1, "confidence": 0.9})
      == {"index": 2, "text": "Fix the owner", "locked": True,
          "confidence": 1.0, "source": "lock"})
check("resolve_active is empty without a usable index",
      resolve_active(_objs, [False, False, False], {"active": 7}) == {}
      and resolve_active(_objs, [], {}) == {}
      and resolve_active([], [True], {"active": 0}) == {})
check("a boolean is not accepted as an index",
      resolve_active(_objs, [False, False, False], {"active": True}) == {})
check("history_entry names the objective and stamps a time",
      history_entry(_objs, 0, 0.5, "jev")["text"] == "Confirm the timeline"
      and bool(history_entry(_objs, 0, 0.5, "jev")["ts"]))

# =====================================================================
# [2] Hysteresis — observe()
# =====================================================================
print("\n[2] Hysteresis — a transition commits only after N agreeing predictions")
_c = ["one", "two"]
_meta, committed = observe(_c, [], {}, 1, 0.9, "llm", 2)
check("a single prediction does not commit", not committed and _meta["pending"] == 1)
check("the streak is recorded", _meta["streak"] == 1 and _meta.get("active") is None)
_meta, committed = observe(_c, [], _meta, 1, 0.8, "llm", 2)
check("the second agreeing prediction commits", committed and _meta["active"] == 1)
check("a commit records confidence/source and clears the streak",
      _meta["confidence"] == 0.8 and _meta["source"] == "llm"
      and _meta["pending"] is None and _meta["streak"] == 0)

_meta, committed = observe(_c, [], _meta, 0, 0.9, "llm", 2)
check("a different index starts a new streak", not committed and _meta["pending"] == 0
      and _meta["streak"] == 1)
_meta, committed = observe(_c, [], _meta, 1, 0.9, "llm", 2)
check("flip-flopping never commits (returning to the active index cancels the candidate)",
      not committed and _meta["active"] == 1 and _meta["streak"] == 0
      and _meta["pending"] is None)
_meta, committed = observe(_c, [], _meta, -1, 0.0, "llm", 2)
check("'no idea' resets the streak instead of counting as agreement",
      not committed and _meta["pending"] is None and _meta["streak"] == 0)
_meta, committed = observe(_c, [], _meta, 7, 0.9, "llm", 2)
check("an out-of-range index is ignored", not committed and _meta["streak"] == 0)
_meta, committed = observe(_c, [], _meta, 1, 0.9, "llm", 2)
check("agreeing with the already-active index is not a transition",
      not committed and _meta["active"] == 1 and _meta["streak"] == 0)
check("a min_streak of 1 commits immediately",
      observe(_c, [], {}, 0, 0.5, "llm", 1)[1] is True)

# =====================================================================
# [3] Lock pinning — a lock beats a prediction and a JEV choice
# =====================================================================
print("\n[3] Lock pinning — a locked objective cannot be re-classified away")
_meta, committed = observe(_c, [False, True], {"active": 0, "confidence": 0.9}, 0, 0.9, "jev", 2)
check("a lock pins the tracker even with no prediction agreement", committed)
check("the pin is recorded as the lock's source",
      _meta["active"] == 1 and _meta["source"] == "lock" and _meta["confidence"] == 1.0)
_meta2, committed = observe(_c, [False, True], _meta, 0, 0.99, "jev", 2)
check("a later prediction cannot move off the locked objective",
      not committed and _meta2["active"] == 1)
check("resolve_active then reports the locked objective",
      resolve_active(_c, [False, True], _meta2)["index"] == 1)

# =====================================================================
# [4] Controller — list editing and paths
# =====================================================================
print("\n[4] Controller — list editing, locks and meta pruning")
ctrl = ObjectiveController()
_seen = []
ctrl.objectives_changed.connect(lambda items, locks: _seen.append((list(items), list(locks))))
ctrl.active_changed.connect(lambda active: _seen.append(dict(active)))
ctrl.set_objectives(["a", "b", "c"])
check("set_objectives emits the list", _seen[0] == (["a", "b", "c"], [False, False, False]),
      str(_seen[0]))
check("set_objectives also publishes the (empty) resolved focus",
      _seen[1] == {}, str(_seen[1]))
check("predict_now with no objectives reports no_input",
      new_controller().predict_now() is False)
check("add_objective appends", ctrl.add_objective("d") and ctrl.get_objectives() == ["a", "b", "c", "d"])
check("add_objective ignores a duplicate", ctrl.add_objective("d") is False)
check("add_objective ignores an empty string", ctrl.add_objective("   ") is False)
check("set_lock by text resolves the item",
      ctrl.set_lock(index=None, text="c", locked=True) and ctrl.get_locks() == [False, False, True, False])
check("set_lock ignores an already-set value",
      ctrl.set_lock(index=2, text="c", locked=True) is False)
check("toggle_lock flips it back", ctrl.toggle_lock(2) and ctrl.get_locks()[2] is False)
check("set_lock by index works when the text is stale",
      ctrl.set_lock(index=0, text="gone", locked=True) and ctrl.get_locks()[0] is True)
check("set_lock on a missing item is a no-op", ctrl.set_lock(index=99) is False)

# Locking is a user-declared focus, so it commits the pin (meta + history).
_lock_ctrl = ObjectiveController()
_lock_history = []
_lock_ctrl.history_appended.connect(lambda entry: _lock_history.append(dict(entry)))
_lock_ctrl.set_objectives(["a", "b"])
_lock_ctrl.set_lock(index=1, text="b", locked=True)
check("locking commits the pin to the tracker meta",
      _lock_ctrl.get_meta()["active"] == 1 and _lock_ctrl.get_meta()["source"] == "lock"
      and _lock_ctrl.get_meta()["confidence"] == 1.0, str(_lock_ctrl.get_meta()))
check("locking appends one history entry with the lock source",
      len(_lock_history) == 1 and _lock_history[0]["source"] == "lock",
      str(_lock_history))
check("unlocking keeps the tracked focus where it was",
      _lock_ctrl.set_lock(index=1, locked=False)
      and _lock_ctrl.get_meta()["active"] == 1
      and _lock_ctrl.get_active()["locked"] is False)

# Unlock everything first so the removal's effect on the tracked index is visible.
ctrl._locks = [False] * len(ctrl.get_objectives())
ctrl._prune_meta()
ctrl._meta = {"active": 3, "confidence": 0.5, "source": "llm"}
check("removing the active objective clears the focus", ctrl.remove_objective(3))
check("the tracked index is cleared", ctrl.get_meta().get("active") is None)
check("with no lock and no tracked index the focus is empty", ctrl.get_active() == {})
ctrl.set_objectives(["a", "b", "c"], [False, True, False])
ctrl._meta = {"active": 2, "confidence": 0.5, "source": "llm"}
ctrl.remove_objective(2)
check("a remaining lock owns the focus after a removal",
      ctrl.get_active().get("index") == 1 and ctrl.get_active().get("source") == "lock")
ctrl.set_objectives(["x", "y", "z"])
ctrl._meta = {"active": 2, "confidence": 0.5, "source": "llm"}
ctrl.remove_objective(0)
check("removing an earlier objective shifts the active index",
      ctrl.get_meta().get("active") == 1 and ctrl.get_active()["text"] == "z")
ctrl._meta = {"active": 2, "confidence": 0.5, "source": "llm",
              "pending": 2, "streak": 1}
ctrl.set_objectives(["only-one"])
check("editing the list prunes an out-of-range focus and pending",
      ctrl.get_meta().get("active") is None and ctrl.get_meta().get("pending") is None)
_capped = ObjectiveController()
_capped.set_objectives([f"o{i}" for i in range(OBJECTIVE_MAX_ITEMS + 5)])
check("the objectives cap is enforced (newest kept)",
      len(_capped.get_objectives()) == OBJECTIVE_MAX_ITEMS
      and _capped.get_objectives()[0] == "o5",
      str(OBJECTIVE_MAX_ITEMS))

# =====================================================================
# [5] Controller — debounce, prediction commit, history
# =====================================================================
print("\n[5] Controller — debounce, prediction commit and history")
ctrl = new_controller(["ship the pilot", "agree on pricing"])
ctrl.add_line("speaker", "so what do we do about the pilot?")
ctrl.schedule()
check("the debounce is single-shot and armed with OBJECTIVE_DEBOUNCE_MS",
      ctrl._timer.isSingleShot() and ctrl._timer.isActive()
      and ctrl._timer.interval() == OBJECTIVE_DEBOUNCE_MS)
ctrl._timer.stop()

_seen_history = []
ctrl.history_appended.connect(lambda entry: _seen_history.append(dict(entry)))
ctrl.predict_now()
worker = last_worker()
check("predict_now starts a worker carrying the window and the list",
      worker is not None and worker.started
      and worker.objectives == ["ship the pilot", "agree on pricing"]
      and worker.lines and worker.lines[0][0] == "speaker",
      str(worker.lines if worker else None))
_status = []
ctrl.status_changed.connect(_status.append)
worker.result.emit(0, 0.8, "llm")
check("the first prediction does not commit", _seen_history == [])
worker = last_worker()
worker.result.emit(0, 0.85, "llm")
check("the second agreeing prediction commits", len(_seen_history) == 1)
check("the history entry names the objective",
      _seen_history[0]["text"] == "ship the pilot"
      and _seen_history[0]["confidence"] == 0.85 and _seen_history[0]["source"] == "llm")
check("the resolved focus follows the commit", ctrl.get_active()["index"] == 0)
check("a completed prediction reports 'complete'", _status[-1] == "complete", str(_status))

# A prediction that is still in flight when the conversation moves on is stale.
ctrl.predict_now()
stale = last_worker()
ctrl.add_line("speaker", "actually let's talk pricing")
stale.result.emit(1, 0.99, "llm")
stale.result.emit(1, 0.99, "llm")
check("a stale-window prediction is discarded", ctrl.get_active()["index"] == 0)

# The busy guard queues exactly one rerun instead of dropping the window.
_FakeWorker.running = True
ctrl._worker = last_worker()          # pretend that prediction is still in flight
ctrl.predict_now()
check("a prediction while one is running is queued, not started",
      ctrl._rerun_pending is True and ctrl._worker is last_worker())
ctrl._rerun_pending = False
ctrl._worker = None
_FakeWorker.running = False

# Manual JEV observation (from the reply worker) is folded in the same way.
ctrl2 = new_controller(["first", "second"])
ctrl2.observe(1, 0.7, "jev")
check("one JEV observation does not commit", ctrl2.get_active().get("index") in (None, 0))
ctrl2.observe(1, 0.9, "jev")
check("two agreeing JEV observations commit", ctrl2.get_active()["index"] == 1)
check("the JEV commit keeps its source", ctrl2.get_meta()["source"] == "jev")
_SOURCE = ctrl2.get_history()[-1]["source"]
check("the history records the JEV source", _SOURCE == "jev", _SOURCE)

# History cap: patched so the test stays cheap, then restored.
_prev_cap = oc_mod.OBJECTIVE_MAX_HISTORY
try:
    oc_mod.OBJECTIVE_MAX_HISTORY = 3
    ctrl3 = new_controller([f"obj{i}" for i in range(5)])
    for i in range(5):
        ctrl3.observe(i, 0.9, "llm")
        ctrl3.observe(i, 0.9, "llm")
    check("the history is capped (newest kept)",
          len(ctrl3.get_history()) == 3 and ctrl3.get_history()[-1]["index"] == 4,
          str(len(ctrl3.get_history())))
finally:
    oc_mod.OBJECTIVE_MAX_HISTORY = _prev_cap

ctrl3.reset()
check("reset clears the list, locks, history and focus",
      ctrl3.get_objectives() == [] and ctrl3.get_locks() == []
      and ctrl3.get_history() == [] and ctrl3.get_active() == {})

# =====================================================================
# [6] JEV plumbing — the objective question and state
# =====================================================================
print("\n[6] JEV — the current_objective question and state fields")
_qs = build_questions({}, {}, ["fallback one"], False, [], None,
                      objectives=["Confirm the timeline", "Fix the owner"])
check("a current_objective choice question is added",
      _qs["current_objective"]["type"] == "choice"
      and _qs["current_objective"]["criteria"]
      == {"confirm_the_timeline": "Confirm the timeline", "fix_the_owner": "Fix the owner"})
check("the per-objective noul questions use the session objectives",
      _qs["objective_0"]["instructions"] == "Confirm the timeline"
      and _qs["objective_1"]["instructions"] == "Fix the owner")
check("with no session objectives the purpose checklist is the fallback",
      build_questions({}, {}, ["fallback one"], False, [], None)["objective_0"]["instructions"]
      == "fallback one"
      and "current_objective" not in build_questions({}, {}, [], False, [], None))
_st = build_state("host", "speaker", "Consultation", "consultant", [], "hi",
                  objectives=["Confirm the timeline"],
                  active_objective={"index": 0, "text": "Confirm the timeline"})
check("the state carries the objectives", _st["objectives"] == ["Confirm the timeline"])
check("the state carries the resolved objective",
      _st["active_objective"]["text"] == "Confirm the timeline")
check("the state omits both when there are none",
      "objectives" not in build_state("h", "s", "p", "r", [], "hi")
      and "active_objective" not in build_state("h", "s", "p", "r", [], "hi"))

# =====================================================================
# [7] Session round-trip
# =====================================================================
print("\n[7] Session round-trip — the fields survive _normalize, then New Session")
# The writer threads debounce at 2 s by default; at 20 ms each store settles
# before the temp dir is torn down, so the harness never races its own writers.
_prev_debounce = ss.SESSION_WRITE_DEBOUNCE_MS
ss.SESSION_WRITE_DEBOUNCE_MS = 20
tmpdir = tempfile.mkdtemp(prefix="objectives-check-")
try:
    store = SessionStore(directory=tmpdir)
    store.set_objectives(["ship the pilot", "agree on pricing"])
    store.set_objective_locks([False, True])
    store.set_objective_meta({"active": 1, "confidence": 0.8, "source": "lock"})
    store.append("objective_history", {"ts": "2026-10-17T00:00:00Z", "index": 1,
                                       "text": "agree on pricing", "confidence": 0.9,
                                       "source": "jev"})
    store.flush()

    with open(store.path, encoding="utf-8") as f:
        raw = json.load(f)
    check("the fields are written to current.json",
          raw["objectives"] == ["ship the pilot", "agree on pricing"]
          and raw["objective_locks"] == [False, True]
          and raw["objective_meta"]["active"] == 1
          and len(raw["objective_history"]) == 1)

    # A fresh store reads them back: _normalize must keep every field (a field
    # missing from SESSION_FIELDS / SESSION_OBJECT_FIELDS is silently dropped).
    reloaded = SessionStore(directory=tmpdir)
    snap = reloaded.snapshot()
    check("objectives survive a reload", snap["objectives"] == ["ship the pilot", "agree on pricing"])
    check("locks survive a reload", snap["objective_locks"] == [False, True])
    check("the tracker meta survives a reload", snap["objective_meta"]["active"] == 1
          and snap["objective_meta"]["source"] == "lock")
    check("the history survives a reload", len(snap["objective_history"]) == 1)

    # A short / absent locks list (an older session file) is padded, not dropped.
    with open(reloaded.path, encoding="utf-8") as f:
        legacy = json.load(f)
    legacy["objective_locks"] = []
    del legacy["objective_meta"]
    with open(reloaded.path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)
    legacy_store = SessionStore(directory=tmpdir)
    check("an older session file pads the lock list",
          legacy_store.snapshot()["objective_locks"] == [False, False])
    check("a missing objective_meta degrades to {}",
          legacy_store.snapshot()["objective_meta"] == {})

    # The history cap is wired to SESSION_CAPS (patched down for speed).
    _prev_hist = ss.SESSION_CAPS["objective_history"]
    try:
        ss.SESSION_CAPS["objective_history"] = 3
        for i in range(5):
            legacy_store.append("objective_history", {"index": i})
        check("append trims the history to the cap",
              len(legacy_store.snapshot()["objective_history"]) == 3
              and legacy_store.snapshot()["objective_history"][-1]["index"] == 4)
    finally:
        ss.SESSION_CAPS["objective_history"] = _prev_hist
    check("OBJECTIVE_MAX_HISTORY matches the configured cap", OBJECTIVE_MAX_HISTORY == 200)

    archived = legacy_store.new_session()
    check("New Session archives the session (objectives included)", bool(archived))
    check("the fresh session is cleared",
          legacy_store.snapshot()["objectives"] == []
          and legacy_store.snapshot()["objective_locks"] == []
          and legacy_store.snapshot()["objective_history"] == []
          and legacy_store.snapshot()["objective_meta"] == {})
    if archived:
        with open(archived, encoding="utf-8") as f:
            archived_data = json.load(f)
        check("the archived file keeps the objectives",
              len(archived_data["objectives"]) == 2
              and len(archived_data["objective_history"]) == 3)
    legacy_store.close()
    reloaded.close()
    store.close()
finally:
    ss.SESSION_WRITE_DEBOUNCE_MS = _prev_debounce
    shutil.rmtree(tmpdir, ignore_errors=True)

oc_mod.ObjectiveWorker = _RealWorker

print()
print(f"{n_pass} checks passed, {len(failures)} failed.")
print("FAILURES:", failures or "none")
sys.exit(1 if failures else 0)
