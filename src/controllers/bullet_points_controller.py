import logging
import re
import time
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from src.bullet_points_worker import BulletPointsWorker
from src.config import (
    BULLET_FLUSH_INTERVAL_MS,
    BULLET_MAX_BUFFER_LINES,
    BULLET_PAUSED_BUFFER_MAX,
)

logger = logging.getLogger(__name__)

# Similarity threshold for the near-duplicate guard in ``_merge_new_items``.
_ITEM_SIMILARITY = 0.8
# Punctuation stripped from the ends of a normalized bullet before comparing.
_ITEM_TRIM_CHARS = ".,;:!?()[]{}\"'` \t"


class BulletPointsController(QObject):
    """Maintains a rolling bullet-point list of the live conversation.

    The list is kept as state and each AI call receives the current list plus
    only the new lines, so cost stays flat instead of re-sending the transcript.
    Updates are **append-only**: the AI returns only the points that are new for
    the new lines and the controller merges them onto the existing list (a
    rebuild call replaces the whole list instead). The list is not capped.
    Finalized lines are always buffered (free); the repeating timer *polls* only
    while ``auto`` is on, and ticks are free when the buffer is empty or a call
    is in flight. ``set_auto`` pauses/resumes the automatic updates while keeping
    the current list as a checkpoint; ``flush_now(force=True)`` updates on demand
    (the manual hotkey) regardless of ``auto``. Each update also records a
    *window* — the time range of the lines that produced it, with the index range
    of the bullets it appended — under ``bullet_windows``.
    """

    # (items, speaker profile, bullet windows, per-item lock flags)
    updated = Signal(list, dict, list, list)
    status_changed = Signal(str)
    error_occurred = Signal(str)
    # (auto active, epoch seconds of the next interval tick; 0 when auto is off).
    # The pane renders this as the countdown under the Bullet Points tab title,
    # so the frontend and the backend QTimer share one deadline.
    countdown_changed = Signal(bool, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto = False
        self._bullets = []
        # Parallel to ``_bullets``: ``True`` pins an item so a Rebuild keeps it
        # verbatim at the top instead of replacing it with the AI's list.
        self._locked = []
        self._speaker = {}
        self._bullet_windows = []
        self._buffer = []
        self._inflight_lines = []
        self._inflight_window = None
        self._worker = None
        self._old_workers = []
        self._next_flush_at = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(BULLET_FLUSH_INTERVAL_MS)
        self._timer.timeout.connect(self._on_interval_tick)

    def is_auto(self):
        return self._auto

    @property
    def next_flush_at(self):
        """Epoch seconds of the next interval tick (0 while auto is off)."""
        return self._next_flush_at if self._auto else 0.0

    def _arm_countdown(self):
        """Publish the deadline of the *next* interval tick to the panes."""
        self._next_flush_at = time.time() + BULLET_FLUSH_INTERVAL_MS / 1000.0
        self.countdown_changed.emit(True, self._next_flush_at)

    def _emit_updated(self):
        """Broadcast the list + profile + windows + locks as one ``updated``."""
        self.updated.emit(
            list(self._bullets),
            dict(self._speaker),
            self._windows_copy(),
            list(self._locked),
        )

    def set_auto(self, auto: bool):
        """Turn automatic updates on/off, keeping the current list as a checkpoint."""
        auto = bool(auto)
        if auto == self._auto:
            return
        self._auto = auto
        if auto:
            self._timer.start()
            self._arm_countdown()
            # Show the checkpoint immediately, then catch up on buffered lines.
            if self._bullets or self._speaker:
                self._emit_updated()
            if self._buffer:
                self._maybe_flush()
        else:
            self._timer.stop()
            self._next_flush_at = 0.0
            self.countdown_changed.emit(False, 0.0)
        logger.debug("Bullet points auto=%s (buffer=%d)", auto, len(self._buffer))

    def _on_interval_tick(self):
        """The repeating auto timer fired: re-arm the countdown, then flush.

        Only this path (and ``set_auto``) moves the deadline, so an early
        flush (full buffer / manual hotkey) never shifts the 5-minute cadence
        the pane is counting down.
        """
        self._arm_countdown()
        self._maybe_flush()

    def add_line(self, source: str, text: str):
        """Buffer a finalized line (always; free). Auto mode flushes early at N lines."""
        text = (text or "").strip()
        if not text:
            return
        self._buffer.append((source, text, datetime.now().isoformat()))
        if len(self._buffer) > BULLET_PAUSED_BUFFER_MAX:
            self._buffer = self._buffer[-BULLET_PAUSED_BUFFER_MAX:]
        if self._auto and len(self._buffer) >= BULLET_MAX_BUFFER_LINES:
            self._maybe_flush()

    def flush_now(self, force: bool = False) -> bool:
        """Flush the buffer now. ``force`` updates even when auto is off (hotkey/button).

        Returns True when an update was actually started, False when there was
        nothing buffered or a call was already in flight — the manual button
        uses that to show the pane a "nothing new" notice.
        """
        return self._maybe_flush(force=force)

    def is_busy(self) -> bool:
        """True while a bullet-points AI call is in flight."""
        return self._worker is not None and self._worker.isRunning()

    def hard_regenerate(self, lines):
        """Rebuild the whole list from the entire transcript (ignores the checkpoint).

        ``lines`` is a list of ``(source, text)`` or ``(source, text, timestamp)``
        entries. Buffered/in-flight lines are dropped (the transcript supersedes
        them) but the current list stays visible until the new one arrives. Works
        with auto on or off.
        """
        self._buffer = []
        self._inflight_lines = []
        self._inflight_window = None
        if self._worker is not None:
            # Suppress the old worker so a late result can't overwrite the rebuild.
            self._worker.stop()
            try:
                self._worker.result.disconnect(self._on_result)
                self._worker.error.disconnect(self._on_error)
            except (RuntimeError, TypeError):
                pass
            self._old_workers.append(self._worker)
            self._worker = None
            self._cleanup_old_workers()
        lines = list(lines or [])
        if not lines:
            logger.info("Bullet points rebuild skipped: empty transcript")
            self.status_changed.emit("error")
            return
        logger.info("Rebuilding bullet points from %d transcript lines", len(lines))
        self._inflight_window = self._make_window("rebuild", lines)
        self._start_worker(self.locked_items(), {}, lines, rebuild=True)

    def reset(self):
        """Clear the list, profile, windows, locks, and buffer (e.g. a new session)."""
        self._bullets = []
        self._locked = []
        self._speaker = {}
        self._bullet_windows = []
        self._buffer = []
        self._emit_updated()

    def load_state(self, items, speaker=None, windows=None, locks=None):
        """Seed the list, speaker profile, windows, and locks from a session."""
        self._bullets = list(items or [])
        self._locked = self._align_locks(self._bullets, locks)
        self._speaker = dict(speaker or {})
        self._bullet_windows = [dict(w) for w in (windows or []) if isinstance(w, dict)]
        self._buffer = []
        logger.debug(
            "Bullet points restored: %d items, %d locked, %d profile fields, %d windows",
            len(self._bullets),
            sum(1 for locked in self._locked if locked),
            len(self._speaker),
            len(self._bullet_windows),
        )

    # --- locks (pinned-on-top rebuild) --------------------------------

    @staticmethod
    def _align_locks(items, locks):
        """Normalize ``locks`` to a ``list[bool]`` matching ``len(items)``.

        A short/absent list (an older session file) pads with ``False``; an
        over-long one (a stale write) is truncated.
        """
        n = len(items or [])
        source = list(locks or [])
        return [bool(source[i]) if i < len(source) else False for i in range(n)]

    def locked_items(self) -> list:
        """The bullet texts currently pinned, in list order."""
        return [text for text, locked in zip(self._bullets, self._locked) if locked]

    def set_lock(self, index=None, text=None, locked=None) -> bool:
        """Pin/unpin one bullet by exact ``text`` (preferred) or ``index``.

        When ``locked`` is given the flag is set to it; otherwise it is flipped.
        Returns ``False`` when the item can't be found or nothing changed.
        """
        target = None
        if text is not None:
            needle = str(text)
            for i, item in enumerate(self._bullets):
                if item == needle:
                    target = i
                    break
        if target is None and index is not None:
            try:
                i = int(index)
            except (TypeError, ValueError):
                i = -1
            if 0 <= i < len(self._bullets):
                target = i
        if target is None:
            logger.debug("Bullet lock ignored: item not found (text=%r index=%r)", text, index)
            return False
        self._locked = self._align_locks(self._bullets, self._locked)
        new_value = (not self._locked[target]) if locked is None else bool(locked)
        if new_value == self._locked[target]:
            return False
        self._locked[target] = new_value
        logger.info("Bullet %d lock=%s: %s", target, new_value, self._bullets[target])
        self._emit_updated()
        return True

    def _maybe_flush(self, force: bool = False) -> bool:
        """Start a worker when (auto or forced), idle, and there is something new.

        Returns True when a worker was started.
        """
        if not self._auto and not force:
            return False
        if not self._buffer:
            return False
        if self._worker is not None and self._worker.isRunning():
            return False
        self._inflight_lines = self._buffer
        self._buffer = []
        self._inflight_window = self._make_window("auto", self._inflight_lines)
        self._start_worker(list(self._bullets), dict(self._speaker), self._inflight_lines)
        return True

    def _start_worker(self, current_bullets: list, current_speaker: dict, lines: list,
                     rebuild: bool = False):
        try:
            self._worker = BulletPointsWorker(
                current_bullets, current_speaker, lines, rebuild=rebuild
            )
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start bullet points worker: %s", e)
            self._requeue_inflight()
            self._worker = None
            self.error_occurred.emit(f"Failed to start bullet points: {e}")

    def _on_result(self, payload: dict):
        self._recycle_worker()
        self._inflight_lines = []
        window = self._inflight_window
        self._inflight_window = None
        items = payload.get("items") if isinstance(payload, dict) else None
        speaker = payload.get("speaker") if isinstance(payload, dict) else None
        # Default "replace" keeps an old-style payload (no mode) safe.
        mode = payload.get("mode", "replace") if isinstance(payload, dict) else "replace"
        new_items = [str(item).strip() for item in (items or []) if str(item).strip()]

        if mode == "append":
            previous = len(self._bullets)
            self._bullets = self._merge_new_items(self._bullets, new_items)
            # The list only grows here; re-align so the tail pads with ``False``.
            self._locked = self._align_locks(self._bullets, self._locked)
            if len(self._bullets) > previous:
                self._record_window(window, previous, len(self._bullets) - 1)
        else:
            # A rebuild rewrote the whole list, so old provenance no longer maps.
            # Locked items are kept verbatim at the top (their order preserved);
            # the AI only returned the points it had not already been given.
            locked = self.locked_items()
            self._bullets = locked + new_items
            self._locked = [True] * len(locked) + [False] * len(new_items)
            self._bullet_windows = []
            if self._bullets:
                self._record_window(window, 0, len(self._bullets) - 1)
        if isinstance(speaker, dict):
            self._speaker = dict(speaker)
        self._emit_updated()
        self.status_changed.emit("complete")

    # --- windows (per-update provenance) ------------------------------

    def _windows_copy(self):
        """A shallow-copied snapshot of the recorded windows (own the dicts)."""
        return [dict(w) for w in self._bullet_windows]

    @staticmethod
    def _entry_timestamp(entry) -> str:
        """The ISO timestamp of a buffered line, or ``""`` when absent."""
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            return str(entry[2] or "")
        return ""

    def _make_window(self, mode: str, lines):
        """Describe the lines an update covers, or ``None`` when untimed."""
        stamps = [t for t in (self._entry_timestamp(e) for e in (lines or [])) if t]
        if not stamps:
            return None
        return {"mode": mode, "start": stamps[0], "end": stamps[-1], "lines": len(lines)}

    def _record_window(self, window, from_index: int, to_index: int):
        """Append one window entry mapping it to the bullets it produced."""
        if not window:
            return
        entry = dict(window)
        entry["from_index"] = from_index
        entry["to_index"] = to_index
        self._bullet_windows.append(entry)

    # --- append merge -------------------------------------------------

    @staticmethod
    def _normalize_item(text: str) -> str:
        """Casefolded, punctuation-stripped, whitespace-collapsed comparison key."""
        key = str(text or "").casefold().strip().strip(_ITEM_TRIM_CHARS)
        return re.sub(r"\s+", " ", key)

    @classmethod
    def _item_tokens(cls, key: str):
        return set(cls._normalize_item(key).split())

    @staticmethod
    def _jaccard(a: set, b: set) -> float:
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    def _merge_new_items(self, existing, new) -> list:
        """Append only genuinely new bullets, dropping exact and near duplicates.

        The model is asked for deltas, but a safety net keeps the list dense: an
        item is skipped when it matches an existing/new item exactly (after
        normalization) or is heavily overlapping (Jaccard token similarity
        >= ``_ITEM_SIMILARITY``). Original wording and order are preserved.
        """
        result = [str(item).strip() for item in (existing or []) if str(item).strip()]
        keys = [self._normalize_item(item) for item in result]
        token_sets = [self._item_tokens(key) for key in keys]
        for item in (new or []):
            text = str(item).strip()
            if not text:
                continue
            key = self._normalize_item(text)
            if not key or key in keys:
                continue
            tokens = self._item_tokens(key)
            if any(self._jaccard(tokens, other) >= _ITEM_SIMILARITY for other in token_sets):
                continue
            result.append(text)
            keys.append(key)
            token_sets.append(tokens)
        return result

    def _on_error(self, msg: str):
        # Put the flushed lines back (before recycling) so they retry next tick.
        self._requeue_inflight()
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit("error")

    def _requeue_inflight(self):
        if self._inflight_lines:
            self._buffer = self._inflight_lines + self._buffer
            self._buffer = self._buffer[-BULLET_PAUSED_BUFFER_MAX:]
        self._inflight_lines = []

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
        """Stop the timer and any running workers.

        The worker may be blocked in a synchronous HTTP call, so a plain wait can
        time out; terminate as a last resort so the QThread isn't destroyed while
        still running (mirrors ``TranslationController``).
        """
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
