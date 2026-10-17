"""Filler/acknowledgment detection for the auto-reply path.

An utterance like ``"Okay."`` — or a run of acknowledgments such as
``"Exactly. You nailed it."`` — carries no request to answer, so the auto-reply
skips the AI call entirely instead of spending a reply on it. The recorded
session shows exactly why this matters: a filler triggered a full suggestion
that invented commitments ("let's put a date on it … by Friday").

The check is deliberately conservative. Only a small closed list of pure fillers
counts, and **every** segment of the utterance must be one, so a short-but-real
answer ("Right, but the brief still gets lost") never matches.
"""

import re

# Pure acknowledgments/fillers. Keep this list small and unambiguous: dropping a
# genuine short answer is much worse than letting one filler through.
FILLERS = frozenset({
    "okay", "ok", "mm", "mm-hm", "mmhm", "uh-huh", "uh huh", "yeah", "yes", "yep",
    "right", "sure", "exactly", "you nailed it", "got it", "i see", "hmm",
    "alright", "thanks", "thank you", "great", "nice", "cool", "interesting",
    "correct", "indeed", "agreed", "absolutely", "fair enough", "sounds good",
    "of course", "no problem", "okay then",
})

# Segments are split on sentence punctuation; a run of fillers is still a filler.
_SEGMENT_SPLIT_RE = re.compile(r"[.!?,;:\n]+")
_NON_WORD_RE = re.compile(r"[^a-z0-9' -]+")
_WHITESPACE_RE = re.compile(r"\s+")
_REPEATED_CHAR_RE = re.compile(r"(.)\1{2,}")


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace (``"Okay!!"`` -> ``"okay"``)."""
    cleaned = _NON_WORD_RE.sub(" ", (text or "").lower())
    return _WHITESPACE_RE.sub(" ", cleaned).strip(" -")


def is_filler_segment(segment: str) -> bool:
    """True when one sentence-sized segment is a pure filler."""
    norm = _normalize(segment)
    if not norm:
        return False
    # "Hmmmm" / "ooookay" are the same filler with a stretched syllable.
    return norm in FILLERS or _REPEATED_CHAR_RE.sub(r"\1", norm) in FILLERS


def is_filler(text: str) -> bool:
    """True when the whole utterance is filler — every segment is an acknowledgment."""
    segments = [s for s in _SEGMENT_SPLIT_RE.split((text or "").lower()) if s.strip()]
    if not segments:
        return False
    return all(is_filler_segment(s) for s in segments)
