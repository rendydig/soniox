"""Thin client for the TypeSafe JEV Decisions API (System One decision model).

JEV is *not* an OpenAI-compatible chat model: it takes application ``state`` plus
typed ``questions`` (``noul`` / ``choice`` / ``score``) and returns typed answers
with probabilities, and no generated text. Endpoint:
``POST {JEV_BASE_URL}/alpha/decisions``.

Everything here degrades gracefully: when JEV is disabled, unkeyed, times out, or
returns malformed JSON, ``decide()`` logs a warning and returns ``None`` so the
caller falls back to the plain auto-reply.
"""

import json
import logging
import urllib.error
import urllib.request

from src.config import (
    JEV_API_KEY,
    JEV_BASE_URL,
    JEV_ENABLED,
    JEV_MODEL,
    LANGUAGES,
)
from src.speech_acts import SPEECH_ACTS, act_criteria

logger = logging.getLogger(__name__)


class DecisionClient:
    """Client for the JEV decisions endpoint (standard library, no new deps)."""

    def __init__(self, api_key=None, base_url=None, model=None, enabled=None):
        self._key = JEV_API_KEY if api_key is None else api_key
        base = JEV_BASE_URL if base_url is None else base_url
        self._base = (base or "").rstrip("/")
        self._model = model or JEV_MODEL
        flag = JEV_ENABLED if enabled is None else enabled
        self._enabled = bool(flag and self._key and self._base)

    @property
    def available(self) -> bool:
        return self._enabled

    def decide(self, state: dict, questions: dict, timeout: float = 4.0):
        """Return the ``answers`` dict, or ``None`` on any failure."""
        if not self._enabled:
            return None
        payload = {"model": self._model, "state": state, "questions": questions}
        try:
            body = json.dumps(payload).encode("utf-8")
        except (TypeError, ValueError) as e:
            logger.warning("JEV payload not serializable: %s", e)
            return None
        request = urllib.request.Request(
            self._base + "/alpha/decisions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
            logger.warning("JEV decision call failed: %s", e)
            return None
        answers = parsed.get("answers") if isinstance(parsed, dict) else None
        if not isinstance(answers, dict):
            logger.warning("JEV response missing 'answers'")
            return None
        return answers


def language_options(speaker_language: str = None, target_language: str = None) -> list:
    """Reply-language candidates: the Speaker's language first, then the target."""
    options = []
    for name in (speaker_language, target_language, *LANGUAGES.keys()):
        if name and name not in options:
            options.append(name)
    return options


def build_questions(purpose: dict, roles: dict, checklist: list, smart_role: bool,
                    languages: list, target_language: str = None) -> dict:
    """Build the JEV ``questions`` dict for one reply decision.

    ``should_reply`` (noul) and ``speech_act`` (choice) are always present;
    ``host_role`` only in Smart mode; ``reply_language`` when any candidate is
    known; and one ``objective_N`` noul per checklist item.
    """
    questions = {
        "should_reply": {
            "type": "noul",
            "instructions": (
                "Should the Host respond to the Speaker's latest utterance now, "
                "rather than stay silent (the Speaker may be thinking aloud or unfinished)?"
            ),
            "criteria": {
                "true": "The Speaker has finished an utterance that invites or expects a response.",
                "false": "The Speaker is still thinking aloud or the latest line does not need a reply.",
            },
        },
    }

    if smart_role and roles:
        questions["host_role"] = {
            "type": "choice",
            "instructions": "Which role is the Host playing in this conversation?",
            "criteria": {key: role.get("label", key) for key, role in roles.items()},
        }

    policy = purpose.get("speech_act_policy") or []
    instructions = "Which speech act should the Host perform in the reply?"
    if policy:
        labels = ", ".join(SPEECH_ACTS.get(a, {}).get("label", a) for a in policy)
        instructions += f" This purpose usually favours: {labels}."
    questions["speech_act"] = {
        "type": "choice",
        "instructions": instructions,
        "criteria": act_criteria(),
    }

    lang_criteria = {lang: f"Reply in {lang}." for lang in languages or []}
    if target_language and target_language not in lang_criteria:
        lang_criteria[target_language] = f"Reply in {target_language}."
    if lang_criteria:
        questions["reply_language"] = {
            "type": "choice",
            "instructions": (
                "Which language should the Host reply in? Prefer the language the "
                "Speaker is currently speaking."
            ),
            "criteria": lang_criteria,
        }

    for i, item in enumerate(checklist or []):
        questions[f"objective_{i}"] = {
            "type": "noul",
            "instructions": item,
            "criteria": {"true": "Yes.", "false": "No."},
        }
    return questions


def build_state(host_profile: str, speaker_profile: str, purpose_label: str,
                host_role: str, turns: list, latest_utterance: str) -> dict:
    """Build the unstructured ``state`` sent alongside the questions."""
    state = {
        "host_profile": host_profile or "",
        "purpose": purpose_label or "",
        "host_role": host_role or "smart",
        "recent_turns": turns or [],
        "latest_utterance": latest_utterance or "",
    }
    if speaker_profile:
        state["speaker_profile"] = speaker_profile
    return state


def answer_choice(answers: dict, key: str):
    """Return ``(choice, confidence)`` for a ``choice`` answer, else ``(None, 0.0)``."""
    answer = (answers or {}).get(key)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None, 0.0
    try:
        confidence = float(answer.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return answer.get("choice"), confidence


def answer_noul(answers: dict, key: str):
    """Return the yes-probability of a ``noul`` answer, else ``None``."""
    answer = (answers or {}).get(key)
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        return None
    try:
        return float(answer.get("noul"))
    except (TypeError, ValueError):
        return None
