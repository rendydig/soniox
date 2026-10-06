import logging

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

    updated = Signal(list)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto = False
        self._bullets = []
        self._buffer = []
        self._inflight_lines = []
        self._worker = None
        self._old_workers = []

        self._timer = QTimer(self)
        self._timer.setInterval(BULLET_FLUSH_INTERVAL_MS)
        self._timer.timeout.connect(self._maybe_flush)

    def is_auto(self):
        return self._auto

    def set_auto(self, auto: bool):
        """Turn automatic updates on/off, keeping the current list as a checkpoint."""
        auto = bool(auto)
        if auto == self._auto:
            return
        self._auto = auto
        if auto:
            self._timer.start()
            # Show the checkpoint immediately, then catch up on buffered lines.
            if self._bullets:
                self.updated.emit(list(self._bullets))
            if self._buffer:
                self._maybe_flush()
        else:
            self._timer.stop()
        logger.debug("Bullet points auto=%s (buffer=%d)", auto, len(self._buffer))

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

    def reset(self):
        """Clear the list and buffer (e.g. at the start of a session)."""
        self._bullets = []
        self._buffer = []
        self.updated.emit([])

    def load_bullets(self, items):
        """Seed the list from a restored session (no AI call, no broadcast)."""
        self._bullets = list(items or [])[:BULLET_MAX_ITEMS]
        self._buffer = []
        logger.debug("Bullet points restored: %d items", len(self._bullets))

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
        self._start_worker(list(self._bullets), self._inflight_lines)

    def _start_worker(self, current_bullets: list, lines: list):
        try:
            self._worker = BulletPointsWorker(current_bullets, lines)
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start bullet points worker: %s", e)
            self._requeue_inflight()
            self._worker = None
            self.error_occurred.emit(f"Failed to start bullet points: {e}")

    def _on_result(self, items: list):
        self._recycle_worker()
        self._inflight_lines = []
        self._bullets = list(items)[:BULLET_MAX_ITEMS]
        self.updated.emit(list(self._bullets))
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
