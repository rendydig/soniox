import json
import os
import re
import time
import logging
from PySide6.QtCore import QThread, Signal
from src.ai_client import get_ai_client, IMAGE_CONTEXT_PROMPT
from src.config import (
    AI_STREAM_CHUNK_INTERVAL_MS,
    JEV_MIN_CONFIDENCE,
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
from src.purpose_store import slugify
from src.purposes import (
    BUILTIN_PURPOSES,
    DEFAULT_PURPOSE,
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
  "reply": "The exact words the Host should say next."
}

Rules:
- If the standard acts DO cover the situation, set "new_category" to null and just answer.
- "key" must be lowercase snake_case; "label" title case and short.
- Write "reply" in the same language the Speaker is using.
- Keep "reply" short and spoken; do not narrate or mention being an AI."""


def _build_messages(conversation_history: list, latest_text: str, images: list = None) -> list:
    """Normalize conversation history into provider-neutral messages.

    Returns a list of ``{"role": "user" | "assistant", "text": str, "images": [...]}``
    dicts. Consecutive same-role turns are merged, a leading host turn is dropped
    (so the list starts with a user turn), the latest transcription is appended
    unless already present, and screenshots are attached to the final user turn.
    """
    logger.debug("Contents Length (%d turns):", len(conversation_history))
    for i, turn in enumerate(conversation_history):
        logger.debug("  [%d] role=%s | text=%s | suggestion=%s", i, turn['role'], turn['text'], turn['suggestion'])

    # Merge consecutive turns with the same role to reduce fragmentation/noise
    merged_history = []
    for t in conversation_history:
        role = t.get("role")
        text = (t.get("text") or "").strip()
        # Skip completely empty entries
        if not text:
            continue
        if merged_history and merged_history[-1].get("role") == role:
            # Merge into previous entry
            prev_text = merged_history[-1].get("text", "")
            merged_history[-1]["text"] = (prev_text + "\n" + text).strip() if prev_text else text
        else:
            merged_history.append({
                "role": role,
                "text": text
            })

    # The list must start with a 'user' turn, so drop any leading unpaired host turn.
    if merged_history and merged_history[0].get("role") == "host":
        merged_history.pop(0)

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

    # Build latest user input, but don't duplicate it if the caller already
    # appended the current transcription as the most recent speaker turn.
    latest_input = (latest_text or "").strip()
    already_latest_speaker = (
        merged_history
        and merged_history[-1].get("role") == "speaker"
        and merged_history[-1].get("text", "").strip() == latest_input
    )
    if latest_input and not already_latest_speaker:
        messages.append({"role": "user", "text": latest_input})

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

    def __init__(self, transcription_text: str, target_language: str, conversation_history: list = None,
                 include_pronunciation: bool = True, purpose: str = DEFAULT_PURPOSE, images: list = None,
                 purpose_store=None, host_role: str = "smart", jev_enabled: bool = False, parent=None):
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
        self._is_running = True
        self._self_context = _load_self_context()
        self._speaker_context = _load_speaker_context()
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
            purpose, roles, checklist, smart_role, languages, self._target_language
        )
        state = build_state(
            self._self_context,
            self._speaker_context,
            purpose.get("label", ""),
            role_key,
            self._recent_turns(),
            self._transcription_text,
        )
        return client.decide(state, questions)

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
    def _format_block(self, language: str, purpose: dict) -> str:
        lines = [f"{language} Text: [Write your response using natural {language} script]"]
        if self._include_pronunciation:
            lines.append(_get_pronunciation_line(language))
            lines.append("English Translation: [Provide the meaning in clear English]")
        lines.extend(purpose.get("extra_format", []))
        lines.append(f"Sample {language} text format: {_get_sample_text(language)}")
        return "\n".join(lines)

    def _build_system_instruction(self, purpose, role, act_key=None, reply_language=None) -> str:
        persona = role.get("persona", "")
        objective = "\n".join(f"- {line}" for line in role.get("objective", []))
        counterpart = role.get("counterpart")

        # Language priority: JEV choice -> detected Speaker language -> target.
        speaker_language = _detect_language(self._transcription_text)
        language = reply_language or speaker_language or self._target_language

        identity_lines = [f"- You are acting as: {role.get('label', 'Host')}."]
        if counterpart:
            identity_lines.append(f"- The Speaker is acting as: {counterpart}.")
        if act_key:
            label = act_label(act_key)
            if label:
                identity_lines.append(f"- Perform this speech act in your reply: {label}.")
        identity_block = "\n".join(identity_lines)

        if self._speaker_context:
            speaker_line = f"- Speaker profile: {self._speaker_context}"
        else:
            speaker_line = "- The Speaker profile is unknown; infer their role from the conversation."

        detected_line = (
            f"- The Speaker appears to be speaking {speaker_language} in their latest turn."
            if speaker_language else
            "- Mirror the language the Speaker uses in their latest turn."
        )

        output_rule = "" if self._include_pronunciation else (
            "\nOutput only the sections shown above (no pronunciation, no English translation)."
        )

        return f"""{persona}

- Messages with role 'user' are what the other person (Speaker) said.
- Messages with role 'assistant' are what you (the Host) have said previously.
{identity_block}
- Your expertise areas: {self._self_context}.
{speaker_line}

Objective:
{objective}

Language:
- Write the Host's reply in {language}.
{detected_line}
- If the Speaker switches language, mirror the new dominant language.
- Label the first line with that language's name (e.g. "Indonesian Text:" instead of "{language} Text:").
- Adapt the syllables/pronunciation to the language you actually use, and ignore the sample text below when it is not in that language.

Format your response exactly as follows:
{self._format_block(language, purpose)}{output_rule}"""

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
        """One LLM call returning ``(new_category | None, reply | None)``."""
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
            return None, None

        data = _parse_json_object(response)
        if not isinstance(data, dict):
            # Malformed output: keep the raw text as a plain reply, learn nothing.
            logger.warning("Persona synthesis returned unparsable JSON; using raw text")
            return None, (response or "").strip() or None
        new_category = data.get("new_category")
        if not isinstance(new_category, dict):
            new_category = None
        reply = (data.get("reply") or "").strip() or None
        return new_category, reply

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

    def _run_other_flow(self, client, purpose, role):
        """Synthesize a new persona (learned + persisted) and answer with it."""
        logger.info("Other flow triggered: escalating to persona synthesis")
        new_category, reply = self._synthesize(client, purpose, role)
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
            self.chunk.emit(reply)
            if self._is_running:
                self.result.emit(reply)
            return

        # No reply from synthesis: fall back to a normal reply with the act hint.
        self._emit_role_status(role, act_key)
        system_instruction = self._build_system_instruction(purpose, role, act_key, None)
        self._stream_reply(client, system_instruction)

    def run(self):
        try:
            if not self._is_running:
                return

            client = get_ai_client()

            purpose = self._resolve_purpose()
            roles = purpose_roles(purpose)
            role_key, role = self._resolve_role(purpose, roles)

            act_key = None
            reply_language = None

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

                    # Speech act: "other" or low confidence escalates.
                    choice, confidence = answer_choice(decision, "speech_act")
                    if choice == OTHER_ACT or (choice and confidence < JEV_MIN_CONFIDENCE):
                        self._run_other_flow(client, purpose, role)
                        return
                    if choice:
                        act_key = choice

                    choice, _ = answer_choice(decision, "reply_language")
                    if choice:
                        reply_language = choice

            self._emit_role_status(role, act_key, reply_language)
            system_instruction = self._build_system_instruction(
                purpose, role, act_key, reply_language
            )
            self._stream_reply(client, system_instruction)
        except Exception as e:
            if self._is_running:
                self.error.emit(f"AI auto-reply error: {str(e)}")

    def stop(self):
        """Stop the worker gracefully."""
        self._is_running = False
