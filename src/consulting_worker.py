import json
import logging

from PySide6.QtCore import QThread, Signal

from src import ai_debug
from src.ai_client import get_ai_client
from src.config import CONSULTING_MAX_LINE_CHARS

logger = logging.getLogger(__name__)

# The three one-shot consulting calls. Each ``mode`` has its own system prompt;
# the user message is assembled per mode in ``_build_user_message``.
MODES = ("brief", "gaps", "roadmap")

BRIEF_INSTRUCTION = """You draft a structured "client brief" from a live two-person \
discovery conversation, capturing ONLY what the [speaker] (the client) actually said.

Rules:
- Messages are labelled [host] (the consultant) and [speaker] (the client).
- Ground every item in the [speaker]'s own words. NEVER invent, guess, or infer facts,
  numbers, goals, or constraints that were not stated. Put anything unclear or unstated
  under "## Open Questions" instead of inventing a value.
- Write the brief in the same language as the conversation. Keep proper nouns as-is.
- Return GitHub-flavoured Markdown with EXACTLY these section headings, in this order,
  and nothing else (no preamble, no closing remarks, no code fences):
  ## Goals
  ## Pain Points
  ## Constraints
  ## Success Metrics
  ## Scope
  ## Open Questions
- Use a bullet list for a section with more than one item, a single sentence otherwise.
- OMIT a section entirely when the conversation produced nothing for it — do not write
  "N/A", "None", or an empty bullet list.
- "## Open Questions" lists what the client has not yet clarified and the consultant still
  needs to ask before the brief can be considered complete."""

GAPS_INSTRUCTION = """You are the consultant's real-time gap analyst for a client \
discovery conversation. Flag thin or contradictory parts of the conversation so the \
consultant can close them BEFORE the meeting ends.

Weigh two variables:
- Depth of the client's answer vs. the complexity of the goal they stated.
- Contradictions in the client's story (things that do not fit together).

You are given a reference — the client's stated goals, either a confirmed brief or a
speaker profile. Every gap you flag must be a real missing or contradictory piece judged
against that reference.

Rules:
- Only flag genuine gaps: a thin/undefined answer for a complex goal, a contradiction, a
  missing success metric, or an unstated constraint.
- Emit one markdown bullet per gap, in this exact shape (the "Ask:" line indented under
  its flag):
  **<short flag name>** — why it is a gap, in one sentence.
  Ask: "<a single sharp question the consultant can ask right now>"
- Do not invent gaps. When the conversation already covers the reference well, return
  nothing at all (an empty reply).
- Write in the same language as the conversation."""

ROADMAP_INSTRUCTION = """You turn a confirmed client brief and a list of flagged gaps \
into a prioritized execution roadmap — "turn-by-turn directions" for the consultant.

Rules:
- Start with one short summary sentence stating the destination.
- Then output 4 to 7 ordered steps, most important first, each on its own line:
  N. **<Step name>** — what it does, why it is next, and what it validates.
- Order discovery/validation BEFORE build: never jump to implementation before the open
  questions and success metrics are closed.
- Fold every flagged gap into a step that resolves it; leave no gap unaddressed.
- Ground the roadmap in the confirmed brief and the conversation; do not invent goals,
  constraints, or metrics that were not stated.
- Write in the same language as the conversation."""

SYSTEM_INSTRUCTIONS = {
    "brief": BRIEF_INSTRUCTION,
    "gaps": GAPS_INSTRUCTION,
    "roadmap": ROADMAP_INSTRUCTION,
}


class ConsultingWorker(QThread):
    """One-shot consulting call: draft a brief, analyze gaps, or build a roadmap.

    A single worker serves all three modes; ``mode`` picks the system prompt and
    how the user message is assembled. Modelled on ``SummarizeWorker``.
    """

    result = Signal(str)
    error = Signal(str)

    def __init__(self, mode: str, lines: list, reference: str = "", gaps: str = "",
                 speaker: dict = None, context: dict = None, parent=None):
        super().__init__(parent)
        self._mode = mode if mode in MODES else "brief"
        self._lines = list(lines or [])
        self._reference = str(reference or "")
        self._gaps = str(gaps or "")
        self._speaker = dict(speaker or {})
        self._context = context if isinstance(context, dict) else {}
        self._is_running = True

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def system_instruction(self) -> str:
        return SYSTEM_INSTRUCTIONS[self._mode]

    def _render_transcript(self) -> str:
        # Lines are ``(source, text)`` or ``(source, text, timestamp)``; only the
        # first two fields matter to the prompt. Each line is truncated for token
        # safety (the transcript is already capped by the session store).
        rendered = []
        for entry in self._lines:
            try:
                source, text = entry[0], entry[1]
            except (TypeError, IndexError):
                continue
            rendered.append(f"[{source}] {str(text)[:CONSULTING_MAX_LINE_CHARS]}")
        return "\n".join(rendered)

    def _speaker_context(self) -> str:
        value = self._context.get("speaker") if self._context else ""
        return value if isinstance(value, str) else ""

    def _reference_block(self) -> str:
        """The locked reference: the confirmed brief, else the speaker profile."""
        if self._reference:
            return f"Reference brief (confirmed):\n{self._reference}"
        block = f"Speaker profile (JSON): {json.dumps(self._speaker, ensure_ascii=False)}"
        context = self._speaker_context()
        if context:
            block += f"\n\nSpeaker context:\n{context}"
        return block

    def _build_user_message(self) -> str:
        transcript = self._render_transcript()
        if self._mode == "brief":
            # No reference yet — the brief is what we are drafting. Give the model
            # the transcript, the speaker profile and the Speaker context file.
            blocks = [f"Conversation transcript:\n{transcript}"]
            profile = f"Speaker profile (JSON): {json.dumps(self._speaker, ensure_ascii=False)}"
            context = self._speaker_context()
            if context:
                profile += f"\n\nSpeaker context:\n{context}"
            blocks.append(profile)
            return "\n\n".join(blocks)

        if self._mode == "gaps":
            return (
                f"Conversation transcript:\n{transcript}\n\n"
                f"{self._reference_block()}"
            )

        # roadmap
        blocks = [f"Conversation transcript:\n{transcript}", self._reference_block()]
        if self._gaps:
            blocks.append(f"Flagged gaps:\n{self._gaps}")
        return "\n\n".join(blocks)

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()
            user_message = self._build_user_message()
            call_id = ai_debug.log_request(
                "consulting", self.system_instruction,
                [{"role": "user", "text": user_message}],
                meta={"mode": self._mode},
            )
            response = client.generate(
                self.system_instruction,
                [{"role": "user", "text": user_message}],
                disable_reasoning=True,
            )
            ai_debug.log_reply(call_id, response)

            if not self._is_running:
                return

            if response is None:
                self.error.emit("Empty response received from the AI provider")
            else:
                self.result.emit((response or "").strip())
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Consulting error: {e}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
