"""NDJSON framing and envelope helpers shared with the Go hub.

One JSON object per line, ``\\n``-terminated. Mirrors
``hub/internal/protocol/protocol.go``; the constants must stay in sync with it
(the Go side rejects a frame whose ``type`` it does not recognize).
"""

import json
import time
import uuid

# Must match protocol.MaxLineBytes: screenshot data URLs ride inside payloads.
MAX_LINE_BYTES = 16 << 20

# Message types (the "type" field).
HELLO = "hello"
HELLO_OK = "hello_ok"
HELLO_ERR = "hello_err"
PUBLISH = "publish"
SUBSCRIBE = "subscribe"
UNSUBSCRIBE = "unsubscribe"
EVENT = "event"
REQUEST = "request"
RESPONSE = "response"
RESULT = "result"
RESULT_CHUNK = "result_chunk"
ACK = "ack"
ERROR = "error"

# Handshake roles.
ROLE_PUBLISHER = "publisher"
ROLE_UI = "ui"
ROLE_AGENT = "agent"
ROLE_BRIDGE = "bridge"

# Request operations.
OP_SNAPSHOT = "snapshot"
OP_RESTORE = "restore"
OP_RESET = "reset"

# Topics.
TOPIC_ALL = "*"
TOPIC_TRANSCRIPTION_PARTIAL = "transcription.partial"
TOPIC_TRANSCRIPTION_FINAL = "transcription.final"
TOPIC_TRANSLATION_FINAL = "translation.final"
TOPIC_STATUS = "status"
TOPIC_ERROR = "error"
TOPIC_SESSION_CONFIG = "session.config"
TOPIC_SCREENSHOTS_ADD = "screenshots.add"
TOPIC_SCREENSHOTS_CLEAR = "screenshots.clear"
TOPIC_COMMAND = "command"
# Bullet points + KYC speaker profile + per-update windows, published together
# (they always change as a unit). Payload: {items, speaker, windows}.
TOPIC_BULLETS = "bullets"

# Browser-bound mirror topics (the hub fans them out unchanged, so the Node
# path stays byte-identical).
TOPIC_PURPOSE_STATE = "purpose_state"

PARTIAL_SUFFIX = ".partial"

# Job kinds — one per agent entry point (mirrors dispatch.Kind*).
JOB_AUTO_REPLY = "auto_reply"
JOB_IMAGE_REPLY = "image_reply"
JOB_MANUAL_TRANSLATE = "manual_translate"
JOB_BULLETS = "bullets"
JOB_PICKUP = "pickup"


def new_id() -> str:
    """A short unique id for request/response correlation and job ids."""
    return uuid.uuid4().hex[:16]


def now() -> float:
    """Seconds since the epoch, as the Go side's float ``ts`` field."""
    return time.time()


def envelope(type_, **fields) -> dict:
    """Build a message dict, dropping ``None`` values."""
    msg = {"type": type_}
    for key, value in fields.items():
        if value is not None:
            msg[key] = value
    return msg


def encode(message: dict) -> bytes:
    """Serialize a message as one NDJSON frame."""
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line) -> dict:
    """Parse one NDJSON frame; raises ``ValueError`` on bad input."""
    if isinstance(line, (bytes, bytearray)):
        line = line.decode("utf-8")
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError("frame is not a JSON object")
    if not message.get("type"):
        raise ValueError("frame has no type")
    return message


def is_disposable(topic: str) -> bool:
    """True for topics whose frames may be dropped under backpressure."""
    return topic.endswith(PARTIAL_SUFFIX)


def match(pattern: str, topic: str) -> bool:
    """Whether a subscription pattern covers a concrete topic."""
    if pattern == TOPIC_ALL or pattern == topic:
        return True
    if pattern.endswith(".*"):
        return topic.startswith(pattern[:-1])
    return False
