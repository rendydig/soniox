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
    # ("started" / "complete" / "error" / "no_input" / "predicted", message).
    # The message is rendered by the pane; "predicted" is the outcome of a manual
    # "Predict now" press, so the button never looks dead.
    status_changed = Signal(str, str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._objectives = []
        self._locks = []
        self._history = []
        self._meta = {}
        self._lines = []
        # Host/Speaker reference context mirrored by MainWindow; interpretation
        # only — never treated as an objective.
        self._context = {}
        self._worker = None
        self._old_workers = []
        self._rerun_pending = False
        # A manual "Predict now" press commits on the first answer instead of
        # waiting for ``OBJECTIVE_MIN_STREAK`` agreeing predictions (hysteresis is
        # there to stop the *automatic* tracker flip-flopping, not the user).
        self._manual = False
        # Window counter: a prediction for a window the user has moved past is
        # discarded instead of committing a stale focus.
        self._window_id = 0

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._maybe_run)

    # --- state accessors ----------------------------------------------
    def set_context(self, contents):
        """Mirror the Host/Speaker reference context pushed by the web service."""
        self._context = contents if isinstance(contents, dict) else {}

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

    def get_pending(self) -> dict:
        """The unconfirmed candidate (``{}`` when there is none).

        ``observe`` records ``pending`` / ``streak`` while a transition waits for
        ``OBJECTIVE_MIN_STREAK`` agreeing predictions. The pane shows it as a
        *candidate*, so an automatic prediction that has not committed yet is
        still visible instead of looking like nothing happened.
        """
        index = self._resolve_index(self._meta.get("pending"))
        if index is None:
            return {}
        return {
            "index": index,
            "text": self._objectives[index],
            "streak": int(self._meta.get("streak") or 0),
        }

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
        # ``satisfied`` is index-based too: drop the removed one and shift the
        # rest down, or the pane would mark the wrong objective as done.
        satisfied = self._meta.get("satisfied")
        if isinstance(satisfied, list):
            self._meta["satisfied"] = sorted(
                i - 1 if i > index else i for i in satisfied if i != index
            )
        self._meta["pending"] = None
        self._meta["streak"] = 0
        self._objectives = objectives
        self._locks = align_locks(objectives, locks)
        self.objectives_changed.emit(self.get_objectives(), self.get_locks())
        self._apply(None, 0.0, "lock")
        self._emit_active()
        return True

    def set_satisfied(self, indexes) -> bool:
        """Record which objectives the conversation has already met.

        ``indexes`` comes from the reply worker's JEV decision call
        (``objectives_satisfied``). Like ``active``, it is **index-based**, so it
        is pruned whenever the list changes — otherwise an edit would silently
        mark the wrong objective as done. Returns True when the set changed.
        """
        cleaned = sorted({i for i in (indexes or [])
                          if isinstance(i, int) and not isinstance(i, bool)
                          and 0 <= i < len(self._objectives)})
        if cleaned == list(self._meta.get("satisfied") or []):
            return False
        self._meta["satisfied"] = cleaned
        self.objectives_changed.emit(self.get_objectives(), self.get_locks())
        self._emit_active()
        logger.debug("Objectives satisfied: %s", cleaned)
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

    def seed_lines(self, lines):
        """Replace the rolling window from a transcript (``(source, text)`` pairs).

        Used by a manual prediction so it can run off the *conversation* even
        when this launch has not buffered anything yet (a fresh start, or a
        restored session): the transcript is persisted, the window is not.
        Returns True when at least one usable line was seeded.
        """
        seeded = []
        for entry in lines or []:
            try:
                source, text = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            text = str(text or "").strip()
            if text:
                seeded.append((str(source or ""), text))
        if not seeded:
            return False
        self._lines = seeded[-OBJECTIVE_WINDOW_LINES:]
        self._window_id += 1
        logger.debug("Objective window seeded from the transcript (%d line(s))",
                     len(self._lines))
        return True

    def schedule(self, delay_ms: int = None):
        """(Re)arm the debounce; the UI calls this at the end of an utterance."""
        if not self._objectives:
            return
        self._timer.stop()
        self._timer.start(max(0, int(OBJECTIVE_DEBOUNCE_MS if delay_ms is None else delay_ms)))

    def predict_now(self, lines=None):
        """Predict on demand (the pane's "Predict now" button).

        A manual press commits the first answer (``min_streak=1``) — the user
        asked, so waiting for a second agreeing prediction would just look like
        the button is broken. ``lines`` optionally seeds the window from the
        persisted conversation before predicting. Returns False when there is
        nothing to predict from, after telling the pane why.
        """
        if not self._objectives:
            self.status_changed.emit("no_input", "Add an objective first")
            return False
        if lines:
            self.seed_lines(lines)
        if not self._lines:
            self.status_changed.emit("no_input", "Nothing to predict from yet")
            return False
        self._timer.stop()
        self._manual = True
        self._maybe_run(force=True)
        return True

    def observe(self, index, confidence, source: str = "jev"):
        """Fold an externally computed prediction in (the reply worker's JEV call).

        Returns True when the active objective changed, which is what appends a
        history entry. ``index`` of -1 (or anything out of range) resets the
        hysteresis streak instead of counting as agreement.
        """
        committed, _ = self._apply(index, confidence, source)
        return committed

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
        self._manual = False
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
        # ``satisfied`` is index-based like ``active``: a shorter or replaced list
        # must not leave an index pointing at a different objective.
        satisfied = self._meta.get("satisfied")
        if isinstance(satisfied, list):
            kept = [i for i in satisfied
                    if isinstance(i, int) and not isinstance(i, bool)
                    and 0 <= i < len(self._objectives)]
            if kept:
                self._meta["satisfied"] = sorted(set(kept))
            else:
                self._meta.pop("satisfied", None)

    def _apply(self, index, confidence, source, min_streak=None):
        """Fold one prediction in; returns ``(committed, pending)``."""
        before = self._meta.get("active")
        meta, committed = observe(
            self._objectives, self._locks, self._meta, index, confidence, source,
            OBJECTIVE_MIN_STREAK if min_streak is None else min_streak,
        )
        self._meta = meta
        if not committed:
            logger.debug("Objective observation ignored (pending=%s streak=%s)",
                         meta.get("pending"), meta.get("streak"))
            return False, meta.get("pending")

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
        return True, None

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
                context=self._context,
            )
            self._worker.result.connect(
                lambda index, confidence, source: self._on_result(index, confidence, source, window),
                Qt.ConnectionType.QueuedConnection,
            )
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started", "")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start objective worker: %s", e)
            self._worker = None
            self.error_occurred.emit(f"Failed to start objective prediction: {e}")

    def _on_result(self, index, confidence, source, window):
        manual = self._manual
        self._manual = False
        self._recycle_worker()
        if manual:
            # The user asked: commit the first answer and say what it was.
            committed, pending = self._apply(index, confidence, source, min_streak=1)
            self._emit_active()
            resolved = self._resolve_index(index)
            logger.info("Manual objective prediction: %s (committed=%s, p=%.2f, %s)",
                        self._objectives[resolved] if resolved is not None else "(no fit)",
                        committed, float(confidence or 0.0), source)
            self.status_changed.emit(
                "predicted",
                self._prediction_message(index, confidence, source, committed, pending),
            )
        elif window != self._window_id:
            # The conversation moved on while the call was in flight; committing
            # it now would record a focus the user has already left behind.
            logger.debug("Discarding a stale objective prediction (window %s)", window)
            self.status_changed.emit("complete", "")
        else:
            self._apply(index, confidence, source)
            self.status_changed.emit("complete", "")
        self._run_pending()

    def _prediction_message(self, index, confidence, source, committed, pending) -> str:
        """A one-line, human-readable result for the pane's status line."""
        resolved = self._resolve_index(index)
        if resolved is None:
            return "No objective fits the conversation yet"
        text = self._objectives[resolved]
        if committed:
            return f"Predicted: {text} (p={float(confidence or 0.0):.2f} · {source})"
        if pending is not None:
            return f"Candidate: {text} (waiting for confirmation)"
        return f"Still working on: {text}"

    def _on_error(self, msg: str):
        self._manual = False
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit("error", msg)
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
