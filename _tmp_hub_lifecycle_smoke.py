"""Throwaway smoke test for the hub's process lifetime.

The app owns the hub (``HubManager(tie_lifecycle=True)``): it adopts a hub
already listening instead of ignoring it, kills it on stop, and — through a
Windows job object — dies with the app even when the app is killed outright.
``tools/hubctl.py`` and the other smoke scripts keep the old semantics, where a
hub they start outlives the command.

Runs on a throwaway port and temp artefact paths, so the real hub on 8770 is
never touched.

    venv/Scripts/python.exe _tmp_hub_lifecycle_smoke.py

Exit codes: 0 = every check passed, 1 = a check failed.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

_TMP = tempfile.mkdtemp(prefix="hub-lifecycle-")


def _free_ports(count: int = 2):
    """Distinct free loopback ports (all sockets held until the ports are picked)."""
    socks = [socket.socket() for _ in range(count)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


_ADDR_PORT, _HTTP_PORT = _free_ports()

# Redirect everything into the temp dir (and off the real ports) before
# src.config is imported.
os.environ["HUB_ADDR"] = f"127.0.0.1:{_ADDR_PORT}"
os.environ["HUB_HTTP_ADDR"] = f"127.0.0.1:{_HTTP_PORT}"
os.environ["HUB_EVENTS_PATH"] = os.path.join(_TMP, "hub-events.jsonl")
os.environ["HUB_SNAPSHOT_PATH"] = os.path.join(_TMP, "hub-state.json")
os.environ["SMOKE_REPO_ROOT"] = REPO_ROOT

import psutil  # noqa: E402

from src.config import HUB_ADDR, HUB_EVENTS_PATH, HUB_HTTP_ADDR, HUB_SNAPSHOT_PATH  # noqa: E402
from src.hub.manager import (  # noqa: E402
    HubManager,
    find_listener_pid,
    is_hub_running,
    looks_like_our_hub,
    resolve_binary,
)

PASSED = []
FAILED = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        PASSED.append(label)
        print(f"  ok   {label}")
    else:
        FAILED.append(label)
        print(f"  FAIL {label}{(' — ' + detail) if detail else ''}")


def wait_for(predicate, timeout: float = 5.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def child_env() -> dict:
    return dict(os.environ)


def write_child(name: str, source: str) -> str:
    path = os.path.join(_TMP, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return path


def spawn_hub_manually():
    """Start a hub the way ``hubctl`` or a terminal would (no tie_lifecycle)."""
    args = [
        resolve_binary(),
        "-addr", HUB_ADDR,
        "-http", HUB_HTTP_ADDR,
        "-events", HUB_EVENTS_PATH,
        "-snapshot", HUB_SNAPSHOT_PATH,
    ]
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_pid(pid):
    try:
        psutil.Process(pid).kill()
    except psutil.Error:
        pass


# --- cases -------------------------------------------------------------------


def case_clean_stop():
    print("\n[clean stop]")
    manager = HubManager(tie_lifecycle=True)
    check("spawns the hub", manager.ensure_running())
    check("hub is listening", is_hub_running())
    check("the manager owns the child process", manager.process is not None)
    pid = manager.process.pid if manager.process else None

    manager.stop()
    check("hub is gone after stop()", wait_for(lambda: not is_hub_running(), timeout=5.0))
    check(
        "the hub process is gone",
        pid is None or wait_for(lambda: not psutil.pid_exists(pid), timeout=5.0),
    )


def case_crash_kills_hub():
    print("\n[crash / force-kill]")
    child = write_child("crash_child.py", '''
import os
import sys

sys.path.insert(0, os.environ["SMOKE_REPO_ROOT"])
from src.hub.manager import HubManager

manager = HubManager(tie_lifecycle=True)
if not manager.ensure_running():
    print("child could not start the hub", file=sys.stderr)
    os._exit(2)
print(manager.process.pid, flush=True)
os._exit(1)  # dies without closeEvent: only the job object can clean this up
''')
    proc = subprocess.run(
        [sys.executable, child], capture_output=True, text=True, env=child_env(), timeout=60
    )
    lines = (proc.stdout or "").strip().splitlines()
    hub_pid = int(lines[-1]) if lines and lines[-1].strip().isdigit() else None
    check("the child started a hub and then died", hub_pid is not None, (proc.stderr or "").strip())
    if hub_pid is None:
        return
    check(
        "the hub dies with the process that started it",
        wait_for(lambda: not psutil.pid_exists(hub_pid), timeout=10.0),
        f"pid {hub_pid} survived",
    )
    check("the port is released", wait_for(lambda: not is_hub_running(), timeout=5.0))
    kill_pid(hub_pid)


def case_adopt_and_kill():
    print("\n[adopt an already running hub]")
    hand = spawn_hub_manually()
    try:
        check("a hand-started hub comes up", wait_for(lambda: is_hub_running(), timeout=10.0))
        if not is_hub_running():
            return
        check("it is recognised as our hub", looks_like_our_hub(hand.pid))
        check("its pid is discoverable from the port", find_listener_pid() == hand.pid)

        manager = HubManager(tie_lifecycle=True)
        check("the manager adopts it", manager.ensure_running())
        check("no second hub was spawned", manager.process is None)
        check("the adopted pid is the hand-started one", manager.adopted_pid == hand.pid)

        manager.stop()
        try:
            hand.wait(timeout=5)
            exited = True
        except subprocess.TimeoutExpired:
            exited = False
        check("the adopted hub is terminated", exited)
        check("the port is released", wait_for(lambda: not is_hub_running(), timeout=5.0))
    finally:
        kill_pid(hand.pid)


def case_foreign_listener_is_left_alone():
    print("\n[foreign listener]")
    foreign = write_child("foreign_listener.py", '''
import os
import socket
import time

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", int(os.environ["HUB_ADDR"].rsplit(":", 1)[1])))
server.listen(5)
print(os.getpid(), flush=True)
time.sleep(60)
''')
    proc = subprocess.Popen(
        [sys.executable, foreign],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=child_env(),
    )
    try:
        pid = int(proc.stdout.readline().strip())
        check("a non-hub process holds the port", wait_for(lambda: is_hub_running(), timeout=5.0))
        check("it is not mistaken for our hub", not looks_like_our_hub(pid))

        manager = HubManager(tie_lifecycle=True)
        check("the manager still reports the address usable", manager.ensure_running())
        check("but it adopts nothing", manager.adopted_pid is None)
        manager.stop()
        check("and it is not killed by stop()", psutil.pid_exists(pid))
    finally:
        kill_pid(proc.pid)
        proc.wait(timeout=5)


def case_hubctl_still_outlives_the_command():
    print("\n[hubctl unaffected]")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "tools", "hubctl.py"), "state", "--summary"],
        capture_output=True,
        text=True,
        env=child_env(),
        timeout=90,
    )
    check("hubctl state succeeds", result.returncode == 0, (result.stderr or "").strip())
    check("hubctl reports the session", "session" in (result.stdout or ""))
    check("the hub outlives the hubctl command", is_hub_running())

    pid = find_listener_pid()
    check("the leftover hub is a hub we can find", pid is not None and looks_like_our_hub(pid))
    kill_pid(pid)
    check("cleanup leaves the port free", wait_for(lambda: not is_hub_running(), timeout=5.0))


def main() -> int:
    print(f"temp dir: {_TMP}")
    print(f"throwaway hub: {HUB_ADDR} (debug HTTP {HUB_HTTP_ADDR}); 127.0.0.1:8770 untouched")

    if is_hub_running():
        raise SystemExit(f"something is already listening on {HUB_ADDR}; pick another port")

    case_clean_stop()
    case_crash_kills_hub()
    case_adopt_and_kill()
    case_foreign_listener_is_left_alone()
    case_hubctl_still_outlives_the_command()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for label in FAILED:
        print(f"  failed: {label}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
