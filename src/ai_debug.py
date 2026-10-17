"""DEBUG-gated prompt dump for every AI call.

When the root logger runs at DEBUG (``LOG_LEVEL``, default ``DEBUG``), every AI
call appends one human-readable block to ``logs/ai-prompt.log``: the system
instruction, the messages, the **exact request payload** the provider client is
about to send (model, contents/messages, generation config/extra body), the call
metadata (including the ``AUTO_REPLY_CONTEXT_DIGEST`` flag) and the model's
reply. Set ``LOG_LEVEL=INFO`` to disable the dump entirely — the toggle is the
logging level, there is no new env var.

Images are base64 data URLs, so they are **never** written: only their count is
recorded, and any data URL embedded in the payload is replaced by a size marker.
The dump is best effort — every write swallows ``OSError`` — and never changes
what is sent to the model, so it stays purely additive.

The request block is buffered (per thread) between :func:`log_request` and
:func:`log_payload` / :func:`log_reply`, so the payload lands inside the request
it belongs to. Concurrent workers still interleave whole blocks, and a
request/reply pair is correlated by the ``call_id`` returned from
:func:`log_request`.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime
from itertools import count

from src.config import AI_MODEL, AI_PROVIDER

logger = logging.getLogger(__name__)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.path.join(_REPO_ROOT, "logs", "ai-prompt.log")

_SEPARATOR = "=" * 80
# Monotonic per-process counter so call ids stay unique even within one second.
_counter = count(1)

# The request block is buffered here until the payload arrives (or the call
# finishes), so the "payload" section always sits inside its own request block.
_local = threading.local()

# Screenshots ride as ``data:image/<mime>;base64,<payload>``; the base64 body is
# never written (it is huge and not human-readable) — only its size.
_DATA_URL_RE = re.compile(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=]+")


def enabled() -> bool:
    """True when the app's logging runs at DEBUG (i.e. ``LOG_LEVEL`` allows it)."""
    return logging.getLogger(__name__).isEnabledFor(logging.DEBUG)


def _format_value(value) -> str:
    """Render a meta value; booleans become lowercase ``true``/``false``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _redact(value):
    """Replace every embedded image data URL with a size marker (recursively)."""
    if isinstance(value, str):
        return _DATA_URL_RE.sub(
            lambda m: f"<image data URL: {len(m.group(0))} chars elided>", value
        )
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _render_payload(payload) -> str:
    """Render the exact request payload as indented JSON (images elided)."""
    try:
        return json.dumps(_redact(payload), ensure_ascii=False, indent=2, default=str)
    except (TypeError, ValueError):
        return str(payload)


def _payload_section(payload) -> str:
    """The ``--- payload (exact request) ---`` block, including its blank lines."""
    return "\n--- payload (exact request) ---\n" + _render_payload(payload) + "\n"


def _write(text: str) -> None:
    """Append ``text`` to the dump file, best effort (never raises)."""
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def _flush_pending(call_id: str = None) -> None:
    """Write the buffered request block (optionally only for ``call_id``)."""
    pending = getattr(_local, "pending", None)
    if not pending:
        return
    if call_id is not None and pending[0] != call_id:
        return
    _local.pending = None
    _write(pending[1])


def log_request(label: str, system_instruction: str, messages: list,
                meta: dict = None, payload=None) -> str:
    """Buffer one request block and return its ``call_id``.

    The block is written by :func:`log_payload` — the provider client attaches
    the exact request it is about to send — or, when that never happens, by
    :func:`log_reply`, so the request, its payload and its reply stay together.
    Returns ``""`` (and writes nothing) when the dump is disabled, so the caller
    can pass the return value straight to :func:`log_reply` without checking.
    """
    if not enabled():
        return ""
    # Anything still buffered (a call that never produced a reply) is flushed.
    _flush_pending()

    timestamp = datetime.now()
    call_id = f"{label}-{timestamp.isoformat()}-{next(_counter)}"

    lines = [
        _SEPARATOR,
        f"[{timestamp.isoformat(timespec='seconds')}] REQUEST  {call_id}",
        f"provider={AI_PROVIDER} model={AI_MODEL or ''} label={label}",
    ]
    if meta:
        rendered = " ".join(f"{k}={_format_value(v)}" for k, v in meta.items())
        lines.append(f"meta: {rendered}")

    if system_instruction:
        lines += ["", "--- system instruction ---", system_instruction]
    if messages:
        lines += ["", f"--- messages ({len(messages)}) ---"]
        for i, msg in enumerate(messages):
            images = msg.get("images") or []
            lines.append(f"[{i}] role={msg.get('role')} images={len(images)}")
            lines.append(msg.get("text") or "")
    if payload is not None:
        lines.append(_payload_section(payload))
    lines.append("")

    _local.pending = (call_id, "\n".join(lines) + "\n")
    return call_id


def log_payload(payload) -> None:
    """Attach the exact request payload to this thread's buffered request.

    Called by the provider clients (``src/ai_client.py``) right before the SDK
    request is made. No-op when the dump is disabled or when no request is
    buffered in this thread (e.g. a stubbed client in a test).
    """
    if not enabled():
        return
    pending = getattr(_local, "pending", None)
    if not pending:
        return
    _, text = pending
    _local.pending = None
    _write(text.rstrip("\n") + "\n" + _payload_section(payload) + "\n")


def log_reply(call_id: str, reply) -> None:
    """Append the reply block for ``call_id`` (no-op when the dump is disabled)."""
    if not call_id or not enabled():
        return
    _flush_pending(call_id)
    lines = [
        f"--- reply    {call_id} ---",
        reply if reply is not None else "(none)",
        "",
    ]
    _write("\n".join(lines) + "\n")
