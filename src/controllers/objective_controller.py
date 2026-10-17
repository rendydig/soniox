"""Session objective tracker.

Owns the session-level objective list and which one the conversation is working
on. Modelled on ``LastPickupController`` (always buffers lines for free; a
debounced call does the paid work) with the lock/pin semantics and history of
``BulletPointsController``:

* finalized lines fill a rolling window (free);
* every new line re-arms a single-shot timer, so a prediction only fires once
  the speaker pauses (``OBJECTIVE_DEBOUNCE_MS``);
* one prediction at a time (busy guard) — a line arriving mid-call queues one
  rerun;
* a prediction is folded in through ``objectives.observe`` (hysteresis), and only
  a *committed* transition appends to the history timeline;
* a locked objective always wins: a prediction can never move the focus away
  from it (`resolve_active`), and ``observe`` pins the tracker to it.

Predictions come from ``ObjectiveWorker`` (JEV first, LLM fallback) or, for free,
from the auto-reply's own JEV decision call (``observe`` is called directly by
``MainWindow`` with ``source="jev"``).
"""

import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from src.config import (
    OBJECTIVE_DEBOUNCE_MS,
    OBJECTIVE_MAX_HISTORY,
    OBJECTIVE_MAX_ITEMS,
    OBJECTIVE_MIN_STREAK,
    OBJECTIVE_WINDOW_LINES,
)
from src.objectives import (
    align_locks,
    history_entry,
    observe,
    resolve_active,
)
from src.objective_worker import ObjectiveWorker

logger = logging.getLogger(__name__)


class ObjectiveController(QObject):
    """Tracks the session objective list, the active objective and its history."""

    # The list itself changed (edit / lock / new session / restore).
    objectives_changed = Signal(list, list)
    # The resolved active objective changed; ``{}`` means "nothing tracked".
    active_changed = Signal(dict)
    # One committed transition (an entry of the history timeline).
    history_appended = Signal(dict)
    # "started" / "complete" / "error" / "no_input" — mirrors the other panes.
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objectives = []
        self._locks = []
        self._history = []
        self._meta = {}
        self._lines = []
        self._worker = None
        self._old_workers = []
        self._rerun_pending = False
        # Window counter: a prediction for a window the user has moved past is
        # discarded instead of committing a stale focus.
        self._window_id = 0

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._maybe_run)

    # --- state accessors ----------------------------------------------
    def get_objectives(self) -> list:
        return list(self._objectives)

    def get_locks(self) -> list:
        return list(self._locks)

    def get_history(self) -> list:
        return [dict(entry) for entry in self._history]

    def get_meta(self) -> dict:
        return dict(self._meta)

    def get_active(self) -> dict:
        """The resolved active objective (``{}`` when nothing is tracked)."""
        return resolve_active(self._objectives, self._locks, self._meta)

    def is_busy(self) -> bool:
        """True while a prediction is in flight."""
        return self._worker is not None and self._worker.isRunning()

    # --- list editing -------------------------------------------------
    def set_objectives(self, objectives, locks=None):
        """Replace the objective list (and locks), keeping the tracker consistent.

        A prediction that named an index no longer in range is dropped, so the
        list can be edited mid-session without leaving a dangling focus.
        """
        items = [str(o).strip() for o in (objectives or []) if str(o).strip()]
        if len(items) > OBJECTIVE_MAX_ITEMS:
            logger.warning("Objective list over cap (%d > %d); dropping the oldest",
                           len(items), OBJECTIVE_MAX_ITEMS)
            items = items[-OBJECTIVE_MAX_ITEMS:]
        self._objectives = items
        self._locks = align_locks(items, locks)
        self._prune_meta()
        logger.debug("Objectives set: %d item(s), %d locked",
                     len(self._objectives), sum(1 for x in self._locks if x))
        # A lock is a user-declared focus: commit it (meta + history) so the pin
        # survives and the timeline records it. Unlocking just clears the pending
        # candidate, leaving the tracker on whatever was already active.
        self.objectives_changed.emit(self.get_objectives(), self.get_locks())
        self._apply(None, 0.0, "lock")
        self._emit_active()

    def add_objective(self, text: str):
        """Append one objective (ignored when empty or already present)."""
        text = (text or "").strip()
        if not text:
            return False
        if text in self._objectives:
            logger.debug("Objective already present: %r", text)
            return False
        self.set_objectives([*self._objectives, text], [*self._locks, False])
        return True

    def remove_objective(self, index: int):
        """Remove one objective (and its lock), shifting the active index."""
        index = self._resolve_index(index)
        if index is None:
            return False
        objectives = list(self._objectives)
        locks = list(self._locks)
        objectives.pop(index)
        locks.pop(index)
        active = self._meta.get("active")
        if isinstance(active, int) and not isinstance(active, bool):
            if active == index:
                self._meta["active"] = None
                self._meta["source"] = ""
                self._meta["confidence"] = 0.0
            elif active > index:
                self._meta["active"] = active - 1
        self._meta["pending"] = None
        self._meta["streak"] = 0
        self._objectives = objectives
        self._locks = align_locks(objectives, locks)
        self.objectives_changed.emit(self.get_objectives(), self.get_locks())
        self._apply(None, 0.0, "lock")
        self._emit_active()
        return True

    def set_lock(self, index=None, text=None, locked=None) -> bool:
        """Set (or flip) one objective's lock, resolving by exact text first.

        Mirrors ``BulletPointsController.set_lock``: the pane sends the item's
        text *and* its index, so a list that shifted between render and click
        still locks the item the user actually pointed at. ``locked=None``
        flips the flag. Returns False when the item is missing or unchanged.
        """
        resolved = None
        if isinstance(text, str) and text.strip():
            for i, objective in enumerate(self._objectives):
                if objective == text.strip():
                    resolved = i
                    break
        if resolved is None:
            resolved = self._resolve_index(index)
        if resolved is None:
            return False
        self._locks = align_locks(self._objectives, self._locks)
        new_value = (not self._locks[resolved]) if locked is None else bool(locked)
        if new_value == self._locks[resolved]:
            return False
        self._locks[resolved] = new_value
        self._prune_meta()
        self.objectives_changed.emit(self.get_objectives(), self.get_locks())
        # Pin (or release) the focus: see the note in ``set_objectives``.
        self._apply(None, 0.0, "lock")
        self._emit_active()
        return True

    def toggle_lock(self, index) -> bool:
        """Flip one objective's lock by index (convenience wrapper)."""
        return self.set_lock(index=index)

    # --- tracking -----------------------------------------------------
    def add_line(self, source: str, text: str):
        """Buffer a finalized line into the rolling window (always; free)."""
        text = (text or "").strip()
        if not text:
            return
        self._lines.append((source, text))
        if len(self._lines) > OBJECTIVE_WINDOW_LINES:
            self._lines = self._lines[-OBJECTIVE_WINDOW_LINES:]
        self._window_id += 1

    def schedule(self, delay_ms: int = None):
        """(Re)arm the debounce; the UI calls this at the end of an utterance."""
        if not self._objectives:
            return
        self._timer.stop()
        self._timer.start(max(0, int(OBJECTIVE_DEBOUNCE_MS if delay_ms is None else delay_ms)))

    def predict_now(self):
        """Predict on demand (the pane's "Predict now" button), regardless of timing."""
        if not self._objectives:
            self.status_changed.emit("no_input")
            return False
        self._timer.stop()
        self._maybe_run(force=True)
        return True

    def observe(self, index, confidence, source: str = "jev"):
        """Fold an externally computed prediction in (the reply worker's JEV call).

        Returns True when the active objective changed, which is what appends a
        history entry. ``index`` of -1 (or anything out of range) resets the
        hysteresis streak instead of counting as agreement.
        """
        return self._apply(index, confidence, source)

    def load_state(self, objectives, locks=None, history=None, meta=None):
        """Seed the tracker from a restored session (no AI call, no broadcast)."""
        self._objectives = [str(o).strip() for o in (objectives or []) if str(o).strip()]
        if len(self._objectives) > OBJECTIVE_MAX_ITEMS:
            self._objectives = self._objectives[-OBJECTIVE_MAX_ITEMS:]
        self._locks = align_locks(self._objectives, locks)
        self._history = [dict(h) for h in (history or []) if isinstance(h, dict)]
        self._meta = dict(meta or {})
        self._prune_meta()
        logger.debug("Objectives restored: %d item(s), %d locked, %d history",
                     len(self._objectives), sum(1 for x in self._locks if x), len(self._history))

    def reset(self):
        """Clear the list, locks, history and buffer (New Session)."""
        self._timer.stop()
        self._objectives = []
        self._locks = []
        self._history = []
        self._meta = {}
        self._lines = []
        self._window_id += 1
        self.objectives_changed.emit([], [])
        self._emit_active()

    # --- internals ----------------------------------------------------
    def _resolve_index(self, index):
        """A usable objective index (bounds-checked; ``None`` when unusable)."""
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        if 0 <= index < len(self._objectives):
            return index
        return None

    def _prune_meta(self):
        """Drop a tracked index that the edited list no longer has."""
        active = self._meta.get("active")
        if active is not None and self._resolve_index(active) is None:
            self._meta["active"] = None
            self._meta["confidence"] = 0.0
            self._meta["source"] = ""
        pending = self._meta.get("pending")
        if pending is not None and self._resolve_index(pending) is None:
            self._meta["pending"] = None
            self._meta["streak"] = 0

    def _apply(self, index, confidence, source):
        """Fold one prediction in; True when the active objective changed."""
        before = self._meta.get("active")
        meta, committed = observe(
            self._objectives, self._locks, self._meta, index, confidence, source,
            OBJECTIVE_MIN_STREAK,
        )
        self._meta = meta
        if not committed:
            logger.debug("Objective observation ignored (pending=%s streak=%s)",
                         meta.get("pending"), meta.get("streak"))
            return False

        logger.info("Active objective -> %r (%s, p=%.2f)",
                    (self.get_active() or {}).get("text"), meta.get("source"),
                    meta.get("confidence") or 0.0)
        entry = history_entry(
            self._objectives, meta.get("active"), meta.get("confidence"), meta.get("source"),
        )
        self._history.append(entry)
        if len(self._history) > OBJECTIVE_MAX_HISTORY:
            self._history = self._history[-OBJECTIVE_MAX_HISTORY:]
        self.history_appended.emit(dict(entry))
        if meta.get("active") != before:
            self._emit_active()
        return True

    def _emit_active(self):
        self.active_changed.emit(self.get_active())

    def _maybe_run(self, force: bool = False):
        """Start a prediction when there is something to predict and nothing in flight."""
        if not self._objectives:
            return
        if not self._lines and not force:
            return
        if self.is_busy():
            # A newer window arrived mid-call; refresh once this one finishes.
            self._rerun_pending = True
            return
        self._start_worker()

    def _start_worker(self):
        window = self._window_id
        try:
            self._worker = ObjectiveWorker(
                list(self._lines),
                self.get_objectives(),
                self.get_locks(),
                self.get_meta(),
            )
            self._worker.result.connect(
                lambda index, confidence, source: self._on_result(index, confidence, source, window),
                Qt.ConnectionType.QueuedConnection,
            )
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start objective worker: %s", e)
            self._worker = None
            self.error_occurred.emit(f"Failed to start objective prediction: {e}")

    def _on_result(self, index, confidence, source, window):
        self._recycle_worker()
        if window != self._window_id:
            # The conversation moved on while the call was in flight; committing
            # it now would record a focus the user has already left behind.
            logger.debug("Discarding a stale objective prediction (window %s)", window)
        else:
            self._apply(index, confidence, source)
        self.status_changed.emit("complete")
        self._run_pending()

    def _on_error(self, msg: str):
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit("error")
        self._run_pending()

    def _run_pending(self):
        if self._rerun_pending:
            self._rerun_pending = False
            self._maybe_run()

    def _recycle_worker(self):
        if self._worker is not None:
            self._worker.wait(1000)
            self._old_workers.append(self._worker)
            self._worker = None
            self._cleanup_old_workers()

    def _cleanup_old_workers(self):
        keep = []
        for worker in self._old_workers:
            if worker.isRunning():
                keep.append(worker)
            else:
                worker.deleteLater()
        self._old_workers = keep

    def cleanup(self):
        """Stop the timer and any running workers (terminate as a last resort)."""
        self._timer.stop()
        workers = [w for w in [self._worker, *self._old_workers] if w is not None]
        for worker in workers:
            worker.stop()
        for worker in workers:
            if worker.isRunning():
                worker.wait(3000)
        for worker in workers:
            if worker.isRunning():
                worker.terminate()
                worker.wait(1000)
            worker.deleteLater()
        self._worker = None
        self._old_workers.clear()
