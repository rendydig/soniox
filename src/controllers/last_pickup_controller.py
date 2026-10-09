import logging

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from src.config import (
    LAST_PICKUP_MAX_LINES,
)
from src.last_pickup_worker import LastPickupWorker

logger = logging.getLogger(__name__)


class LastPickupController(QObject):
    """Tracks the latest topic/intent the speaker is expressing.

    Finalized conversation lines are always buffered into a rolling window (the
    last ``LAST_PICKUP_MAX_LINES``); when ``auto`` is on, a debounced call sends
    that whole window to the AI and emits the resulting Indonesian sentence. The
    result is a single string that replaces the previous one.

    The trigger is externally scheduled (the UI calls ``schedule`` at the end of
    a speaker utterance), so non-final/live text never reaches the AI.
    """

    updated = Signal(str)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto = False
        self._lines = []
        self._worker = None
        self._old_workers = []
        self._rerun_pending = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._maybe_run)

    def is_auto(self):
        return self._auto

    def set_auto(self, auto: bool):
        """Turn automatic pickup on/off; catch up once when enabling."""
        auto = bool(auto)
        if auto == self._auto:
            return
        self._auto = auto
        if auto:
            self._timer.stop()
            self._maybe_run()
        else:
            self._timer.stop()
        logger.debug("Last pickup auto=%s (lines=%d)", auto, len(self._lines))

    def add_line(self, source: str, text: str):
        """Buffer a finalized line into the rolling window (always; free)."""
        text = (text or "").strip()
        if not text:
            return
        self._lines.append((source, text))
        if len(self._lines) > LAST_PICKUP_MAX_LINES:
            self._lines = self._lines[-LAST_PICKUP_MAX_LINES:]

    def schedule(self, delay_ms: int):
        """(Re)arm the debounce; the UI calls this at the end of an utterance."""
        if not self._auto:
            return
        self._timer.stop()
        self._timer.start(max(0, int(delay_ms)))

    def reset(self):
        """Clear the window and the shown pickup (e.g. at the start of a session)."""
        self._timer.stop()
        self._lines = []
        self.updated.emit("")

    def load_last_pickup(self, text):
        """Seed the shown pickup from a restored session (no AI call, no broadcast)."""
        self._lines = []
        self._last_result = str(text or "")
        logger.debug("Last pickup restored: %d chars", len(self._last_result))

    def _maybe_run(self):
        """Start a worker only when auto, there is a window, and nothing is in flight."""
        if not self._auto:
            return
        if not self._lines:
            return
        if self._worker is not None and self._worker.isRunning():
            # A newer window arrived mid-call; refresh once this one finishes.
            self._rerun_pending = True
            return
        self._start_worker(list(self._lines))

    def _start_worker(self, lines: list):
        try:
            self._worker = LastPickupWorker(lines)
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start last-pickup worker: %s", e)
            self._worker = None
            self.error_occurred.emit(f"Failed to start last pickup: {e}")

    def _on_result(self, text: str):
        self._recycle_worker()
        self.updated.emit(text or "")
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
