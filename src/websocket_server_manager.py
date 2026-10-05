"""Lifecycle helper for the Node.js WebSocket/web server on port 8765.

The desktop app is only a WebSocket *client* of ``websocket-server/server.js``;
this manager lets ``main.py`` start that server on demand when nothing is
already listening, and stop it again on exit.
"""

import os
import shutil
import socket
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(REPO_ROOT, "websocket-server")
LOG_PATH = os.path.join(REPO_ROOT, "logs", "websocket-server.log")

HOST = "localhost"
PORT = 8765
_IS_WINDOWS = sys.platform == "win32"


def is_server_running(host: str = HOST, port: int = PORT, timeout: float = 0.3) -> bool:
    """Return True if something is accepting connections on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class WebSocketServerManager:
    """Start the Node server if 8765 is down; stop it only if we started it."""

    def __init__(self):
        self.process = None

    def ensure_running(self, wait_seconds: float = 8.0) -> bool:
        """Ensure the server is listening on 8765.

        Returns True if the server is up (already running or freshly started),
        False if it could not be started. A server started outside the app is
        left untouched.
        """
        if is_server_running():
            return True

        node = shutil.which("node")
        if not node:
            print("[Server] node not found on PATH; start manually: "
                  "cd websocket-server && npm start")
            return False

        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
        try:
            with open(LOG_PATH, "ab") as log_file:
                self.process = subprocess.Popen(
                    [node, "server.js"],
                    cwd=SERVER_DIR,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
        except OSError as e:
            print(f"[Server] Failed to start node server: {e}")
            self.process = None
            return False

        print(f"[Server] Starting node server (pid {self.process.pid}); "
              f"logs: {LOG_PATH}")

        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if is_server_running():
                print(f"[Server] Web service ready at http://localhost:{PORT}")
                return True
            if self.process.poll() is not None:
                print(f"[Server] node server exited early (code "
                      f"{self.process.returncode}); see {LOG_PATH}")
                self.process = None
                return False
            time.sleep(0.1)

        print(f"[Server] Timed out waiting for port {PORT}; see {LOG_PATH}")
        return False

    def stop(self):
        """Terminate the server process if this manager started it."""
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
