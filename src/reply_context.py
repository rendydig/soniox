"""Session digest for the auto-reply prompt.

The app already computes a lot of session state — the rolling bullet list, the
per-item locks, the extracted KYC speaker profile, the confirmed consulting
brief and its own prior suggestions — but the reply prompt used to see none of
it. This module turns that state into one small, capped dict the prompt can
carry as a ``Context digest:`` section (``gemini_worker._digest_block``).

Pure and dependency-free on purpose (same style as ``src/filler_filter.py`` and
``src/speech_acts.py``): no Qt, no network, no disk, so the digest is cheap to
rebuild after every state change and trivial to test offline.

``build_digest`` returns ``{}`` when there is nothing to show, so the caller can
skip the whole section instead of rendering an empty heading.
"""

from src.config import (
    AUTO_REPLY_MAX_BRIEF_CHARS,
    AUTO_REPLY_MAX_BULLETS,
    AUTO_REPLY_MAX_BULLET_CHARS,
    AUTO_REPLY_MAX_PRIOR_SUGGESTIONS,
    AUTO_REPLY_MAX_PROFILE_ITEMS,
)

# The KYC profile's scalar identity fields, in display order. ``location`` is
# deliberately left out: it is rarely relevant to what the Host should say.
_PROFILE_TEXT_FIELDS = ("name", "occupation")

# The KYC profile's list fields, in display order, with their prompt labels.
_PROFILE_LIST_FIELDS = (
    ("goals", "Goals"),
    ("pain_points", "Pain points"),
    ("facts", "Facts"),
)


def _truncate(text, limit: int) -> str:
    """Collapse whitespace and cut ``text`` to ``limit`` characters."""
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 1, 0)].rstrip() + "…"


def _clean_list(values, limit: int) -> list:
    """Non-empty, whitespace-collapsed, truncated strings (at most ``limit``)."""
    out = []
    for value in values if isinstance(values, (list, tuple)) else []:
        text = _truncate(value, AUTO_REPLY_MAX_BULLET_CHARS)
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _split_bullets(bullets, locks) -> tuple:
    """Pair bullets with their lock flags, returning ``(locked, rolling)``.

    ``locks`` is a parallel list (``bullet_locks``) that may be shorter — a
    missing flag means "not locked". Locked bullets are split out so the prompt
    can mark them; the rolling list keeps the most recent ``AUTO_REPLY_MAX_BULLETS``
    *after* the split, so locked points never push out fresh ones.
    """
    bullets = bullets if isinstance(bullets, (list, tuple)) else []
    locks = locks if isinstance(locks, (list, tuple)) else []
    locked, rolling = [], []
    for index, bullet in enumerate(bullets):
        text = _truncate(bullet, AUTO_REPLY_MAX_BULLET_CHARS)
        if not text:
            continue
        flag = bool(locks[index]) if index < len(locks) else False
        (locked if flag else rolling).append(text)
    return locked, rolling[-AUTO_REPLY_MAX_BULLETS:]


def _profile(profile: dict) -> dict:
    """Keep the KYC fields the reply can actually use, each capped and trimmed."""
    if not isinstance(profile, dict):
        return {}
    out = {}
    for field in _PROFILE_TEXT_FIELDS:
        text = _truncate(profile.get(field), AUTO_REPLY_MAX_BULLET_CHARS)
        if text:
            out[field] = text
    for field, _label in _PROFILE_LIST_FIELDS:
        items = _clean_list(profile.get(field), AUTO_REPLY_MAX_PROFILE_ITEMS)
        if items:
            out[field] = items
    return out


def _prior_suggestions(conversation, limit: int) -> list:
    """The last ``limit`` non-empty suggestions the app already produced.

    Read straight off the conversation turns (the controller records each
    finished reply as the ``suggestion`` of the speaker turn it answered), so
    the model can avoid repeating what the Host was already told to say. Only
    the tail is kept — a long session's earliest suggestions are stale anyway.
    """
    out = []
    for turn in conversation if isinstance(conversation, (list, tuple)) else []:
        if not isinstance(turn, dict):
            continue
        text = _truncate(turn.get("suggestion"), AUTO_REPLY_MAX_BULLET_CHARS)
        if text:
            out.append(text)
    return out[-limit:]


def build_digest(bullets, locks, speaker_profile, brief, conversation) -> dict:
    """Build the auto-reply session digest.

    Args:
        bullets: the rolling bullet list (``bullets`` session field).
        locks: the parallel lock flags (``bullet_locks``); may be short/absent.
        speaker_profile: the extracted KYC profile (``speaker`` session field).
        brief: the *confirmed* client brief, or ``""`` when none is locked in.
        conversation: the turn list with ``text``/``role``/``suggestion``.

    Returns:
        ``{"bullets": [...], "locked": [...], "speaker": {...}, "brief": str,
        "prior_suggestions": [...]}`` — or ``{}`` when every part is empty, so
        the caller omits the section entirely.

    The digest is deliberately flat text: no ids, no timestamps, no confidence
    values, because the prompt only needs to know *what* was established, not
    where it came from.
    """
    locked, rolling = _split_bullets(bullets, locks)
    profile = _profile(speaker_profile)
    brief_text = _truncate(brief, AUTO_REPLY_MAX_BRIEF_CHARS)
    suggestions = _prior_suggestions(conversation, AUTO_REPLY_MAX_PRIOR_SUGGESTIONS)

    if not (locked or rolling or profile or brief_text or suggestions):
        return {}
    return {
        "bullets": rolling,
        "locked": locked,
        "speaker": profile,
        "brief": brief_text,
        "prior_suggestions": suggestions,
    }
