"""Render the Host/Speaker context as a *reference* block for AI prompts.

The Context pane owns the text (``websocket-server/context-store.js``) and which
variant it hands over — the real file or its AI-compacted ``.compacted`` sibling
(``effective`` in the ``context_state`` payload). This module is only the
prompt-side rendering, shared by the workers that *interpret the conversation*
(bullet points / KYC profile, Last Picked Up, objectives, summary) so they all
carry the same reference in the same shape.

It is deliberately **not** used by the auto-reply prompt: ``gemini_worker``
renders its own ``- Host profile (pre-identified): …`` / ``- Speaker profile: …``
lines, and that exact wording is asserted by the regression suite.

Every caller must send the block as *reference only*: the models are told to use
it to interpret the conversation and never to restate it as a finding, so a
pre-identified profile cannot leak back out as an "extracted" one.
"""

from src.config import REFERENCE_CONTEXT_MAX_CHARS

# The two roles, in the order they are rendered.
ROLES = ("host", "speaker")
_LABELS = {"host": "Host (us)", "speaker": "Speaker"}

_NOTE = (
    "use it to interpret the conversation; do NOT copy or restate anything from "
    "it as a finding"
)


def normalize(context) -> dict:
    """A ``{role: text}`` dict from a mirrored ``context`` payload.

    ``None`` (nothing arrived yet) and a non-dict both normalize to empty text,
    matching ``TranslationController.set_context``'s contract without collapsing
    it (callers that need the distinction keep using that method).
    """
    if not isinstance(context, dict):
        return {role: "" for role in ROLES}
    return {
        role: (context.get(role) if isinstance(context.get(role), str) else "").strip()
        for role in ROLES
    }


def has_context(context) -> bool:
    """True when at least one role carries non-empty reference text."""
    return any(normalize(context).values())


def _clip(text: str) -> str:
    limit = REFERENCE_CONTEXT_MAX_CHARS
    if limit and len(text) > limit:
        return text[:limit] + f"\n…[truncated at {limit} chars]"
    return text


def render_reference_context(context, *, label: str = "Reference context") -> str:
    """The prompt block, or ``""`` when there is nothing to render.

    Each role's text is clipped to ``REFERENCE_CONTEXT_MAX_CHARS``: these blocks
    ride prompts that run on a timer (the objective tracker re-arms every couple
    of seconds), so an unbounded 64 KB file must not be able to grow every call.
    The Compact button is the intended way to bring a long file under the limit.
    """
    values = normalize(context)
    lines = [f"{_LABELS[role]}: {_clip(values[role])}" for role in ROLES if values[role]]
    if not lines:
        return ""
    return f"{label} ({_NOTE}):\n" + "\n".join(lines) + "\n\n"
