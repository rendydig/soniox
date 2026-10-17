import logging

from PySide6.QtCore import QObject, Qt, Signal

from src.summarize_worker import SummarizeWorker

logger = logging.getLogger(__name__)


class SummarizeController(QObject):
    """One-shot whole-session summary.

    Unlike ``BulletPointsController`` / ``LastPickupController`` there is no timer
    and no auto mode: ``trigger_now`` runs on demand (the Summary tab's button)
    and ``updated`` carries the finished markdown, which replaces any previous
    one. The current text is kept so a restored session can seed it without an
    AI call (``load_summary``).
    """

    updated = Signal(str)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._old_workers = []
        self._summary = ""
        # Host/Speaker reference context mirrored by MainWindow; interpretation
        # only, never added to the summary as a finding.
        self._context = {}

    def set_context(self, contents):
        """Mirror the Host/Speaker reference context pushed by the web service."""
        self._context = contents if isinstance(contents, dict) else {}

    def is_busy(self) -> bool:
        """True while a summary AI call is in flight."""
        return self._worker is not None and self._worker.isRunning()

    def trigger_now(self, lines, bullets, speaker) -> bool:
        """Start a summary call. Returns True when a worker was started.

        Returns False and emits ``no_input`` when there is nothing to summarize
        (an empty transcript), and False when a call is already in flight — the
        same "nothing happened" contract the bullet-points button relies on, so
        the caller can show a feedback notice instead of a dead button.
        """
        if not lines:
            self.status_changed.emit("no_input")
            return False
        if self.is_busy():
            return False
        self._start_worker(list(lines), list(bullets or []), dict(speaker or {}))
        return True

    def reset(self):
        """Clear the shown summary (e.g. at the start of a new session)."""
        self._summary = ""
        self.updated.emit("")

    def load_summary(self, text):
        """Seed the shown summary from a restored session (no AI call, no broadcast)."""
        self._summary = str(text or "")
        logger.debug("Summary restored: %d chars", len(self._summary))

    def _start_worker(self, lines, bullets, speaker):
        try:
            self._worker = SummarizeWorker(lines, bullets, speaker, context=self._context)
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit("started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start summarize worker: %s", e)
            self._worker = None
            self.error_occurred.emit(f"Failed to start summary: {e}")

    def _on_result(self, text: str):
        self._recycle_worker()
        self._summary = text or ""
        self.updated.emit(self._summary)
        self.status_changed.emit("complete")

    def _on_error(self, msg: str):
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit("error")

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
        still running (mirrors ``TranslationController``).
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
        self._old_workers.clear()
