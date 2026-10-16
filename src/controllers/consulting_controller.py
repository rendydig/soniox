import logging

from PySide6.QtCore import QObject, Qt, Signal

from src.consulting_worker import ConsultingWorker, MODES

logger = logging.getLogger(__name__)


class ConsultingController(QObject):
    """One-shot consulting pipeline: brief -> gap analysis -> execution roadmap.

    Like ``SummarizeController`` there is no timer and no auto mode — each of
    ``draft_brief`` / ``analyze_gaps`` / ``generate_roadmap`` runs on demand (the
    Consulting tab's buttons). ``updated`` carries ``(mode, text)`` so the caller
    knows which of the three sections to replace. One worker runs at a time
    (busy guard), so the three buttons are mutually exclusive while a call is in
    flight. The three texts are kept so a restored session can seed them without
    an AI call (``load_state``).
    """

    # (mode, text)
    updated = Signal(str, str)
    # (mode, status)
    status_changed = Signal(str, str)
    error_occurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._worker_mode = None
        self._old_workers = []
        self._brief = ""
        self._gaps = ""
        self._roadmap = ""

    # --- public API ---------------------------------------------------
    def is_busy(self) -> bool:
        """True while a consulting AI call is in flight."""
        return self._worker is not None and self._worker.isRunning()

    def draft_brief(self, lines, speaker, context=None) -> bool:
        """Draft a client brief from the conversation. Returns True on start."""
        return self._trigger("brief", lines, speaker=speaker, context=context)

    def analyze_gaps(self, lines, reference, speaker, context=None) -> bool:
        """Flag thin/contradictory parts of the conversation against ``reference``."""
        return self._trigger(
            "gaps", lines, reference=reference, speaker=speaker, context=context
        )

    def generate_roadmap(self, lines, reference, gaps, speaker, context=None) -> bool:
        """Turn the confirmed brief + flagged gaps into a prioritized roadmap."""
        return self._trigger(
            "roadmap", lines, reference=reference, gaps=gaps,
            speaker=speaker, context=context,
        )

    def load_state(self, brief, gaps, roadmap):
        """Seed the three texts from a restored session (no AI call, no broadcast)."""
        self._brief = str(brief or "")
        self._gaps = str(gaps or "")
        self._roadmap = str(roadmap or "")
        logger.debug(
            "Consulting restored: brief=%d gaps=%d roadmap=%d chars",
            len(self._brief), len(self._gaps), len(self._roadmap),
        )

    def reset(self):
        """Clear all three sections (e.g. at the start of a new session)."""
        self._brief = ""
        self._gaps = ""
        self._roadmap = ""
        for mode in MODES:
            self.updated.emit(mode, "")

    # --- internals ----------------------------------------------------
    def _trigger(self, mode, lines, reference="", gaps="", speaker=None, context=None) -> bool:
        """Start a call. Returns True when a worker was started.

        Returns False and emits ``no_input`` when there is nothing to work with
        (an empty transcript), and False when a call is already in flight — the
        same "nothing happened" contract the other manual buttons rely on, so
        the caller can show a feedback notice instead of a dead button.
        """
        if not lines:
            self.status_changed.emit(mode, "no_input")
            return False
        if self.is_busy():
            return False
        self._start_worker(mode, lines, reference, gaps, speaker, context)
        return True

    def _start_worker(self, mode, lines, reference, gaps, speaker, context):
        try:
            self._worker = ConsultingWorker(
                mode, lines, reference=reference, gaps=gaps,
                speaker=speaker, context=context,
            )
            self._worker_mode = mode
            self._worker.result.connect(self._on_result, Qt.ConnectionType.QueuedConnection)
            self._worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
            self.status_changed.emit(mode, "started")
            self._worker.start()
        except Exception as e:
            logger.error("Failed to start consulting worker: %s", e)
            self._worker = None
            self._worker_mode = None
            self.error_occurred.emit(f"Failed to start consulting call: {e}")

    def _on_result(self, text: str):
        mode = self._worker_mode or "brief"
        self._recycle_worker()
        self._set_text(mode, text or "")
        self.updated.emit(mode, text or "")
        self.status_changed.emit(mode, "complete")

    def _on_error(self, msg: str):
        mode = self._worker_mode or "brief"
        self._recycle_worker()
        self.error_occurred.emit(msg)
        self.status_changed.emit(mode, "error")

    def _set_text(self, mode, text):
        if mode == "brief":
            self._brief = text
        elif mode == "gaps":
            self._gaps = text
        elif mode == "roadmap":
            self._roadmap = text

    def _recycle_worker(self):
        if self._worker is not None:
            self._worker.wait(1000)
            self._old_workers.append(self._worker)
            self._worker = None
            self._worker_mode = None
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
        still running (mirrors ``TranslationController``/``SummarizeController``).
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
        self._worker_mode = None
        self._old_workers.clear()
