"""Python client for the Go central hub (``hub/``).

The hub owns all live session state and the message bus; publishers (the
Soniox workers, the global hotkeys, the UI) send topics, subscribers receive
ordered events. The wire format is NDJSON over loopback TCP — see
``protocol.py`` for the framing and ``hub/internal/protocol`` for the Go side.
"""
