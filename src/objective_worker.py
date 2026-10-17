"""Objective prediction for the session objective tracker.

One prediction per debounce cycle, computed off the Qt thread because both
engines block on HTTP:

1. **JEV first** — the same decision layer the auto-reply uses. Its
   ``current_objective`` question (``decision_client.build_questions``) is asked
   against the session's objective list, so a confident answer costs no
   generation call at all. ``JEV_ENABLED`` defaults to false, so this is skipped
   entirely without a key.
2. **LLM fallback** — one small classification call that returns
   ``{"objective": "<label>", "confidence": 0.0}``, mapped back to an index. This
   is the default-user path: without JEV the tracker still works.

``result`` carries ``(index, confidence, source)``; an index of ``-1`` means "no
objective fits" (the tracker resets its hysteresis streak instead of committing).
"""

import json
import logging

from PySide6.QtCore import QThread, Signal

from src import ai_debug
from src.ai_client import get_ai_client
from src.config import JEV_MIN_CONFIDENCE, OBJECTIVE_MAX_LINE_CHARS
from src.decision_client import (
    DecisionClient,
    answer_choice,
    build_questions,
    build_state,
)
from src.gemini_worker import _parse_json_object
from src.objectives import objective_key, resolve_active
from src.reference_context import render_reference_context

logger = logging.getLogger(__name__)

# No matching objective: the tracker resets instead of committing.
NO_OBJECTIVE = -1

SYSTEM_INSTRUCTION = """You track which objective a live two-person conversation is \
currently working on.

Rules:
- Messages are labelled [host] (the person you are helping) and [speaker] (the other person).
- You are given the session's objective list and a rolling window of the conversation.
- Pick the ONE objective the conversation is working on right now — the thing the
  host and speaker are currently driving at, not every objective mentioned so far.
- Use the objective text EXACTLY as given in the list. If nothing in the list fits,
  set "objective" to "".
- Judge by the latest turns; an objective the conversation has clearly finished is
  not the current one, even if it was important earlier.
- Return ONLY a JSON object — no prose, no code fences — in this shape:
  {"objective": "<exact objective text, or \\"\\">", "confidence": 0.0}
- "confidence" is your own 0.0-1.0 certainty that this is the current objective.
- REFERENCE CONTEXT: when the user message carries a "Reference context" block it is
  background about the two participants. Use it to interpret the conversation; never
  treat it as an objective and never add anything from it to the list."""


class ObjectiveWorker(QThread):
    """Predict the active session objective (JEV first, LLM fallback)."""

    result = Signal(int, float, str)
    error = Signal(str)

    def __init__(self, lines: list, objectives: list, locks: list = None,
                 meta: dict = None, host_profile: str = "", speaker_profile: str = "",
                 parent=None, context: dict = None):
        super().__init__(parent)
        self._lines = list(lines or [])
        self._objectives = [str(o) for o in (objectives or []) if str(o).strip()]
        self._locks = [bool(x) for x in (locks or [])]
        self._meta = dict(meta or {})
        self._host_profile = host_profile or ""
        self._speaker_profile = speaker_profile or ""
        # Host/Speaker reference context (the Context pane's file, or its
        # compacted variant). The JEV path gets it through ``build_state`` above;
        # this is the LLM-fallback block.
        self._context = context if isinstance(context, dict) else {}
        self._is_running = True

    # --- helpers ------------------------------------------------------
    def _latest_utterance(self) -> str:
        for entry in reversed(self._lines):
            try:
                text = str(entry[1] or "").strip()
            except (TypeError, IndexError):
                continue
            if text:
                return text
        return ""

    def _turns(self) -> list:
        """The window as the ``recent_turns`` state JEV expects."""
        turns = []
        for entry in self._lines:
            try:
                source, text = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            text = str(text or "").strip()
            if text:
                turns.append({"role": source or "speaker", "text": text})
        return turns

    def _index_for(self, label: str):
        """Map a returned objective label back to its index (``None`` when unknown)."""
        label = (label or "").strip()
        if not label:
            return None
        for index, objective in enumerate(self._objectives):
            if objective == label:
                return index
        key = objective_key(label)
        for index, objective in enumerate(self._objectives):
            if objective_key(objective) == key:
                return index
        lowered = label.lower()
        for index, objective in enumerate(self._objectives):
            if lowered in objective.lower() or objective.lower() in lowered:
                return index
        return None

    # --- JEV ----------------------------------------------------------
    def _jev_prediction(self):
        """``(index, confidence)`` from JEV, or ``None`` to fall through to the LLM."""
        client = DecisionClient()
        if not client.available:
            return None
        questions = build_questions({}, {}, [], False, [], None, objectives=self._objectives)
        state = build_state(
            self._host_profile,
            self._speaker_profile,
            "",
            "smart",
            self._turns(),
            self._latest_utterance(),
            objectives=self._objectives,
            active_objective=resolve_active(self._objectives, self._locks, self._meta),
        )
        decision = client.decide(state, questions)
        if decision is None:
            return None
        choice, confidence = answer_choice(decision, "current_objective")
        if not choice or confidence < JEV_MIN_CONFIDENCE:
            return None
        index = self._index_for(choice)
        if index is None:
            logger.debug("JEV named an unknown objective (%r); falling back", choice)
            return None
        logger.info("JEV objective prediction: %r (p=%.2f)", self._objectives[index], confidence)
        return index, confidence

    # --- LLM ----------------------------------------------------------
    def _build_user_message(self) -> str:
        rendered = []
        for entry in self._lines:
            try:
                source, text = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            rendered.append(f"[{source}] {str(text or '')[:OBJECTIVE_MAX_LINE_CHARS]}")
        return (
            f"Objectives (JSON list, in order):\n"
            f"{json.dumps(self._objectives, ensure_ascii=False)}\n\n"
            f"{render_reference_context(self._context)}"
            f"Conversation window:\n" + "\n".join(rendered) +
            f"\n\nLatest utterance: {self._latest_utterance()}"
        )

    def run(self):
        try:
            if not self._is_running or not self._objectives:
                return

            jev = self._jev_prediction()
            if jev is not None:
                if self._is_running:
                    self.result.emit(jev[0], jev[1], "jev")
                return

            client = get_ai_client()
            user_message = self._build_user_message()
            call_id = ai_debug.log_request(
                "objective", SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                meta={"count": len(self._objectives)},
            )
            response = client.generate(
                SYSTEM_INSTRUCTION,
                [{"role": "user", "text": user_message}],
                disable_reasoning=True,
            )
            ai_debug.log_reply(call_id, response)
            if not self._is_running:
                return
            if response is None:
                self.error.emit("Empty response received from the AI provider")
                return

            data = _parse_json_object(response)
            if not isinstance(data, dict):
                logger.warning("Objective prediction returned unparsable JSON: %r",
                               (response or "")[:120])
                self.error.emit("Could not parse the objective prediction")
                return
            index = self._index_for(data.get("objective"))
            try:
                confidence = float(data.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if index is None:
                # "Nothing in the list fits": a real answer, not a failure — the
                # tracker resets its pending streak instead of committing.
                logger.info("Objective prediction found no matching objective")
                index = NO_OBJECTIVE
            else:
                logger.info("LLM objective prediction: %r (p=%.2f)",
                            self._objectives[index], confidence)
            self.result.emit(index, confidence, "llm")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Objective prediction error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
