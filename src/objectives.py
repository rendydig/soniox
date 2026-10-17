"""Session objectives: pure helpers for the tracked objective list.

An *objective* is one session-level item of what the conversation is working
towards (``"Confirm the rollout timeline"``). The list is owned by the session
store and edited in the Objectives tab; a tracker predicts which one is active
as the conversation moves on.

Two rules live here, in pure form (no Qt, no network, no disk), so they can be
tested offline and reused by both the tracker and the reply prompt:

* ``resolve_active`` — a **locked** objective always wins over the prediction, so
  a user pin cannot be re-classified away; otherwise the tracker's ``active``
  index is used.
* ``observe`` — a transition is only committed after ``OBJECTIVE_MIN_STREAK``
  consecutive agreeing predictions (hysteresis). Without it the tracker
  flip-flops on adjacent utterances and the history timeline becomes noise.
"""

import re
from datetime import datetime, timezone

# Mirrors ``purpose_store.slugify`` so a key built here matches the one the
# purpose registry would build for the same label.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def objective_key(text: str) -> str:
    """Stable key for an objective label (``Confirm the timeline`` -> ``confirm_the_timeline``)."""
    slug = _SLUG_RE.sub("_", str(text or "").strip().lower()).strip("_")
    return slug or "objective"


def align_locks(objectives: list, locks: list) -> list:
    """Pad / trim ``locks`` so it is index-aligned with ``objectives``."""
    objectives = objectives if isinstance(objectives, (list, tuple)) else []
    locks = locks if isinstance(locks, (list, tuple)) else []
    return ([bool(x) for x in locks] + [False] * len(objectives))[:len(objectives)]


def locked_index(objectives: list, locks: list) -> int:
    """Index of the first locked objective, or ``None`` when nothing is locked."""
    if not isinstance(objectives, (list, tuple)):
        return None
    for index, locked in enumerate(align_locks(objectives, locks)):
        if locked:
            return index
    return None


def resolve_active(objectives: list, locks: list, meta: dict) -> dict:
    """Resolve the objective the reply should serve.

    Returns ``{"index", "text", "locked", "confidence", "source"}`` — or ``{}``
    when there is nothing to focus on. Precedence: a locked objective beats the
    prediction (``source`` becomes ``"lock"``); otherwise the tracker's
    ``active`` index is used when it is still in range.
    """
    objectives = list(objectives or [])
    meta = meta if isinstance(meta, dict) else {}
    index = locked_index(objectives, locks)
    if index is not None:
        return {
            "index": index,
            "text": objectives[index],
            "locked": True,
            "confidence": 1.0,
            "source": "lock",
        }
    active = meta.get("active")
    if not isinstance(active, int) or isinstance(active, bool) or not 0 <= active < len(objectives):
        return {}
    return {
        "index": active,
        "text": objectives[active],
        "locked": False,
        "confidence": _as_float(meta.get("confidence")),
        "source": str(meta.get("source") or ""),
    }


def observe(objectives: list, locks: list, meta: dict, index, confidence, source: str,
            min_streak: int) -> tuple:
    """Fold one prediction into the tracker meta.

    Args:
        objectives: the current objective list.
        locks: the parallel lock flags.
        meta: the previous tracker state (``{}`` on a cold start).
        index: the predicted objective index, or ``None``/out-of-range for "no
            idea" (which resets the streak instead of counting as agreement).
        confidence: the predictor's confidence in ``index``.
        source: ``"jev"`` or ``"llm"`` — recorded on a committed transition.
        min_streak: consecutive agreeing predictions needed to commit.

    Returns:
        ``(new_meta, committed)``. ``committed`` is True only when the *active*
        objective changed, which is what appends to the history timeline.

    A locked objective short-circuits everything: the meta is pinned to it, so
    an unlocked prediction can never move the tracker away from a user lock.
    """
    meta = dict(meta or {})
    objectives = list(objectives or [])
    streak_needed = max(int(min_streak or 1), 1)

    locked = locked_index(objectives, locks)
    if locked is not None:
        # A user lock is absolute: it cannot be re-classified away, and an
        # agreeing prediction has nothing to commit.
        if meta.get("active") == locked:
            meta["pending"] = None
            meta["streak"] = 0
            return meta, False
        meta.update({
            "active": locked,
            "confidence": 1.0,
            "source": "lock",
            "pending": None,
            "streak": 0,
            "updated_at": _now(),
        })
        return meta, True

    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(objectives):
        meta["pending"] = None
        meta["streak"] = 0
        return meta, False

    if index == meta.get("active"):
        # Agrees with what is already active: nothing to commit, and the streak
        # resets because the pending candidate (if any) is not the active one.
        meta["pending"] = None
        meta["streak"] = 0
        return meta, False

    streak = int(meta.get("streak") or 0) + 1 if meta.get("pending") == index else 1
    meta["pending"] = index
    meta["streak"] = streak
    if streak < streak_needed:
        return meta, False

    meta.update({
        "active": index,
        "confidence": _as_float(confidence),
        "source": str(source or ""),
        "pending": None,
        "streak": 0,
        "updated_at": _now(),
    })
    return meta, True


def history_entry(objectives: list, index: int, confidence, source: str) -> dict:
    """One history-timeline entry for a committed transition."""
    objectives = list(objectives or [])
    text = objectives[index] if 0 <= index < len(objectives) else ""
    return {
        "ts": _now(),
        "index": index,
        "text": text,
        "confidence": _as_float(confidence),
        "source": str(source or ""),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
