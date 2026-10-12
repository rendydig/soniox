"""Thread-safe client for the Go hub.

Mirrors :class:`src.websocket_client.WebSocketClient`: one background thread
owning an asyncio event loop, with thread-safe senders built on
``run_coroutine_threadsafe`` so any thread (including the Qt main thread) can
publish without touching the loop. Inbound messages are handed to the
registered handler on the loop thread; Qt code marshals them onto the main
thread with a ``Signal``, exactly as it does for the browser WebSocket.
"""

import asyncio
import concurrent.futures
import logging
import threading
from typing import Callable, Optional

from src.config import HUB_ADDR, HUB_TOKEN
from src.hub import protocol

logger = logging.getLogger(__name__)


class HubClient:
    """A reconnecting NDJSON client for the hub."""

    def __init__(
        self,
        addr: str = None,
        token: str = None,
        role: str = protocol.ROLE_UI,
        name: str = "desktop",
        reconnect_delay: float = 2.0,
    ):
        self.addr = addr or HUB_ADDR
        host, _, port = self.addr.rpartition(":")
        self.host = host or "127.0.0.1"
        self.port = int(port)
        self.token = HUB_TOKEN if token is None else token
        self.role = role
        self.name = name
        self.reconnect_delay = reconnect_delay

        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.connected = False

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._stop_flag = False
        self._message_handler: Optional[Callable[[dict], None]] = None

        # id -> Future, filled by the loop thread, read by request()'s caller.
        self._pending: dict = {}
        self._pending_lock = threading.Lock()

    # --- lifecycle ----------------------------------------------------

    def set_message_handler(self, handler: Callable[[dict], None]):
        """Register a callback invoked with each inbound message (loop thread)."""
        self._message_handler = handler

    def start(self):
        """Start the background connection loop (idempotent)."""
        if self.thread and self.thread.is_alive():
            logger.info("Hub client already running")
            return
        self._stop_flag = False
        self.thread = threading.Thread(target=self._run_loop, name="hub-client", daemon=True)
        self.thread.start()
        logger.info("Hub client started, connecting to %s", self.addr)

    def stop(self):
        """Close the connection and join the background thread."""
        self._stop_flag = True
        if self._writer is not None and self.loop and self.loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._close_writer(), self.loop)
                future.result(timeout=2)
            except Exception:
                pass
        self.connected = False
        self._fail_pending(ConnectionError("hub client stopped"))
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        logger.info("Hub client stopped")

    def is_connected(self) -> bool:
        return self.connected

    # --- senders (callable from any thread) ---------------------------

    def publish(self, topic: str, payload: dict = None) -> bool:
        """Publish one topic into the hub."""
        return self._send(protocol.envelope(protocol.PUBLISH, topic=topic, payload=payload or {}))

    def subscribe(self, topics) -> bool:
        """Subscribe this connection to one or more topic patterns."""
        return self._send(protocol.envelope(protocol.SUBSCRIBE, topics=list(topics)))

    def unsubscribe(self, topics) -> bool:
        return self._send(protocol.envelope(protocol.UNSUBSCRIBE, topics=list(topics)))

    def send_result(self, job_id: str, payload: dict) -> bool:
        """Return a finished job's result (agents)."""
        return self._send(protocol.envelope(protocol.RESULT, job_id=job_id, payload=payload or {}))

    def send_result_chunk(self, job_id: str, text: str) -> bool:
        """Stream one partial result (agents)."""
        return self._send(protocol.envelope(protocol.RESULT_CHUNK, job_id=job_id, text=text))

    def request(self, op: str, params: dict = None, timeout: float = 5.0) -> Optional[dict]:
        """Send a request and block for its response (``None`` on timeout)."""
        if not self.is_connected():
            return None
        request_id = protocol.new_id()
        future: "concurrent.futures.Future" = concurrent.futures.Future()
        with self._pending_lock:
            self._pending[request_id] = future
        try:
            if not self._send(protocol.envelope(protocol.REQUEST, id=request_id, op=op, payload=params or {})):
                return None
            return future.result(timeout=timeout)
        except Exception as e:
            logger.warning("Hub request %s failed: %s", op, e)
            return None
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    # --- internals ----------------------------------------------------

    def _send(self, message: dict) -> bool:
        if not self.connected or not self.loop:
            logger.debug("Hub not connected, skipping %s", message.get("type"))
            return False
        try:
            future = asyncio.run_coroutine_threadsafe(self._write(message), self.loop)
        except RuntimeError as e:
            logger.debug("Hub loop unavailable: %s", e)
            return False
        future.add_done_callback(self._log_send_error)
        return True

    @staticmethod
    def _log_send_error(future):
        try:
            error = future.exception()
        except Exception:
            return
        if error is not None:
            logger.warning("Hub send error: %s", error)

    async def _write(self, message: dict):
        writer = self._writer
        if writer is None:
            return
        try:
            writer.write(protocol.encode(message))
            await writer.drain()
        except Exception as e:
            logger.error("Hub write failed: %s", e)
            self.connected = False

    async def _close_writer(self):
        writer, self._writer = self._writer, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect_loop())
        except Exception as e:
            if not self._stop_flag:
                logger.error("Hub event loop error: %s", e)
        finally:
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                try:
                    self.loop.close()
                except Exception:
                    pass

    async def _connect_loop(self):
        while not self._stop_flag:
            try:
                await self._connect()
            except Exception as e:
                if not self._stop_flag:
                    logger.debug("Hub connection error: %s", e)
            if self._stop_flag:
                break
            await self._sleep(self.reconnect_delay)

    async def _sleep(self, seconds: float):
        """Sleep in small slices so stop() is not delayed by the backoff."""
        steps = max(1, int(seconds / 0.1))
        for _ in range(steps):
            if self._stop_flag:
                return
            await asyncio.sleep(0.1)

    async def _connect(self):
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port, limit=protocol.MAX_LINE_BYTES
            )
        except OSError as e:
            logger.debug("Hub connect to %s failed: %s", self.addr, e)
            return

        try:
            await self._write(
                protocol.envelope(
                    protocol.HELLO, role=self.role, name=self.name, token=self.token
                )
            )
            line = await asyncio.wait_for(self._reader.readline(), timeout=5.0)
            reply = protocol.decode(line) if line else {}
            if reply.get("type") != protocol.HELLO_OK:
                logger.warning("Hub rejected handshake: %s", reply.get("error") or reply.get("type"))
                return

            self.connected = True
            logger.info("Connected to hub at %s as %s", self.addr, self.role)
            await self._reader_loop()
        finally:
            self.connected = False
            self._fail_pending(ConnectionError("hub connection lost"))
            await self._close_writer()

    async def _reader_loop(self):
        while not self._stop_flag:
            line = await self._reader.readline()
            if not line:
                logger.info("Hub connection closed by peer")
                return
            try:
                message = protocol.decode(line)
            except ValueError as e:
                logger.warning("Dropping malformed hub frame: %s", e)
                continue

            if message.get("type") == protocol.RESPONSE:
                self._resolve(message)
                continue

            handler = self._message_handler
            if handler is None:
                continue
            try:
                handler(message)
            except Exception:
                logger.exception("Hub message handler failed for %s", message.get("type"))

    def _resolve(self, message: dict):
        with self._pending_lock:
            future = self._pending.get(message.get("id"))
        if future is None or future.done():
            return
        future.set_result(message)

    def _fail_pending(self, error: BaseException):
        with self._pending_lock:
            pending = list(self._pending.values())
        for future in pending:
            if not future.done():
                future.set_exception(error)
