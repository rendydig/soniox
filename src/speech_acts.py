"""Searle's speech acts, used as JEV ``choice`` criteria for the auto-reply.

The JEV decision layer picks one of these for each Speaker utterance so the LLM
knows *what kind* of move to make (state a fact, ask a question, promise, ...),
rather than always producing the same flavour of reply.
"""

SPEECH_ACTS = {
    "assertive": {
        "label": "Assertive",
        "criteria": "States a fact, report, confirmation, or belief the Speaker can verify.",
    },
    "directive": {
        "label": "Directive",
        "criteria": "Asks a question, requests, commands, or suggests an action.",
    },
    "commissive": {
        "label": "Commissive",
        "criteria": "Commits the Host to a future action — promises, offers, threatens.",
    },
    "expressive": {
        "label": "Expressive",
        "criteria": "Expresses feelings or attitude — thanks, apology, congratulations, complaints.",
    },
    "declarative": {
        "label": "Declarative",
        "criteria": "Changes reality by its utterance — decisions, appointments, dismissals (needs authority).",
    },
    "other": {
        "label": "Other",
        "criteria": "The situation does not fit any of the standard acts above.",
    },
}

# The catch-all key; when JEV picks this (or is unsure) the Other flow runs.
OTHER_ACT = "other"


def act_criteria() -> dict:
    """Return the ``{act_key: criteria}`` mapping for a JEV ``choice`` question."""
    return {key: act["criteria"] for key, act in SPEECH_ACTS.items()}


def act_label(act_key: str) -> str:
    """Human-readable label for an act key (``""`` when unknown)."""
    return SPEECH_ACTS.get(act_key, {}).get("label", "")
