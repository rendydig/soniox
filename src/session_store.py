import copy
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from src.config import (
    SESSION_DIR,
    SESSION_MAX_GEMINI,
    SESSION_MAX_SCREENSHOTS,
    SESSION_MAX_TRANSCRIPT_LINES,
    SESSION_WRITE_DEBOUNCE_MS,
)

logger = logging.getLogger(__name__)

# Fields that make up a session (all lists).
SESSION_FIELDS = (
    "bullets",
    "conversation",
    "transcriptions",
    "translations",
    "gemini_results",
    "screenshots",
)

# Per-field retention caps, so a long session can't grow without bound.
SESSION_CAPS = {
    "transcriptions": SESSION_MAX_TRANSCRIPT_LINES,
    "translations": SESSION_MAX_TRANSCRIPT_LINES,
    "gemini_results": SESSION_MAX_GEMINI,
    "screenshots": SESSION_MAX_SCREENSHOTS,
}


def _new_session_data():
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": now,
        "updated_at": now,
    }
    for field in SESSION_FIELDS:
        data[field] = []
    return data


class SessionStore:
    """In-memory session state persisted to disk by a background thread.

    The Qt main thread only mutates the in-memory dict (replacing list values,
    never mutating them in place); a daemon writer thread JSON-dumps snapshots to
    ``SESSION_DIR/current.json`` on a debounce, so file I/O never blocks the UI.
    """

    def __init__(self, directory=None):
        self._dir = directory or SESSION_DIR
        self._path = os.path.join(self._dir, "current.json")
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._data = self._normalize(self._read_file())
        self._thread = threading.Thread(
            target=self._writer_loop, name="session-writer", daemon=True
        )
        self._thread.start()

    # --- public API ---------------------------------------------------
    def snapshot(self):
        """Return a shallow copy of the session (lists are owned + replaced)."""
        with self._lock:
            return dict(self._data)

    def update(self, field, value):
        """Replace a field's value (lists are copied so the store owns them)."""
        if isinstance(value, list):
            value = list(value)
        with self._lock:
            self._data[field] = value
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._dirty.set()

    def append(self, field, item, cap=None):
        """Append an item, trimming the field to ``cap`` (oldest dropped)."""
        if cap is None:
            cap = SESSION_CAPS.get(field)
        with self._lock:
            items = list(self._data.get(field) or [])
            items.append(item)
            if cap is not None and len(items) > cap:
                items = items[-cap:]
            self._data[field] = items
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._dirty.set()

    def set_bullets(self, bullets):
        self.update("bullets", list(bullets or []))

    def clear_fields(self, fields):
        """Empty the given fields (used by New Session / reset)."""
        with self._lock:
            for field in fields:
                self._data[field] = []
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._dirty.set()

    def new_session(self):
        """Archive the current session (if non-empty) and start a fresh one."""
        with self._lock:
            has_content = any(self._data.get(f) for f in SESSION_FIELDS)
            old = copy.deepcopy(self._data) if has_content else None
        archived = self._archive(old) if old is not None else None
        with self._lock:
            self._data = _new_session_data()
        self.flush()
        logger.info("New session started (archived=%s)", archived)
        return archived

    def flush(self):
        """Write the session synchronously (e.g. on close)."""
        self._write()

    def close(self):
        """Stop the writer thread after a final flush."""
        self._stop.set()
        self._dirty.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self.flush()

    # --- internals ----------------------------------------------------
    def _read_file(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _archive(self, data):
        try:
            os.makedirs(self._dir, exist_ok=True)
            path = os.path.join(self._dir, f"{data.get('id', 'session')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            return path
        except OSError as e:
            logger.error("Failed to archive session: %s", e)
            return None

    def _writer_loop(self):
        while not self._stop.is_set():
            if not self._dirty.wait(timeout=0.5):
                continue
            if self._stop.is_set():
                break
            # Debounce: coalesce a burst of updates into one write.
            time.sleep(SESSION_WRITE_DEBOUNCE_MS / 1000.0)
            if self._stop.is_set():
                break
            self._write()

    def _write(self):
        with self._lock:
            self._dirty.clear()
            data = dict(self._data)  # shallow: list refs are owned + replaced
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.error("Failed to serialize session: %s", e)
            return
        try:
            with self._write_lock:
                os.makedirs(self._dir, exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, self._path)
        except OSError as e:
            logger.error("Failed to write session: %s", e)

    @staticmethod
    def _normalize(data):
        base = _new_session_data()
        if isinstance(data, dict):
            base.update({k: v for k, v in data.items() if k in base})
        for field in SESSION_FIELDS:
            if not isinstance(base.get(field), list):
                base[field] = []
        return base
