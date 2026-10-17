"""Long-run health/diagnostics for the main window (the ``HealthMixin``).

This cluster was split out of ``src/ui.py`` into its own mixin: it samples
memory, thread count, editor lines and each pane's webview JS heap and appends
one line per sample to ``logs/health.log``, so growth (or a crash) is visible
over a multi-hour session.

A mixin — not a free-standing helper — because the methods must stay attributes
of ``MainWindow``: the ``_tmp_*`` checks reach ``MainWindow`` members (and
monkeypatch ``src.ui`` globals) rather than importing this module, so inheriting
the mixin keeps ``ui.MainWindow.<method>`` and every instance call working with
no edit at any call site. ``HealthMixin`` defines no ``__init__``/``__new__``, so
the Qt base class keeps owning construction.
"""

import logging
import os
import threading
from datetime import datetime

from src.config import MAX_TRANSCRIPTION_LINES

logger = logging.getLogger(__name__)

# Long-run diagnostics: a one-line memory/thread/editor sample appended here
# every HEALTH_LOG_INTERVAL_MS so growth (or a crash) is visible over hours.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_REPO_ROOT, "logs")
HEALTH_LOG = os.path.join(_LOGS_DIR, "health.log")
HEALTH_LOG_INTERVAL_MS = 30000


class HealthMixin:
    """The long-run health/diagnostics methods inherited by ``MainWindow``."""

    def _update_memory_usage(self):
        """Update memory usage indicator."""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            mem_mb = mem_info.rss / 1024 / 1024
            
            trans_lines = self.transcription_editor.document().blockCount()
            
            self.memory_label.setText(f"Memory: {mem_mb:.1f} MB | Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except ImportError:
            trans_lines = self.transcription_editor.document().blockCount()
            self.memory_label.setText(f"Lines: {trans_lines}/{MAX_TRANSCRIPTION_LINES}")
        except Exception:
            pass

    def _on_render_process_terminated(self, status, exit_code):
        """A pane's Chromium renderer died (would otherwise show a blank pane)."""
        logger.error("Webview renderer terminated: status=%s exit_code=%s", status, exit_code)

    def _append_health(self, fields: str):
        """Append one health sample line to logs/health.log (best effort)."""
        line = "%s %s" % (datetime.now().isoformat(timespec="seconds"), fields)
        try:
            os.makedirs(_LOGS_DIR, exist_ok=True)
            with open(HEALTH_LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
        logger.info("health: %s", line)

    def _log_health(self):
        """Sample process/editor health and the webview JS heaps."""
        try:
            import psutil
            rss_mb = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except Exception:
            rss_mb = -1.0
        try:
            blocks = self.transcription_editor.document().blockCount()
        except Exception:
            blocks = -1
        try:
            session_kb = os.path.getsize(self.session_store.path) / 1024
        except OSError:
            session_kb = -1.0
        self._append_health(
            "rss_mb=%.1f threads=%d editor_blocks=%d session_kb=%.1f"
            % (rss_mb, threading.active_count(), blocks, session_kb)
        )
        # JS heap is only available asynchronously; each pane logs its own line.
        for name, pane in (("gemini", self.gemini_window),
                           ("live", self.live_window),
                           ("bullets", self.bullet_points_window),
                           ("context", self.context_window)):
            view = getattr(pane, "webview", None)
            if view is None:
                continue
            view.page().runJavaScript(
                "(window.performance && performance.memory)"
                " ? performance.memory.usedJSHeapSize : 0",
                lambda value, _name=name: self._on_webview_heap(_name, value),
            )

    def _on_webview_heap(self, name, value):
        try:
            heap_mb = int(value) / 1024 / 1024
        except (TypeError, ValueError):
            return
        self._append_health("webview_%s_heap_mb=%.1f" % (name, heap_mb))
