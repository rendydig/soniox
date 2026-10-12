"""Lifecycle helper for the Go hub on port 8770.

Mirrors :mod:`src.websocket_server_manager`: the app starts the hub on demand
when nothing is already listening, and stops it again on exit.

With ``tie_lifecycle=True`` (what the app uses) the hub belongs to this process:
a hub already listening on the address is *adopted* instead of ignored, and on
Windows both the spawned and the adopted process are assigned to a job object
with ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``, so the kernel kills the hub
whenever this process dies — including a crash or a Task Manager kill, where
``closeEvent`` never runs.

The default (``tie_lifecycle=False``, used by ``tools/hubctl.py`` and the smoke
scripts) keeps the old behavior: a hub started that way outlives the command,
and one already running is left untouched.
"""

import ctypes
import logging
import os
import shutil
import socket
import subprocess
import sys
import time

import psutil

from src.config import (
    HUB_ADDR,
    HUB_BIN,
    HUB_ENABLED,
    HUB_EVENTS_PATH,
    HUB_HTTP_ADDR,
    HUB_SNAPSHOT_PATH,
    HUB_TOKEN,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HUB_DIR = os.path.join(REPO_ROOT, "hub")
LOG_PATH = os.path.join(REPO_ROOT, "logs", "hub.log")

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Cap on how long ensure_running() waits for the listener or the debug endpoint.
DEFAULT_WAIT_SECONDS = 10.0


def host_port(addr: str = None):
    """Split "host:port" into its parts."""
    host, _, port = (addr or HUB_ADDR).rpartition(":")
    return host or "127.0.0.1", int(port)


def is_hub_running(addr: str = None, timeout: float = 0.3) -> bool:
    """True if something is accepting connections on the hub's address."""
    host, port = host_port(addr)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def default_binary_path() -> str:
    """Where the compiled hub binary lives (``hub/hub.exe`` on Windows)."""
    return os.path.join(HUB_DIR, "hub.exe" if _IS_WINDOWS else "hub")


def resolve_binary() -> str:
    """Find the hub binary, building it from source when necessary.

    ``HUB_BIN`` wins; otherwise ``hub/hub[.exe]`` is used, and if that is
    missing a one-off ``go build`` is attempted. Returns "" when no binary is
    available (the caller then runs without a hub).
    """
    if HUB_BIN:
        if os.path.exists(HUB_BIN):
            return HUB_BIN
        logger.error("HUB_BIN=%s does not exist", HUB_BIN)
        return ""

    path = default_binary_path()
    if os.path.exists(path):
        return path

    go = shutil.which("go")
    if not go:
        logger.warning(
            "hub binary missing (%s) and `go` is not on PATH; "
            "build it with: cd hub && go build -o %s ./cmd/hub",
            path,
            os.path.basename(path),
        )
        return ""

    logger.info("Building hub binary (missing %s)", path)
    creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
    try:
        proc = subprocess.run(
            [go, "build", "-o", path, "./cmd/hub"],
            cwd=HUB_DIR,
            capture_output=True,
            text=True,
            creationflags=creationflags,
        )
    except OSError as e:
        logger.error("Failed to run go build: %s", e)
        return ""

    if proc.returncode != 0:
        logger.error("go build failed (%s): %s", proc.returncode, (proc.stderr or "").strip())
        return ""

    logger.info("Built hub binary at %s", path)
    return path


def find_listener_pid(addr: str = None):
    """The pid owning the LISTEN socket on the hub's address, or None."""
    _, port = host_port(addr)
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError) as e:
        logger.debug("net_connections failed: %s", e)
        return None
    for conn in connections:
        if conn.status == psutil.CONN_LISTEN and conn.pid and conn.laddr.port == port:
            return conn.pid
    return None


def looks_like_our_hub(pid: int) -> bool:
    """True when the process is a hub binary from this checkout.

    Name first, then path: the compiled binary (``HUB_BIN`` / ``hub/hub[.exe]``)
    or anything else running out of ``hub/``. A hub binary built elsewhere counts
    only when it was pointed at our address, so a foreign listener is never
    mistaken for ours.
    """
    try:
        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        exe = proc.exe()
        cmdline = proc.cmdline()
    except (psutil.Error, OSError) as e:
        logger.debug("Cannot inspect pid %s: %s", pid, e)
        return False

    if name not in ("hub", "hub.exe"):
        return False

    if exe:
        exe_norm = os.path.normcase(os.path.abspath(exe))
        for candidate in (HUB_BIN, default_binary_path()):
            if candidate and exe_norm == os.path.normcase(os.path.abspath(candidate)):
                return True
        if exe_norm.startswith(os.path.normcase(os.path.abspath(HUB_DIR)) + os.sep):
            return True

    return HUB_ADDR in cmdline


# --- Windows job object ---------------------------------------------------
#
# A hub started as a child only dies on closeEvent; a crash or a Task Manager
# kill leaves it listening forever (which is exactly how the hub survived the
# 08:52 crash). Assigning it to a job object with KILL_ON_JOB_CLOSE moves that
# guarantee into the kernel: when this process goes away — however it goes away
# — the handle is closed and the hub dies with it.

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


if _IS_WINDOWS:
    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            (field, ctypes.c_uint64)
            for field in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _KERNEL32.CreateJobObjectW.restype = ctypes.c_void_p
    _KERNEL32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    _KERNEL32.SetInformationJobObject.restype = ctypes.c_int
    _KERNEL32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    _KERNEL32.OpenProcess.restype = ctypes.c_void_p
    _KERNEL32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _KERNEL32.AssignProcessToJobObject.restype = ctypes.c_int
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
    _KERNEL32.CloseHandle.restype = ctypes.c_int


def create_kill_on_close_job():
    """Create a job object whose members die when this process does."""
    if not _IS_WINDOWS:
        return None

    job = _KERNEL32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("CreateJobObject failed (err %s)", ctypes.get_last_error())
        return None

    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _KERNEL32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        logger.warning("SetInformationJobObject failed (err %s)", ctypes.get_last_error())
        _KERNEL32.CloseHandle(job)
        return None
    return job


def assign_to_job(job, pid: int) -> bool:
    """Put an existing process into ``job`` (spawned or adopted)."""
    if not job:
        return False

    handle = _KERNEL32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, int(pid))
    if not handle:
        logger.warning(
            "OpenProcess(%s) failed (err %s); hub is not bound to this process",
            pid,
            ctypes.get_last_error(),
        )
        return False

    try:
        if not _KERNEL32.AssignProcessToJobObject(job, handle):
            # Nested jobs need Windows 8+; on failure the hub still dies on
            # closeEvent, it just is not protected against a crash.
            logger.warning(
                "AssignProcessToJobObject(%s) failed (err %s); hub is not bound to this process",
                pid,
                ctypes.get_last_error(),
            )
            return False
        return True
    finally:
        _KERNEL32.CloseHandle(handle)


def close_job(job):
    """Close the job handle, which terminates every process still in it."""
    if job and _IS_WINDOWS:
        _KERNEL32.CloseHandle(job)


class HubManager:
    """Start the hub if 8770 is down; stop it only if we own it.

    ``tie_lifecycle`` binds the hub to this process (see the module docstring):
    a hub already listening is adopted rather than ignored, and on Windows it is
    put in a job object so it dies with us. Left off, the hub is only stopped
    when this manager started it.
    """

    def __init__(self, addr: str = None, tie_lifecycle: bool = False):
        self.addr = addr or HUB_ADDR
        self.tie_lifecycle = tie_lifecycle
        self.process = None
        self.binary = ""
        self.adopted_pid = None
        self._job = None

    def ensure_running(self, wait_seconds: float = DEFAULT_WAIT_SECONDS) -> bool:
        """Ensure the hub is listening. Returns True when it is up."""
        if not HUB_ENABLED:
            logger.info("Hub disabled (HUB_ENABLED=false)")
            return False

        if is_hub_running(self.addr):
            if not self.tie_lifecycle:
                logger.info("Hub already running on %s", self.addr)
                return True
            return self._adopt_running()

        self.binary = resolve_binary()
        if not self.binary:
            return False

        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(HUB_EVENTS_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(HUB_SNAPSHOT_PATH), exist_ok=True)

        args = [
            self.binary,
            "-addr", self.addr,
            "-http", HUB_HTTP_ADDR or "-",
            "-events", HUB_EVENTS_PATH,
            "-snapshot", HUB_SNAPSHOT_PATH,
        ]
        if HUB_TOKEN:
            args += ["-token", HUB_TOKEN]

        creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
        try:
            with open(LOG_PATH, "ab") as log_file:
                self.process = subprocess.Popen(
                    args,
                    cwd=HUB_DIR,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
        except OSError as e:
            logger.error("Failed to start hub: %s", e)
            self.process = None
            return False

        logger.info("Starting hub (pid %s) on %s; logs: %s", self.process.pid, self.addr, LOG_PATH)
        if self.tie_lifecycle:
            self._bind_to_process(self.process.pid, "hub")

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if is_hub_running(self.addr):
                logger.info("Hub ready at %s", self.addr)
                return True
            if self.process.poll() is not None:
                logger.error(
                    "hub exited early (code %s); see %s", self.process.returncode, LOG_PATH
                )
                self.process = None
                return False
            time.sleep(0.1)

        logger.warning("Timed out waiting for the hub on %s; see %s", self.addr, LOG_PATH)
        return False

    def stop(self):
        """Terminate the hub if this manager owns it."""
        if self.process is not None:
            self._terminate(self.process.pid, "hub")
            self.process = None
        if self.adopted_pid is not None:
            self._terminate(self.adopted_pid, "adopted hub")
            self.adopted_pid = None
        if self._job is not None:
            close_job(self._job)
            self._job = None

    # --- internals ----------------------------------------------------

    def _adopt_running(self) -> bool:
        """Take over a hub already listening on our address.

        Returns True whenever the address is usable, so a listener we cannot
        attribute (someone else's process) is left running exactly as before.
        """
        pid = find_listener_pid(self.addr)
        if pid is None:
            logger.warning(
                "Something is listening on %s but its pid is unknown; leaving it alone", self.addr
            )
            return True
        if not looks_like_our_hub(pid):
            logger.warning(
                "Port %s is held by pid %s, which is not one of our hubs; leaving it alone",
                self.addr,
                pid,
            )
            return True

        self.adopted_pid = pid
        logger.info("Adopting hub pid %s on %s", pid, self.addr)
        self._bind_to_process(pid, "adopted hub")
        return True

    def _bind_to_process(self, pid: int, label: str):
        """Put the hub in a job object that dies with this process (Windows)."""
        if not _IS_WINDOWS:
            return
        if self._job is None:
            self._job = create_kill_on_close_job()
        if self._job is None:
            return
        if assign_to_job(self._job, pid):
            logger.info("Bound %s (pid %s) to this process; it dies with the app", label, pid)

    @staticmethod
    def _terminate(pid: int, label: str):
        """Terminate one process, escalating to kill() if it lingers."""
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
        except psutil.NoSuchProcess:
            return
        except psutil.TimeoutExpired:
            logger.warning("%s (pid %s) did not exit; killing it", label, pid)
            try:
                proc.kill()
            except psutil.Error:
                pass
        except psutil.Error as e:
            logger.warning("Cannot stop %s (pid %s): %s", label, pid, e)
