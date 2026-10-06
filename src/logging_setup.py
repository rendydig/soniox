import logging
import os
import sys

# Third-party loggers that are noisy at DEBUG; keep them at WARNING so the
# console stays focused on this app's output.
_NOISY_LOGGERS = ("websockets", "urllib3", "asyncio")


def setup_logging(level: str = None) -> None:
    """Configure the root logger to write formatted output to the terminal."""
    level = level or os.environ.get("LOG_LEVEL", "DEBUG")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.DEBUG))
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
