import faulthandler
import logging
import os
import sys
import threading

# Third-party loggers that are noisy at DEBUG; keep them at WARNING so the
# console stays focused on this app's output.
_NOISY_LOGGERS = ("websockets", "urllib3", "asyncio")

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGS_DIR = os.path.join(_REPO_ROOT, "logs")
# Native-crash stacks (SIGSEGV/SIGABRT/...) are dumped here by faulthandler, and
# unhandled Python exceptions (including those raised inside Qt slots, which
# sys.excepthook never sees) are appended by the crash handler below.
FAULT_LOG = os.path.join(_LOGS_DIR, "faulthandler.log")
CRASH_LOG = os.path.join(_LOGS_DIR, "crash.log")

# Keep the faulthandler stream open for the process lifetime.
_fault_stream = None


def _install_crash_handlers() -> None:
    """Route native crashes and unhandled exceptions to files under logs/."""
    global _fault_stream
    try:
        os.makedirs(_LOGS_DIR, exist_ok=True)
    except OSError:
        pass

    # faulthandler dumps a Python stack for every thread on a fatal signal
    # (e.g. the PortAudio heap-corruption abort) — the only way to see what a
    # hard crash was doing.
    try:
        _fault_stream = open(FAULT_LOG, "a", buffering=1, encoding="utf-8")
        faulthandler.enable(file=_fault_stream, all_threads=True)
    except OSError:
        faulthandler.enable()

    crash_logger = logging.getLogger("crash")
    if not crash_logger.handlers:
        try:
            handler = logging.FileHandler(CRASH_LOG, encoding="utf-8")
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            crash_logger.addHandler(handler)
        except OSError:
            pass

    def _excepthook(exc_type, exc, tb):
        crash_logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))

    def _thread_excepthook(args):
        crash_logger.critical(
            "Unhandled exception in thread %s",
            args.thread.name if args.thread is not None else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


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
    _install_crash_handlers()
