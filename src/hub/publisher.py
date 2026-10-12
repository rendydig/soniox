"""Thin named-publish helper over :class:`~src.hub.client.HubClient`.

Every helper is a no-op when the client is missing or disconnected, so a
publisher can call it unconditionally on the hot audio path without a
connection check at each call site.
"""

import logging
from datetime import datetime

from src.hub import protocol

logger = logging.getLogger(__name__)


class HubPublisher:
    """Publishes the app's canonical topics into the hub."""

    def __init__(self, client=None):
        self.client = client

    # --- plumbing -----------------------------------------------------

    def is_connected(self) -> bool:
        return bool(self.client and self.client.is_connected())

    def publish(self, topic: str, payload: dict = None) -> bool:
        if not self.is_connected():
            return False
        return self.client.publish(topic, payload or {})

    # --- transcription / translation ----------------------------------

    def transcription_partial(self, source: str, text: str) -> bool:
        return self.publish(protocol.TOPIC_TRANSCRIPTION_PARTIAL, {"source": source, "text": text})

    def transcription_final(
        self, source: str, text: str, endpoint: bool = False, timestamp: str = None
    ) -> bool:
        """Publish a finalized line.

        ``timestamp`` defaults to the same ``datetime.now().isoformat()`` the
        session store has always used, so persisted entries stay identical.
        """
        return self.publish(
            protocol.TOPIC_TRANSCRIPTION_FINAL,
            {
                "source": source,
                "text": text,
                "endpoint": bool(endpoint),
                "timestamp": timestamp or datetime.now().isoformat(),
            },
        )

    def translation_final(self, source: str, text: str, timestamp: str = None) -> bool:
        return self.publish(
            protocol.TOPIC_TRANSLATION_FINAL,
            {
                "source": source,
                "text": text,
                "timestamp": timestamp or datetime.now().isoformat(),
            },
        )

    def status(self, source: str, message: str) -> bool:
        return self.publish(protocol.TOPIC_STATUS, {"source": source, "message": message})

    def error(self, source: str, message: str) -> bool:
        return self.publish(protocol.TOPIC_ERROR, {"source": source, "message": message})

    # --- session / UI -------------------------------------------------

    def session_config(self, **fields) -> bool:
        """Publish the live session configuration (auto flags, purpose, caps...)."""
        return self.publish(protocol.TOPIC_SESSION_CONFIG, fields)

    def command(self, action: str, **fields) -> bool:
        """Ask the hub to do something (trigger_bullets, regenerate_bullets...)."""
        payload = {"action": action}
        payload.update(fields)
        return self.publish(protocol.TOPIC_COMMAND, payload)

    def bullets(self, items, speaker, windows) -> bool:
        """Publish the bullet list + speaker profile + windows as one topic."""
        return self.publish(protocol.TOPIC_BULLETS, {
            "items": list(items or []),
            "speaker": dict(speaker or {}),
            "windows": list(windows or []),
        })

    def screenshot(self, data_url: str) -> bool:
        return self.publish(protocol.TOPIC_SCREENSHOTS_ADD, {"data_url": data_url})

    def clear_screenshots(self) -> bool:
        return self.publish(protocol.TOPIC_SCREENSHOTS_CLEAR, {})

    # --- browser-bound mirrors (unchanged payload shapes) --------------

    def mirror(self, topic: str, payload: dict = None) -> bool:
        """Fan a browser-bound frame out to subscribers (Node path unchanged)."""
        return self.publish(topic, payload or {})

    # --- requests ------------------------------------------------------

    def snapshot(self, timeout: float = 5.0):
        """The hub's full state, or ``None`` when it is unreachable."""
        if not self.is_connected():
            return None
        return self.client.request(protocol.OP_SNAPSHOT, timeout=timeout)

    def restore(self, session: dict, timeout: float = 5.0):
        if not self.is_connected():
            return None
        return self.client.request(protocol.OP_RESTORE, session, timeout=timeout)

    def reset(self, timeout: float = 5.0):
        if not self.is_connected():
            return None
        return self.client.request(protocol.OP_RESET, timeout=timeout)
