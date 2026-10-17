"""Purpose store: the in-memory source of truth for auto-reply purposes.

Mirrors ``SessionStore``: reads always come from memory; a daemon writer thread
JSON-dumps a snapshot to ``purposes.json`` on a debounce via a temp file +
``os.replace``. ``register()`` is called from ``GeminiAutoReplyWorker`` (a
QThread), so the in-memory dict is guarded by a lock and ``purposes_changed`` is
delivered to the Qt main thread through the normal queued connection.

Load order: seed ``BUILTIN_PURPOSES`` (the immutable seed), then overlay
``purposes.json`` — which now carries **only** non-built-in (user / AI-learned)
entries, wrapped as ``{"schema_version": 2, "overrides": {...}, "purposes": {...}}``.
A stale on-disk copy of a built-in (the old whole-dict dump) is **ignored**, so the
seed is always authoritative. ``overrides`` is reserved for deliberate built-in
edits (there is no UI for them yet) and is empty today. The legacy flat
``{key: purpose}`` shape still loads.
"""

import copy
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from src.config import (
    MAX_DYNAMIC_PURPOSES,
    PURPOSES_PATH,
    PURPOSES_WRITE_DEBOUNCE_MS,
)
from src.purposes import (
    BUILTIN_PURPOSES,
    DEFAULT_PURPOSE,
    DEFAULT_ROLE_STYLE,
    purpose_roles,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2


def slugify(label: str) -> str:
    """Turn a label into a stable, filesystem-safe key (``Crisis Mediation`` -> ``crisis_mediation``)."""
    slug = re.sub(r"[^a-z0-9]+", "_", (label or "").strip().lower()).strip("_")
    return slug or "purpose"


class PurposeStore(QObject):
    """In-memory purpose registry persisted to disk by a background thread."""

    # Emits the key of the new/changed purpose (queued to the Qt main thread).
    purposes_changed = Signal(str)

    def __init__(self, path=None, parent=None):
        super().__init__(parent)
        self._path = path or PURPOSES_PATH
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._dirty = threading.Event()
        self._stop = threading.Event()
        # Deliberate built-in edits, loaded from the file's ``overrides`` block.
        # Empty today (no UI edits built-ins) but preserved across writes.
        self._overrides = {}
        self._purposes = self._load()
        self._thread = threading.Thread(
            target=self._writer_loop, name="purpose-writer", daemon=True
        )
        self._thread.start()

    # --- read (always memory) ----------------------------------------
    def get(self, key) -> dict:
        with self._lock:
            purpose = self._purposes.get(key)
        if purpose is None:
            # Unknown key (e.g. a purpose removed from disk): fall back to default.
            purpose = self._purposes.get(DEFAULT_PURPOSE) or BUILTIN_PURPOSES[DEFAULT_PURPOSE]
        return copy.deepcopy(purpose)

    def all(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._purposes)

    def keys(self) -> list:
        with self._lock:
            return list(self._purposes.keys())

    def labels(self) -> list:
        """Return ``[(key, label), ...]`` in insertion order (built-ins first)."""
        with self._lock:
            return [(key, p.get("label", key)) for key, p in self._purposes.items()]

    def roles(self, key) -> dict:
        return purpose_roles(self.get(key))

    def exists(self, key) -> bool:
        with self._lock:
            return key in self._purposes

    # --- write --------------------------------------------------------
    def register(self, purpose: dict) -> str:
        """Add an AI-learned purpose to memory immediately; persist asynchronously.

        Returns the assigned key. Metadata (``dynamic``, ``created_at``,
        ``source``, ``confidence_at_creation``, ``schema_version``) is attached
        and ``MAX_DYNAMIC_PURPOSES`` is enforced by pruning the oldest dynamic
        entries.
        """
        purpose = dict(purpose or {})
        label = (purpose.get("label") or "Auto Purpose").strip()
        base = slugify(purpose.get("key") or label)
        with self._lock:
            key = self._unique_key(base)
            self._purposes[key] = self._normalize_dynamic(key, label, purpose)
            self._prune_dynamic()
        self._dirty.set()
        self.purposes_changed.emit(key)
        logger.info("Registered new purpose %r (%s)", key, label)
        return key

    def flush(self):
        """Write the store synchronously (e.g. on close)."""
        self._write()

    def close(self):
        """Stop the writer thread after a final flush."""
        self._stop.set()
        self._dirty.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self.flush()

    # --- internals ----------------------------------------------------
    def _load(self) -> dict:
        purposes = {k: copy.deepcopy(v) for k, v in BUILTIN_PURPOSES.items()}
        self._overrides = {}
        disk = self._read_file()
        if not isinstance(disk, dict):
            return purposes
        # Schema 2 wraps the payload; the legacy shape is a bare {key: purpose} map.
        wrapped = isinstance(disk.get("purposes"), dict)
        entries = disk["purposes"] if wrapped else disk
        if wrapped and isinstance(disk.get("overrides"), dict):
            self._overrides = {
                key: value for key, value in disk["overrides"].items()
                if isinstance(key, str) and isinstance(value, dict)
                and key in BUILTIN_PURPOSES
            }
        for key, value in entries.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            if key in BUILTIN_PURPOSES:
                # Built-ins come from the seed, always: a stale on-disk copy from
                # the old whole-dict dump must never shadow it.
                if value != BUILTIN_PURPOSES[key]:
                    logger.warning(
                        "Ignoring stale built-in copy of %r from purposes.json", key
                    )
                continue
            purposes[key] = value
        # A deliberate built-in edit (reserved; unused today) merges onto the seed.
        for key, value in self._overrides.items():
            merged = dict(purposes[key])
            merged.update(value)
            purposes[key] = merged
        return purposes

    def _unique_key(self, base: str) -> str:
        if base not in self._purposes:
            return base
        n = 2
        while f"{base}-{n}" in self._purposes:
            n += 1
        return f"{base}-{n}"

    def _normalize_dynamic(self, key: str, label: str, purpose: dict) -> dict:
        """Convert a synthesis ``new_category`` payload into a stored purpose."""
        role_key = slugify(purpose.get("role_key") or label)
        persona = purpose.get("persona") or f"You are the Host: {label}."
        objective = purpose.get("objective")
        if isinstance(objective, str):
            objective = [objective]
        objective = list(objective or [])
        speech_act = (purpose.get("speech_act") or "").strip()
        criteria = (purpose.get("criteria") or "").strip()
        confidence = purpose.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        style = purpose.get("style")
        style = (
            {k: v for k, v in style.items() if v not in (None, "")}
            if isinstance(style, dict) else {}
        )
        display_label = label if label.endswith("(auto)") else f"{label} (auto)"
        entry = {
            "label": display_label,
            "dynamic": True,
            "source": "ai",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": SCHEMA_VERSION,
            "default_role": role_key,
            "roles": {
                role_key: {
                    "label": label,
                    "persona": persona,
                    "objective": objective,
                    # Style is optional: an AI-synthesized role carries it when the
                    # synthesis returned one, otherwise it inherits the
                    # persona-neutral default (see src/purposes.py).
                    "style": {**DEFAULT_ROLE_STYLE, **style},
                    "counterpart": purpose.get("counterpart") or "Speaker",
                }
            },
            "speech_act_policy": [speech_act] if speech_act else [],
            "objective_checklist": [criteria] if criteria else [],
            "extra_format": [],
            "include_pronunciation_default": False,
        }
        if confidence is not None:
            entry["confidence_at_creation"] = confidence
        return entry

    def _prune_dynamic(self) -> None:
        """Drop the oldest dynamic entries once ``MAX_DYNAMIC_PURPOSES`` is exceeded."""
        dynamic = [
            (key, p.get("created_at", ""))
            for key, p in self._purposes.items()
            if p.get("dynamic")
        ]
        if len(dynamic) <= MAX_DYNAMIC_PURPOSES:
            return
        dynamic.sort(key=lambda item: item[1])
        for key, _ in dynamic[: len(dynamic) - MAX_DYNAMIC_PURPOSES]:
            self._purposes.pop(key, None)
            logger.info("Pruned oldest dynamic purpose %r", key)

    def _read_file(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def _writer_loop(self):
        while not self._stop.is_set():
            if not self._dirty.wait(timeout=0.5):
                continue
            if self._stop.is_set():
                break
            # Debounce: coalesce a burst of updates into one write.
            time.sleep(PURPOSES_WRITE_DEBOUNCE_MS / 1000.0)
            if self._stop.is_set():
                break
            self._write()

    def _write(self):
        with self._lock:
            self._dirty.clear()
            # Shallow copies: values are replaced, never mutated. Built-ins are the
            # seed and are never written back, so the file only carries state the
            # seed cannot reconstruct (user edits and AI-learned purposes).
            entries = {
                key: value for key, value in self._purposes.items()
                if key not in BUILTIN_PURPOSES
            }
            overrides = dict(self._overrides)
        data = {
            "schema_version": SCHEMA_VERSION,
            "overrides": overrides,
            "purposes": entries,
        }
        try:
            payload = json.dumps(data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as e:
            logger.error("Failed to serialize purposes: %s", e)
            return
        try:
            with self._write_lock:
                directory = os.path.dirname(self._path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, self._path)
        except OSError as e:
            logger.error("Failed to write purposes: %s", e)
