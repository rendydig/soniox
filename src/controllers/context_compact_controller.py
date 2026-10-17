import logging

from PySide6.QtCore import QObject, Qt, Signal

from src.config import CONTEXT_COMPACT_MIN_CHARS
from src.context_compact_worker import ContextCompactWorker

logger = logging.getLogger(__name__)


class ContextCompactController(QObject):
    """One-shot "Compact" for a Context-pane role.

    Modelled on ``SummarizeController``: no timer, no auto mode, one call per
    press. The pane sends ``compact_context`` with the role (and the real file's
    path, so the write can be rejected if the selection moved on while the call
    was in flight); the finished text is emitted on ``compacted`` and the app
    hands it to the Node context store, which owns the writing.
    """

    compacted = Signal(str, str, str)   # role, source_path, text
    status_changed = Signal(str, str)   # role, status
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._old_workers = []
        self._role = ""
        self._path = ""

    def is_busy(self) -> bool:
        """True while a compaction call is in flight."""
        return self._worker is not None and self._worker.isRunning()

    def trigger_now(self, role, text, source_path: str = "") -> bool:
        """Compact `text` for `role`. Returns True when a worker was started.

        Returns False (with a ``status_changed`` notice) when there is nothing
        worth a call — no text at all, or a file already shorter than
        ``CONTEXT_COMPACT_MIN_CHARS`` — and when a call is already in flight.
        """
        role = str(role or "")
        body = str(text or "").strip()
        if not role:
            self.status_changed.emit("", "invalid")
            return False
        if not body:
            self.status_changed.emit(role, "no_input")
            return False
        if len(body) < CONTEXT_COMPACT_MIN_CHARS:
            self.status_changed.emit(role, "too_short")
            return False
        if self.is_busy():
            self.status_changed.emit(role, "busy")
            return False
        self._role = role
        self._path = str(source_path or "")
        self._start_worker(role, body, self._path)
        return True

    def _start_worker(self, role, text, source_path):
        try:
            self._worker = ContextCompactWorker(role, text, source_path)
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit(role, "started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start context-compact worker: %s", e)
            self._worker = None
            self.error_occurred.emit(f"Failed to compact the context: {e}")

    def _on_result(self, role: str, source_path: str, text: str):
        self._recycle_worker()
        self.compacted.emit(role, source_path, text)
        self.status_changed.emit(role, "complete")

    def _on_error(self, role: str, msg: str):
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit(role, "error")

    def reset(self):
        """Forget the in-flight role (a new session)."""
        self._role = ""
        self._path = ""

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
        """Stop any running workers (terminate as a last resort).

        The worker may be blocked in a synchronous HTTP call, so a plain wait can
        time out; terminate as a last resort so the QThread isn't destroyed while
        still running (mirrors ``SummarizeController``).
        """
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
        self._old_workers = []
