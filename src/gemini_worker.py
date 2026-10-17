import json
import os
import re
import time
import logging
from PySide6.QtCore import QThread, Signal
from src.ai_client import get_ai_client, IMAGE_CONTEXT_PROMPT
from src.config import (
    AI_STREAM_CHUNK_INTERVAL_MS,
    AUTO_REPLY_CONTEXT_DIGEST,
    AUTO_REPLY_FILLER_FILTER,
    JEV_MIN_CONFIDENCE,
    JEV_OBJECTIVE_MET_MIN,
    JEV_SHOULD_REPLY_MIN,
    PRONUNCIATION_GUIDES,
    SAMPLE_TEXTS,
    SELF_CONTEXT_FILE,
    SPEAKER_CONTEXT_FILE,
)
from src.decision_client import (
    DecisionClient,
    answer_choice,
    answer_noul,
    build_questions,
    build_state,
    language_options,
)
from src.filler_filter import is_filler
from src.objectives import objective_key, resolve_active
from src.purpose_store import slugify
from src.purposes import (
    BUILTIN_PURPOSES,
    DEFAULT_PURPOSE,
    DEFAULT_ROLE_STYLE,
    default_role_key,
    purpose_roles,
)
from src.speech_acts import OTHER_ACT, act_label

logger = logging.getLogger(__name__)

DEFAULT_SELF_CONTEXT = "bahasa pemograman javascript, react , nextjs, python, docker, kubernetes, aws, gcp, azure, github, gitlab, bitbucket, jenkins, circleci, travis ci, aws lambda, aws s3, aws ec2, aws rds, aws lambda, aws s3, aws ec2, aws rds"

# Lexical hints for the lightweight language heuristic. Detection is deliberately
# conservative: only strong, low-ambiguity signals are returned, otherwise the
# configured target language is used.
_INDONESIAN_MARKERS = {
    "apa", "kabar", "saya", "tidak", "dan", "yang", "sudah", "belum", "mau",
    "bisa", "terima", "kasih", "dengan", "untuk", "ini", "itu", "adalah",
    "hari", "juga", "atau", "punya", "kenapa", "bagaimana",
}
_ENGLISH_MARKERS = {
    "the", "is", "are", "you", "what", "how", "and", "to", "of", "in", "that",
    "it", "for", "this", "with", "hello", "thanks", "do", "does", "can", "would",
}

# Meta-prompt for the "Other" flow: one call returns the learning payload and the
# Host's reply as a single JSON object.
# Digest profile fields, in the order the prompt lists them (mirrors
# src/reply_context.py, which builds the dict).
_DIGEST_PROFILE_LABELS = (
    ("name", "Name"),
    ("occupation", "Occupation"),
    ("goals", "Goals"),
    ("pain_points", "Pain points"),
    ("facts", "Facts"),
)

# Meta-prompt for the "Other" flow: one call returns the learning payload and the
# Host's reply as a single JSON object.
OTHER_SYNTHESIS_INSTRUCTION = """You are a conversation analyst. The Host is an AI-assisted person in a live \
two-person conversation. The Speaker's latest utterance does not obviously fit any \
standard speech act (assertive, directive, commissive, expressive, declarative), so \
you must (a) decide whether a NEW reusable category of situation is needed and \
(b) write the exact words the Host should say next.

Return ONLY a JSON object — no prose, no code fences — in this shape:
{
  "new_category": {
    "key": "snake_case_key",
    "label": "Short Human Label",
    "persona": "You are ... (second person, describes the Host's role)",
    "objective": ["...", "..."],
    "speech_act": "assertive|directive|commissive|expressive|declarative",
    "criteria": "When does this situation apply?",
    "counterpart": "Who the Speaker is",
    "confidence": 0.0
  },
  "speaker_move": "One English sentence naming the Speaker's act and what they asked, confirmed, or stated.",
  "reply": "The exact words the Host should say next."
}

Rules:
- If the standard acts DO cover the situation, set "new_category" to null and just answer.
- "key" must be lowercase snake_case; "label" title case and short.
- Write "speaker_move" in English; write "reply" in the same language the Speaker is using.
- Keep "reply" short and spoken; do not narrate or mention being an AI."""


def _build_messages(conversation_history: list, latest_text: str, images: list = None) -> list:
    """Normalize conversation history into provider-neutral messages.

    Returns a list of ``{"role": "user" | "assistant", "text": str, "images": [...]}``
    dicts. The trailing Speaker turn is kept as its own clean final user message
    (so the latest utterance is never merged into a block or duplicated); the
    remaining consecutive same-role turns are merged, leading host turns are
    dropped (so the list starts with a user turn), speaker-side fillers are
    dropped (a run of "Exactly."/"You nailed it." is not conversation), and
    screenshots are attached to the final user turn.
    """
    logger.debug("Contents Length (%d turns):", len(conversation_history))
    for i, turn in enumerate(conversation_history):
        logger.debug("  [%d] role=%s | text=%s | suggestion=%s", i, turn['role'], turn['text'], turn['suggestion'])

    # Drop completely empty entries up front.
    turns = []
    for t in conversation_history:
        text = (t.get("text") or "").strip()
        if text:
            turns.append({"role": t.get("role"), "text": text})

    # The list must start with a 'user' turn: drop every leading unpaired host turn
    # (a single one is not enough — a run of ASR host fragments would still lead).
    while turns and turns[0].get("role") == "host":
        turns.pop(0)

    # The trailing Speaker turn is the authoritative "latest utterance": keep it
    # out of the merge so it stays a single, clean final user message.
    latest_utterance = None
    if turns and turns[-1].get("role") == "speaker":
        latest_utterance = turns.pop()["text"]
    if not latest_utterance:
        latest_utterance = (latest_text or "").strip()

    # Speaker-side fillers carry no content. Host turns are never dropped here:
    # what the Host said is the conversation the reply has to continue.
    turns = [
        t for t in turns
        if t.get("role") == "host" or not is_filler(t.get("text") or "")
    ]

    # Merge consecutive turns with the same role to reduce fragmentation/noise
    merged_history = []
    for t in turns:
        role = t.get("role")
        text = t["text"]
        if merged_history and merged_history[-1].get("role") == role:
            # Merge into previous entry
            prev_text = merged_history[-1].get("text", "")
            merged_history[-1]["text"] = (prev_text + "\n" + text).strip() if prev_text else text
        else:
            merged_history.append({
                "role": role,
                "text": text
            })

    messages = []
    idx = 0
    while idx < len(merged_history):
        turn = merged_history[idx]
        role = turn.get("role")
        if role == "speaker":
            # The other person's utterance becomes a user message
            speaker_text = turn.get("text", "").strip()
            if speaker_text:
                messages.append({"role": "user", "text": speaker_text})

            # Pair with the host reply if present next
            host_reply_text = None
            if idx + 1 < len(merged_history) and merged_history[idx + 1].get("role") == "host":
                host_reply_text = (merged_history[idx + 1].get("text") or "").strip()
                idx += 1  # consume the paired host turn

            if host_reply_text:
                messages.append({"role": "assistant", "text": host_reply_text})

        elif role == "host":
            # Unpaired host utterance (e.g., manual speech) as an assistant message
            host_text = turn.get("text", "").strip()
            if host_text:
                messages.append({"role": "assistant", "text": host_text})

        idx += 1

    # Guarantee the final turn is a single, clean Speaker utterance (never merged
    # into a block and never duplicated). A host turn landing after the question
    # leaves the question earlier in the list, so the earlier copy is dropped
    # rather than sent twice.
    if latest_utterance:
        already_last = (
            messages
            and messages[-1].get("role") == "user"
            and messages[-1].get("text", "").strip() == latest_utterance
        )
        if not already_last:
            messages = [
                m for m in messages
                if not (m.get("role") == "user"
                        and m.get("text", "").strip() == latest_utterance)
            ]
            messages.append({"role": "user", "text": latest_utterance})

    # Attach screenshots to the final user turn, or append a new user turn when
    # the conversation ends with an assistant turn (or is empty).
    if images:
        if messages and messages[-1].get("role") == "user":
            messages[-1]["images"] = list(messages[-1].get("images") or []) + list(images)
        else:
            messages.append({
                "role": "user",
                "text": IMAGE_CONTEXT_PROMPT,
                "images": list(images)
            })
        logger.debug("Attached %d screenshot(s)", len(images))

    return messages


def _get_pronunciation_line(target_language: str) -> str:
    """Build the Syllables/Pronunciation instruction line based on target language."""
    guide = PRONUNCIATION_GUIDES.get(target_language, PRONUNCIATION_GUIDES["Japanese"])
    return f"Syllables/Pronunciation: [{guide['instruction']} Example format: \"{guide['example']}\"]"


def _get_sample_text(target_language: str) -> str:
    """Get a sample text in the target language to show expected output format."""
    return SAMPLE_TEXTS.get(target_language, SAMPLE_TEXTS["Japanese"])


def _analysis_prompt_lines(speaker_act: str = None) -> list:
    """The English analysis line the model must emit before the reply.

    ``speaker_act`` pins the act label when JEV already decided it, so the
    analysis cannot contradict the status line; otherwise the model picks one.
    """
    act = (act_label(speaker_act) or speaker_act) if speaker_act else None
    move = f"{act} — " if act else "<Assertive|Directive|Commissive|Expressive|Declarative> — "
    return [
        f"Speaker's move: [{move}in one English sentence, what the Speaker just "
        "asked, confirmed, or stated]",
    ]


def _style_block(role: dict) -> str:
    """Render a role's optional ``style`` into the prompt's ``Style:`` section.

    Missing fields — and a role with no ``style`` block at all (an older
    ``purposes.json`` entry or an AI-synthesized role) — fall back to
    ``DEFAULT_ROLE_STYLE``, so every persona gets an explicit approach, tone,
    length and structure instead of one global rule. ``answer_first`` emits the
    answer-first directive; a false value (e.g. an Interviewer) emits nothing, so
    the prompt does not contradict a role whose job is to ask.
    """
    raw = role.get("style") if isinstance(role, dict) else None
    style = dict(DEFAULT_ROLE_STYLE)
    if isinstance(raw, dict):
        style.update({k: v for k, v in raw.items() if v not in (None, "")})
    lines = []
    if style.get("answer_first"):
        lines.append(
            "If the Speaker asked a question, answer it in your first sentence; "
            "never open with an acknowledgment or a counter-question."
        )
    for field, label in (("approach", "Approach"), ("tone", "Tone"),
                         ("length", "Length"), ("structure", "Structure")):
        value = str(style.get(field) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    if not lines:
        return ""
    return "\nStyle:\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def _analysis_text(speaker_move: str) -> str:
    """Render a free-form analysis block (Other flow); ``""`` when empty."""
    if not speaker_move:
        return ""
    return f"Speaker's move: {speaker_move.strip()}\n\n"


def _load_self_context() -> str:
    """Load self context from SELF_CONTEXT_FILE if configured, otherwise use default."""
    if not SELF_CONTEXT_FILE or not os.path.exists(SELF_CONTEXT_FILE):
        return DEFAULT_SELF_CONTEXT
    with open(SELF_CONTEXT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip() or DEFAULT_SELF_CONTEXT


def _load_speaker_context() -> str:
    """Load the optional Speaker profile; ``""`` when unset/absent/empty."""
    if not SPEAKER_CONTEXT_FILE or not os.path.exists(SPEAKER_CONTEXT_FILE):
        return ""
    try:
        with open(SPEAKER_CONTEXT_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return ""


def _detect_language(text: str):
    """Lightweight language hint from a single utterance (``None`` when unsure)."""
    if not text:
        return None
    # Script ranges are reliable, low-ambiguity signals.
    if re.search(r"[\u3040-\u30ff]", text):
        return "Japanese"
    if re.search(r"[\uac00-\ud7af]", text):
        return "Korean"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "Chinese"
    if re.search(r"[\u0600-\u06ff]", text):
        return "Arabic"
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return None
    id_hits = sum(1 for w in words if w in _INDONESIAN_MARKERS)
    en_hits = sum(1 for w in words if w in _ENGLISH_MARKERS)
    if id_hits >= 2 and id_hits > en_hits:
        return "Indonesian"
    return None


def _parse_json_object(text: str):
    """Parse a JSON object from a model reply, tolerating code fences/prose."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        return None


class GeminiWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    
    def __init__(self, text: str, target_language: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._target_language = target_language
        self._is_running = True
    
    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()

            system_instruction = f"""You are a professional translator. Translate the given text to {self._target_language}.

Format your response exactly as follows:
{self._target_language} Text: [Write the sentence using natural {self._target_language} script]
{_get_pronunciation_line(self._target_language)}
----------------
English Translation: [Provide the meaning in clear English]
----------------
Sample {self._target_language} text format: {_get_sample_text(self._target_language)}"""

            if not self._is_running:
                return

            response = client.generate(
                system_instruction,
                [{"role": "user", "text": f"Text to translate: {self._text}"}]
            )

            if self._is_running and response:
                self.result.emit(response)
            elif self._is_running:
                self.error.emit("Empty response received from the AI provider")
        except Exception as e:
            if self._is_running:
                self.error.emit(f"Translation error: {str(e)}")
    
    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False


class GeminiAutoReplyWorker(QThread):
    error = Signal(str)
    result = Signal(str)
    chunk = Signal(str)
    # Emitted instead of a result when JEV decides no reply is needed.
    skipped = Signal(str)
    # Human-readable progress (e.g. "Replying as Interviewer · Directive").
    status = Signal(str)
    # A JEV prediction of the active session objective: (index, confidence, source).
    # The decision call the reply already pays for answers ``current_objective``
    # too, so the objective tracker gets a free observation per reply.
    objective_observed = Signal(int, float, str)
    # Session objectives the decision call judges *already met* (list of indexes),
    # so the pane can show progress and the reply can stop re-opening them.
    objectives_satisfied = Signal(list)

    def __init__(self, transcription_text: str, target_language: str, conversation_history: list = None,
                 include_pronunciation: bool = True, purpose: str = DEFAULT_PURPOSE, images: list = None,
                 purpose_store=None, host_role: str = "smart", jev_enabled: bool = False,
                 context: dict = None, allow_filler: bool = False, digest: dict = None,
                 objectives: list = None, objective_locks: list = None,
                 objective_meta: dict = None, parent=None):
        super().__init__(parent)
        self._transcription_text = transcription_text
        self._target_language = target_language
        self._conversation_history = conversation_history or []
        self._include_pronunciation = include_pronunciation
        self._purpose = purpose
        self._images = images or []
        self._purpose_store = purpose_store
        self._host_role = host_role or "smart"
        self._jev_enabled = bool(jev_enabled)
        # An explicit request (the manual "Reply now" / hotkey) answers even a filler.
        self._allow_filler = bool(allow_filler)
        self._is_running = True
        # The Host/Speaker context is pushed by the web service (the Context
        # pane owns the files). ``None`` means nothing has arrived yet, so the
        # .env files are read exactly as before; an empty string is the user
        # explicitly selecting no context for that role.
        if context is None:
            self._self_context = _load_self_context()
            self._speaker_context = _load_speaker_context()
        else:
            self._self_context = (context.get("host") or "").strip()
            self._speaker_context = (context.get("speaker") or "").strip()
        # The session digest built by src/reply_context.py (bullets, locked
        # bullets, KYC profile, confirmed brief, prior suggestions). Only
        # rendered when AUTO_REPLY_CONTEXT_DIGEST is on.
        self._digest = digest if isinstance(digest, dict) else None
        # Session objectives mirrored from the ObjectiveController: the list, its
        # parallel lock flags and the tracker state. The prompt only needs the
        # *resolved* objective, but JEV is asked about the whole list.
        self._objectives = [str(o) for o in (objectives or []) if str(o).strip()]
        self._objective_locks = [bool(x) for x in (objective_locks or [])]
        self._objective_meta = dict(objective_meta or {})
        # Indexes the decision call judged already met (filled in ``run``); empty
        # whenever JEV is off, unavailable or unsure, so the prompt is unchanged.
        self._satisfied = []
        self._decision_client = None

    # --- JEV helpers --------------------------------------------------
    @property
    def _decision(self):
        if self._decision_client is None:
            self._decision_client = DecisionClient()
        return self._decision_client

    def _recent_turns(self) -> list:
        turns = []
        for turn in (self._conversation_history or [])[-6:]:
            text = (turn.get("text") or "").strip()
            if text:
                turns.append({"role": turn.get("role", "speaker"), "text": text})
        return turns

    def _run_decision(self, purpose, roles, role_key):
        """Call JEV and return the ``answers`` dict (or ``None`` to skip the gate)."""
        client = self._decision
        if client is None or not client.available:
            return None
        speaker_language = _detect_language(self._transcription_text)
        languages = language_options(speaker_language, self._target_language)
        checklist = purpose.get("objective_checklist") or []
        smart_role = self._host_role == "smart" and len(roles) > 1
        questions = build_questions(
            purpose, roles, checklist, smart_role, languages, self._target_language,
            objectives=self._objectives,
        )
        state = build_state(
            self._self_context,
            self._speaker_context,
            purpose.get("label", ""),
            role_key,
            self._recent_turns(),
            self._transcription_text,
            objectives=self._objectives,
            active_objective=resolve_active(
                self._objectives, self._objective_locks, self._objective_meta
            ),
        )
        return client.decide(state, questions)

    def _run_objective_decision(self, decision):
        """Read the ``current_objective`` answer out of a decision call.

        The question's criteria are keyed by ``objective_key``, so the choice is
        mapped back to its index. Returns ``(index, confidence)`` — ``(None,
        0.0)`` when JEV did not answer, the key is unknown, or the confidence is
        below ``JEV_MIN_CONFIDENCE``.
        """
        if not self._objectives:
            return None, 0.0
        choice, confidence = answer_choice(decision, "current_objective")
        if not choice or confidence < JEV_MIN_CONFIDENCE:
            return None, 0.0
        keys = {objective_key(o): i for i, o in enumerate(self._objectives)}
        index = keys.get(choice)
        if index is None:
            logger.debug("JEV named an unknown objective (%r); ignoring", choice)
            return None, 0.0
        return index, confidence

    def _objective_satisfied(self, decision) -> list:
        """Indexes of the objectives JEV judges *already met* by the conversation.

        One ``noul`` per objective (``decision_client.build_questions``). The bar
        is ``JEV_OBJECTIVE_MET_MIN``, deliberately higher than the act-picking
        confidence: a wrong "met" would quietly stop the Host closing a real gap.
        Returns ``[]`` when JEV is off, unkeyed, or sure of nothing — which is
        what keeps the ``Already met`` prompt line inert by default.
        """
        satisfied = []
        for i in range(len(self._objectives)):
            met = answer_noul(decision, f"objective_{i}")
            if met is not None and met >= JEV_OBJECTIVE_MET_MIN:
                satisfied.append(i)
        return satisfied

    # --- purpose / role resolution ------------------------------------
    def _resolve_purpose(self) -> dict:
        if self._purpose_store is not None:
            return self._purpose_store.get(self._purpose)
        return BUILTIN_PURPOSES.get(self._purpose, BUILTIN_PURPOSES[DEFAULT_PURPOSE])

    def _resolve_role(self, purpose, roles):
        role_key = self._host_role
        if role_key == "smart" or role_key not in roles:
            role_key = default_role_key(purpose)
        return role_key, roles.get(role_key) or next(iter(roles.values()))

    # --- prompt / streaming -------------------------------------------
    def _has_utterance(self) -> bool:
        """True when there is a Speaker utterance to analyse (image-only replies have none)."""
        return bool((self._transcription_text or "").strip())

    def _format_block(self, language: str, purpose: dict, speaker_act: str = None) -> str:
        lines = []
        if self._has_utterance():
            lines.extend(_analysis_prompt_lines(speaker_act))
            lines.append("")
        lines.append(f"{language} Text: [Write your response using natural {language} script]")
        if self._include_pronunciation:
            lines.append(_get_pronunciation_line(language))
            lines.append("English Translation: [Provide the meaning in clear English]")
        lines.extend(purpose.get("extra_format", []))
        lines.append(f"Sample {language} text format: {_get_sample_text(language)}")
        return "\n".join(lines)

    def _build_system_instruction(self, purpose, role, act_key=None, reply_language=None,
                                  speaker_act=None) -> str:
        persona = role.get("persona", "")
        objective = "\n".join(f"- {line}" for line in role.get("objective", []))
        style_section = _style_block(role)
        counterpart = role.get("counterpart")

        # Language priority: JEV choice -> detected Speaker language -> target.
        speaker_language = _detect_language(self._transcription_text)
        language = reply_language or speaker_language or self._target_language
        has_utterance = self._has_utterance()

        identity_lines = [f"- You are acting as: {role.get('label', 'Host')}."]
        if counterpart:
            identity_lines.append(f"- The Speaker is acting as: {counterpart}.")
        if act_key:
            label = act_label(act_key)
            if label:
                identity_lines.append(f"- Perform this speech act in your reply: {label}.")
        if has_utterance:
            label = act_label(speaker_act) if speaker_act else ""
            if label:
                identity_lines.append(
                    f"- The Speaker's latest utterance is a {label} speech act; "
                    "name it and say what they asked, confirmed, or stated."
                )
            else:
                identity_lines.append(
                    "- Classify the Speaker's latest utterance as one of: "
                    "Assertive, Directive, Commissive, Expressive, Declarative."
                )
        identity_block = "\n".join(identity_lines)

        if self._speaker_context:
            speaker_line = f"- Speaker profile: {self._speaker_context}"
        else:
            speaker_line = "- The Speaker profile is unknown; infer their role from the conversation."
        # Pre-identifier for the Host. Omitted entirely when the user selected
        # no context for that role (an empty string, not the .env default).
        host_line = (
            f"- Host profile (pre-identified): {self._self_context}\n"
            if self._self_context else ""
        )
        # The profile is only authoritative when it is actually attached, so the
        # rule travels with the bullet instead of being stated unconditionally. The
        # no-context branch is its mirror image: with nothing about what the Host
        # offers, the model must not invent product specifics. It deliberately avoids
        # the phrase "Host profile" — _tmp_context_prompt_check.py asserts that
        # phrase is absent when the user selected no context.
        grounding_rule = (
            "- The Host profile is the source of truth for what the Host offers: answer the\n"
            "  Speaker's question from it, and never invent product facts that are not in it.\n"
            "- Name the concrete product mechanism in your FIRST sentence, then explain it;\n"
            "  never answer a product question in the abstract.\n"
            if self._self_context else
            "- No profile of what the Host offers is available: do not invent product\n"
            "  specifics (features, integrations, dashboards, pricing, roadmaps). If the\n"
            "  answer depends on facts you do not have, say so briefly or ask.\n"
        )

        detected_line = (
            f"- The Speaker appears to be speaking {speaker_language} in their latest turn."
            if speaker_language else
            "- Mirror the language the Speaker uses in their latest turn."
        )

        output_rule = "" if self._include_pronunciation else (
            "\nOutput only the sections shown above (no pronunciation, no English translation)."
        )

        analysis_rule = (
            "- Write the \"Speaker's move\" line in English, before the reply; "
            "only the reply uses the language above.\n"
            if has_utterance else ""
        )

        digest_block = self._digest_block()
        objective_block = self._objective_block()

        return f"""{persona}

- Messages with role 'user' are what the other person (Speaker) said.
- Messages with role 'assistant' are what you (the Host) have said previously.
{grounding_rule}{identity_block}
{host_line}{speaker_line}{digest_block}{objective_block}

Objective:
{objective}
{style_section}
Language:
- Write the Host's reply in {language}.
{analysis_rule}{detected_line}
- If the Speaker switches language, mirror the new dominant language.
- Label the reply's first line with that language's name (e.g. "Indonesian Text:" instead of "{language} Text:").
- Adapt the syllables/pronunciation to the language you actually use, and ignore the sample text below when it is not in that language.

Format your response exactly as follows:
{self._format_block(language, purpose, speaker_act)}{output_rule}"""

    def _objective_block(self) -> str:
        """Render the prompt's ``Objective focus:`` section.

        The resolved objective is what the reply should serve. It is *soft*: a
        locked objective is marked (and always wins over the prediction), but it
        never suppresses a reply. Returns ``""`` when no objective is tracked, so
        the prompt is byte-identical to today's when the feature is unused.
        """
        active = resolve_active(self._objectives, self._objective_locks, self._objective_meta)
        if not active:
            return ""
        source = active.get("source") or ""
        detail = f" (confidence {active.get('confidence', 0.0):.2f}, from {source})" \
            if source and source != "lock" else ""
        lines = ["", "", "Objective focus:", f"- Working towards: {active['text']}{detail}"]
        if active.get("locked"):
            lines.append("- This objective is locked by the user; serve it.")
        met = [self._objectives[i] for i in self._satisfied
               if 0 <= i < len(self._objectives) and i != active.get("index")]
        if met:
            lines.append("- Already met (do not re-open these): " + "; ".join(met))
        return "\n".join(lines)

    def _digest_block(self) -> str:
        """Render the session digest as the prompt's ``Context digest:`` section.

        Carries what the app already computed: the bullet list, the bullets the
        user locked, the extracted KYC profile, the confirmed brief and the
        suggestions already given (so the reply does not repeat itself). Returns
        ``""`` when the feature flag is off or the digest is empty, which keeps
        the rendered system instruction byte-identical to the pre-digest one.
        """
        digest = self._digest if AUTO_REPLY_CONTEXT_DIGEST else None
        if not digest:
            return ""
        locked = digest.get("locked") or []
        bullets = digest.get("bullets") or []
        profile = digest.get("speaker") or {}
        brief = (digest.get("brief") or "").strip()
        suggestions = digest.get("prior_suggestions") or []

        lines = ["", "", "Context digest:"]
        if locked or bullets:
            lines.append("Conversation points so far:")
            lines.extend(f"- [locked] {item}" for item in locked)
            lines.extend(f"- {item}" for item in bullets)
        if profile:
            lines.append("Extracted Speaker profile:")
            for field, label in _DIGEST_PROFILE_LABELS:
                value = profile.get(field)
                if not value:
                    continue
                if isinstance(value, (list, tuple)):
                    value = "; ".join(str(v) for v in value)
                lines.append(f"- {label}: {value}")
        if brief:
            lines.append("Confirmed client brief:")
            lines.extend(f"  {line}" for line in brief.splitlines() if line.strip())
        if suggestions:
            lines.append("Already suggested (do not repeat these):")
            lines.extend(f"- {item}" for item in suggestions)
        return "\n".join(lines)

    def _emit_role_status(self, role, act_key=None, reply_language=None):
        parts = [f"Replying as {role.get('label', 'Host')}"]
        if act_key:
            label = act_label(act_key)
            if label:
                parts.append(label)
        if reply_language:
            parts.append(reply_language)
        self.status.emit(" · ".join(parts))

    def _stream_reply(self, client, system_instruction):
        """Stream the reply, emitting coalesced partials then the final result."""
        messages = _build_messages(
            self._conversation_history, self._transcription_text, self._images
        )
        if not self._is_running:
            return
        # Which optional prompt sections made it in, so the digest / objective
        # focus can be confirmed from the log without dumping the prompt itself.
        logger.debug(
            "System instruction: %d chars (digest=%s, objective_focus=%s)",
            len(system_instruction or ""),
            "on" if "Context digest:" in (system_instruction or "") else "off",
            "on" if "Objective focus:" in (system_instruction or "") else "off",
        )
        logger.debug("Messages (%d turns):", len(messages))
        for i, m in enumerate(messages):
            logger.debug("  [%d] role=%s | images=%d | %r", i, m['role'], len(m.get('images') or []), m.get('text', '')[:200])

        parts = []
        last_emit = 0.0
        interval_s = AI_STREAM_CHUNK_INTERVAL_MS / 1000.0
        for piece in client.generate_stream(system_instruction, messages):
            if not self._is_running:
                return
            if not piece:
                continue
            parts.append(piece)
            now = time.monotonic()
            if now - last_emit >= interval_s:
                last_emit = now
                self.chunk.emit("".join(parts))

        response = "".join(parts)
        if self._is_running and response:
            self.result.emit(response)
        elif self._is_running:
            self.error.emit("Empty response received from the AI provider")

    # --- Other flow (persona synthesis + learning) --------------------
    def _synthesize(self, client, purpose, role):
        """One LLM call returning ``(new_category, reply, speaker_move)``."""
        recent = "\n".join(
            f"[{t['role']}] {t['text']}" for t in self._recent_turns()
        )
        user = (
            f"Current purpose: {purpose.get('label', '')}\n"
            f"Host role: {role.get('label', '')}\n"
            f"Latest utterance from the Speaker: {self._transcription_text}\n"
            f"Recent conversation:\n{recent}"
        )
        try:
            response = client.generate(
                OTHER_SYNTHESIS_INSTRUCTION,
                [{"role": "user", "text": user}],
                disable_reasoning=True,
            )
        except Exception as e:
            logger.warning("Persona synthesis failed: %s", e)
            return None, None, None

        data = _parse_json_object(response)
        if not isinstance(data, dict):
            # Malformed output: keep the raw text as a plain reply, learn nothing.
            logger.warning("Persona synthesis returned unparsable JSON; using raw text")
            return None, (response or "").strip() or None, None
        new_category = data.get("new_category")
        if not isinstance(new_category, dict):
            new_category = None
        reply = (data.get("reply") or "").strip() or None
        speaker_move = (data.get("speaker_move") or "").strip() or None
        return new_category, reply, speaker_move

    def _should_register(self, new_category) -> bool:
        """Dedup pre-check: skip registration when a category already covers it."""
        if self._purpose_store is None:
            return False
        slug = slugify(new_category.get("key") or new_category.get("label") or "")
        if self._purpose_store.exists(slug):
            logger.info("Other flow: %r already exists; skipping registration", slug)
            return False
        client = self._decision
        if client is None or not client.available:
            return True
        known = [p.get("label", key) for key, p in self._purpose_store.all().items()]
        questions = {
            "covered": {
                "type": "noul",
                "instructions": "Do any of the existing categories already cover this situation?",
                "criteria": {
                    "true": "An existing category already fits this situation.",
                    "false": "This is genuinely a new situation not covered by any category.",
                },
            }
        }
        state = {
            "candidate": {
                "label": new_category.get("label"),
                "criteria": new_category.get("criteria"),
            },
            "existing_categories": known,
        }
        covered = answer_noul(client.decide(state, questions), "covered")
        if covered is None:
            return True
        return covered < 0.5

    def _run_other_flow(self, client, purpose, role, speaker_act=None):
        """Synthesize a new persona (learned + persisted) and answer with it."""
        logger.info("Other flow triggered: escalating to persona synthesis")
        new_category, reply, speaker_move = self._synthesize(client, purpose, role)
        if not self._is_running:
            return

        act_key = None
        if new_category and self._should_register(new_category):
            act_key = (new_category.get("speech_act") or "").strip() or None
            try:
                key = self._purpose_store.register(new_category)
                label = new_category.get("label") or key
                logger.info("Learned new persona %r", key)
                self.status.emit(f"Learned new persona: {label}")
            except Exception as e:
                logger.warning("Failed to register new persona: %s", e)

        if reply:
            text = _analysis_text(speaker_move) + reply
            self.chunk.emit(text)
            if self._is_running:
                self.result.emit(text)
            return

        # No reply from synthesis: fall back to a normal reply with the act hint.
        self._emit_role_status(role, act_key)
        system_instruction = self._build_system_instruction(
            purpose, role, act_key, None, speaker_act
        )
        self._stream_reply(client, system_instruction)

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()

            # A pure filler ("Okay.", "Exactly. You nailed it.") asks nothing, so it
            # skips the call instead of spending a suggestion on it. The manual path
            # (allow_filler) always replies.
            if (AUTO_REPLY_FILLER_FILTER and not self._allow_filler
                    and self._has_utterance() and not self._images
                    and is_filler(self._transcription_text)):
                logger.info("Auto-reply skipped: filler utterance %r",
                            self._transcription_text[:40])
                self.skipped.emit("Filler utterance")
                return

            purpose = self._resolve_purpose()
            roles = purpose_roles(purpose)
            role_key, role = self._resolve_role(purpose, roles)

            act_key = None
            reply_language = None
            speaker_act = None

            # JEV governs voice auto-replies only; a user-triggered screenshot
            # reply has no utterance to judge and must always produce an answer.
            if self._jev_enabled and not self._images:
                decision = self._run_decision(purpose, roles, role_key)
                if decision is not None:
                    # should_reply gate: stay silent when the Speaker needs nothing.
                    should = answer_noul(decision, "should_reply")
                    if should is not None and should < JEV_SHOULD_REPLY_MIN:
                        logger.info("JEV: no reply needed (p=%.2f)", should)
                        self.skipped.emit("No reply needed")
                        return

                    # Smart role: adopt the JEV choice when confident enough.
                    # A manually pinned role ("I am: <role>") is never overridden.
                    if self._host_role == "smart":
                        choice, confidence = answer_choice(decision, "host_role")
                        if choice in roles and confidence >= JEV_MIN_CONFIDENCE:
                            role_key, role = choice, roles[choice]

                    # Speaker's act: names the Speaker's move in the analysis
                    # preamble. "other" or low confidence falls back to the
                    # model's own classification.
                    choice, confidence = answer_choice(decision, "speaker_act")
                    if choice and choice != OTHER_ACT and confidence >= JEV_MIN_CONFIDENCE:
                        speaker_act = choice

                    # Speech act: "other" or low confidence escalates.
                    choice, confidence = answer_choice(decision, "speech_act")
                    if choice == OTHER_ACT or (choice and confidence < JEV_MIN_CONFIDENCE):
                        self._run_other_flow(client, purpose, role, speaker_act)
                        return
                    if choice:
                        act_key = choice

                    choice, _ = answer_choice(decision, "reply_language")
                    if choice:
                        reply_language = choice

                    # The objective tracker gets this prediction for free: the
                    # controller folds it in with its hysteresis, and only a
                    # committed transition reaches the prompt / history.
                    obj_index, obj_confidence = self._run_objective_decision(decision)
                    if obj_index is not None:
                        self.objective_observed.emit(obj_index, obj_confidence, "jev")

                    # Which objectives the conversation has already settled. Read
                    # here (and only here) so the answers are no longer paid for
                    # and thrown away; the prompt then stops re-opening them.
                    self._satisfied = self._objective_satisfied(decision)
                    if self._satisfied:
                        self.objectives_satisfied.emit(list(self._satisfied))

            self._emit_role_status(role, act_key, reply_language)
            system_instruction = self._build_system_instruction(
                purpose, role, act_key, reply_language, speaker_act
            )
            self._stream_reply(client, system_instruction)
        except Exception as e:
            if self._is_running:
                self.error.emit(f"AI auto-reply error: {str(e)}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
