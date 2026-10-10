import logging
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from src.bullet_points_worker import BulletPointsWorker
from src.config import (
    BULLET_FLUSH_INTERVAL_MS,
    BULLET_MAX_BUFFER_LINES,
    BULLET_MAX_ITEMS,
    BULLET_PAUSED_BUFFER_MAX,
)

logger = logging.getLogger(__name__)


class BulletPointsController(QObject):
    """Maintains a rolling bullet-point list of the live conversation.

    The list is kept as state and each AI call receives the current list plus
    only the new lines, so cost stays flat instead of re-sending the transcript.
    Finalized lines are always buffered (free); the repeating timer *polls* only
    while ``auto`` is on, and ticks are free when the buffer is empty or a call
    is in flight. ``set_auto`` pauses/resumes the automatic updates while keeping
    the current list as a checkpoint; ``flush_now(force=True)`` updates on demand
    (the manual hotkey) regardless of ``auto``.
    """

    updated = Signal(list, dict)  # (items, speaker profile)
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
        self._speaker = {}
        self._buffer = []
        self._inflight_lines = []
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
                self.updated.emit(list(self._bullets), dict(self._speaker))
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
        self._buffer.append((source, text))
        if len(self._buffer) > BULLET_PAUSED_BUFFER_MAX:
            self._buffer = self._buffer[-BULLET_PAUSED_BUFFER_MAX:]
        if self._auto and len(self._buffer) >= BULLET_MAX_BUFFER_LINES:
            self._maybe_flush()

    def flush_now(self, force: bool = False):
        """Flush the buffer now. ``force`` updates even when auto is off (hotkey)."""
        self._maybe_flush(force=force)

    def hard_regenerate(self, lines):
        """Rebuild the whole list from the entire transcript (ignores the checkpoint).

        ``lines`` is a list of ``(source, text)`` pairs. Buffered/in-flight lines
        are dropped (the transcript supersedes them) but the current list stays
        visible until the new one arrives. Works with auto on or off.
        """
        self._buffer = []
        self._inflight_lines = []
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
        self._start_worker([], {}, lines, rebuild=True)

    def reset(self):
        """Clear the list, profile, and buffer (e.g. at the start of a session)."""
        self._bullets = []
        self._speaker = {}
        self._buffer = []
        self.updated.emit([], {})

    def load_state(self, items, speaker=None):
        """Seed the list and speaker profile from a restored session (no AI call)."""
        self._bullets = list(items or [])[:BULLET_MAX_ITEMS]
        self._speaker = dict(speaker or {})
        self._buffer = []
        logger.debug(
            "Bullet points restored: %d items, %d profile fields",
            len(self._bullets),
            len(self._speaker),
        )

    def _maybe_flush(self, force: bool = False):
        """Start a worker only when (auto or forced), idle, and there is something new."""
        if not self._auto and not force:
            return
        if not self._buffer:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._inflight_lines = self._buffer
        self._buffer = []
        self._start_worker(list(self._bullets), dict(self._speaker), self._inflight_lines)

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
        items = payload.get("items") if isinstance(payload, dict) else None
        speaker = payload.get("speaker") if isinstance(payload, dict) else None
        self._bullets = list(items or [])[:BULLET_MAX_ITEMS]
        if isinstance(speaker, dict):
            self._speaker = dict(speaker)
        self.updated.emit(list(self._bullets), dict(self._speaker))
        self.status_changed.emit("complete")

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
