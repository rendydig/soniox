import copy
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from src.config import (
    OBJECTIVE_MAX_HISTORY,
    OBJECTIVE_MAX_ITEMS,
    SESSION_DIR,
    SESSION_MAX_GEMINI,
    SESSION_MAX_SCREENSHOTS,
    SESSION_MAX_TRANSCRIPT_LINES,
    SESSION_WRITE_DEBOUNCE_MS,
)

logger = logging.getLogger(__name__)

# Fields that make up a session (all lists, except the string fields below).
# ``bullet_windows`` is the per-update provenance of ``bullets``: one entry per
# bullet-points update recording the time range it covered and the index range
# of the bullets it appended (or the whole list for a rebuild).
# ``bullet_locks`` is a parallel list[bool] index-aligned with ``bullets``: a
# ``True`` pins that bullet so a Rebuild keeps it verbatim at the top.
# ``objectives`` is the session-level list of what the conversation is working
# towards (see src/objectives.py), ``objective_locks`` is its parallel list[bool]
# (True pins an objective so a prediction can never re-classify away from it) and
# ``objective_history`` is the append-only timeline of committed transitions.
SESSION_FIELDS = (
    "bullets",
    "bullet_windows",
    "bullet_locks",
    "objectives",
    "objective_locks",
    "objective_history",
    "conversation",
    "transcriptions",
    "translations",
    "gemini_results",
    "screenshots",
)

# Session fields stored as plain strings rather than lists.
SESSION_TEXT_FIELDS = ("last_pickup", "summary", "brief", "gaps", "roadmap")

# Session fields stored as JSON objects (dicts) rather than lists.
# ``brief_meta`` carries the Consulting tab's confirmation state
# (``{"confirmed": bool, "confirmed_at": iso}``) alongside the ``brief`` text.
# ``objective_meta`` carries the objective tracker's state
# (``{"active": int|None, "confidence": float, "source": "jev"|"llm",
# "updated_at": iso}`` plus the hysteresis state ``pending``/``streak``).
# ``speaker_locks`` pins parts of the extracted speaker (KYC) profile:
# ``{field: bool}`` for the scalar fields and ``{field: [bool, ...]}`` for the
# list fields, parallel to ``speaker``.
SESSION_OBJECT_FIELDS = ("speaker", "brief_meta", "objective_meta", "speaker_locks")

# Every persisted field, in the order they are created / normalized.
ALL_SESSION_FIELDS = SESSION_FIELDS + SESSION_TEXT_FIELDS + SESSION_OBJECT_FIELDS

# Per-field retention caps, so a long session can't grow without bound.
SESSION_CAPS = {
    "transcriptions": SESSION_MAX_TRANSCRIPT_LINES,
    "translations": SESSION_MAX_TRANSCRIPT_LINES,
    "gemini_results": SESSION_MAX_GEMINI,
    "screenshots": SESSION_MAX_SCREENSHOTS,
    "objectives": OBJECTIVE_MAX_ITEMS,
    "objective_history": OBJECTIVE_MAX_HISTORY,
}

# The extracted speaker (KYC) profile's fields, mirrored from
# ``src/bullet_points_worker.py``. Duplicated deliberately: the session store is
# loaded by tools that must not pull Qt in (`bullet_points_worker` is a QThread),
# and this is the persisted shape of ``speaker_locks``.
_SPEAKER_SCALAR_FIELDS = ("name", "location", "occupation")
_SPEAKER_LIST_FIELDS = ("interests", "goals", "pain_points", "facts")


def _new_session_data():
    now = datetime.now(timezone.utc).isoformat()
    data = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": now,
        "updated_at": now,
    }
    for field in SESSION_FIELDS:
        data[field] = []
    for field in SESSION_TEXT_FIELDS:
        data[field] = ""
    for field in SESSION_OBJECT_FIELDS:
        data[field] = {}
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
    @property
    def path(self):
        """Absolute path of the current-session file (used for diagnostics)."""
        return self._path

    def snapshot(self):
        """Return a shallow copy of the session (lists are owned + replaced)."""
        with self._lock:
            return dict(self._data)

    def update(self, field, value):
        """Replace a field's value (lists/dicts are copied so the store owns them)."""
        if isinstance(value, list):
            value = list(value)
        elif isinstance(value, dict):
            value = dict(value)
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

    def set_bullet_windows(self, windows):
        """Replace the bullet-points windows (own the entries, not the caller's)."""
        self.update("bullet_windows", [dict(w) for w in (windows or []) if isinstance(w, dict)])

    def set_bullet_locks(self, locks):
        """Replace the per-item lock flags (parallel to ``bullets``)."""
        self.update("bullet_locks", [bool(x) for x in (locks or [])])

    def set_speaker(self, profile):
        self.update("speaker", dict(profile or {}))

    def set_speaker_locks(self, locks):
        """Replace the speaker-profile lock flags (parallel to ``speaker``).

        Aligned to the profile's *current* shape, so a stale or short list from a
        caller cannot pin the wrong item (`speaker` is written first by the app).
        """
        locks = locks if isinstance(locks, dict) else {}
        with self._lock:
            speaker = self._data.get("speaker")
        speaker = speaker if isinstance(speaker, dict) else {}
        aligned = {}
        for field in _SPEAKER_SCALAR_FIELDS:
            aligned[field] = bool(locks.get(field))
        for field in _SPEAKER_LIST_FIELDS:
            values = speaker.get(field)
            values = values if isinstance(values, list) else []
            flags = locks.get(field)
            flags = list(flags) if isinstance(flags, list) else []
            aligned[field] = [bool(flags[i]) if i < len(flags) else False
                              for i in range(len(values))]
        self.update("speaker_locks", aligned)

    def set_objectives(self, objectives):
        """Replace the session objectives, keeping at most ``OBJECTIVE_MAX_ITEMS``.

        The newest entries win, matching the ``append`` discipline; a drop is
        logged rather than silent (the pane shows the list it sent back).
        """
        items = [str(x) for x in (objectives or []) if str(x).strip()]
        cap = SESSION_CAPS["objectives"]
        if len(items) > cap:
            logger.warning("Objective list over cap (%d > %d); dropping the oldest",
                           len(items), cap)
            items = items[-cap:]
        self.update("objectives", items)

    def set_objective_locks(self, locks):
        """Replace the per-objective lock flags (parallel to ``objectives``)."""
        self.update("objective_locks", [bool(x) for x in (locks or [])])

    def set_objective_meta(self, meta):
        """Replace the objective tracker state (which objective is active, etc.)."""
        self.update("objective_meta", dict(meta or {}))

    def clear_fields(self, fields):
        """Empty the given fields (used by New Session / reset)."""
        with self._lock:
            for field in fields:
                if field in SESSION_OBJECT_FIELDS:
                    self._data[field] = {}
                elif field in SESSION_TEXT_FIELDS:
                    self._data[field] = ""
                else:
                    self._data[field] = []
            self._data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._dirty.set()

    def new_session(self):
        """Archive the current session (if non-empty) and start a fresh one."""
        with self._lock:
            has_content = any(self._data.get(f) for f in ALL_SESSION_FIELDS)
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
        for field in SESSION_TEXT_FIELDS:
            if not isinstance(base.get(field), str):
                base[field] = ""
        for field in SESSION_OBJECT_FIELDS:
            if not isinstance(base.get(field), dict):
                base[field] = {}
        # ``objectives`` is capped like any other list, and ``objective_locks`` is
        # parallel to it — an older session file (or a hand-edited one) may be
        # short, absent or longer, so pad / trim it to match. ``_normalize`` keeps
        # only keys in ``_new_session_data``, so a field missing from
        # SESSION_FIELDS/SESSION_OBJECT_FIELDS is silently dropped here.
        cap = SESSION_CAPS["objectives"]
        if len(base["objectives"]) > cap:
            base["objectives"] = base["objectives"][-cap:]
        count = len(base["objectives"])
        locks = [bool(x) for x in base["objective_locks"]]
        base["objective_locks"] = (locks + [False] * count)[:count]
        # ``speaker_locks`` is parallel to the extracted speaker profile: align the
        # list-field flags to the profile's shape (an older session file, or a
        # hand-edited one, may be short/absent/long) and coerce the scalars.
        speaker = base.get("speaker") if isinstance(base.get("speaker"), dict) else {}
        raw_locks = base.get("speaker_locks") if isinstance(base.get("speaker_locks"), dict) else {}
        aligned = {}
        for field in _SPEAKER_SCALAR_FIELDS:
            aligned[field] = bool(raw_locks.get(field))
        for field in _SPEAKER_LIST_FIELDS:
            values = speaker.get(field)
            values = values if isinstance(values, list) else []
            flags = raw_locks.get(field)
            flags = list(flags) if isinstance(flags, list) else []
            aligned[field] = [bool(flags[i]) if i < len(flags) else False
                              for i in range(len(values))]
        base["speaker_locks"] = aligned
        return base
