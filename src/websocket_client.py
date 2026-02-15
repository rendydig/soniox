import asyncio
import json
import threading
from typing import Optional
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException


class WebSocketClient:
    def __init__(self, uri: str = "ws://localhost:8765"):
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.connected = False
        self.reconnect_delay = 5
        self._stop_flag = False
        
    def start(self):
        if self.thread and self.thread.is_alive():
            print("[WebSocket] Client already running")
            return
            
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        print(f"[WebSocket] Client started, connecting to {self.uri}")
    
    def _run_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._connect_loop())
        except Exception as e:
            if not self._stop_flag:
                print(f"[WebSocket] Event loop error: {e}")
        finally:
            # Cancel all pending tasks
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                # Wait for all tasks to complete cancellation
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                try:
                    self.loop.close()
                except:
                    pass
    
    async def _connect_loop(self):
        while not self._stop_flag:
            try:
                await self._connect()
            except Exception as e:
                if not self._stop_flag:
                    print(f"[WebSocket] Connection error: {e}")
            
            if not self.connected and not self._stop_flag:
                print(f"[WebSocket] Reconnecting in {self.reconnect_delay} seconds...")
                for _ in range(self.reconnect_delay * 10):
                    if self._stop_flag:
                        break
                    await asyncio.sleep(0.1)
    
    async def _connect(self):
        try:
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                self.connected = True
                print(f"[WebSocket] Connected to {self.uri}")
                
                while not self._stop_flag:
                    try:
                        await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except ConnectionClosed:
                        break
        except ConnectionClosed:
            if not self._stop_flag:
                print("[WebSocket] Connection closed")
        except Exception as e:
            if not self._stop_flag:
                print(f"[WebSocket] Connection failed: {e}")
        finally:
            self.connected = False
            self.websocket = None
    
    def send_transcription(self, text: str, is_final: bool, additional_data: dict = None, message_type: str = "transcription"):
        if not self.connected or not self.loop:
            print("[WebSocket] Not connected, skipping send")
            return
        
        message = {
            "type": message_type,
            "text": text,
            "is_final": is_final,
            "timestamp": None
        }
        
        if additional_data:
            message.update(additional_data)
        
        asyncio.run_coroutine_threadsafe(
            self._send_message(message),
            self.loop
        )
    
    async def _send_message(self, message: dict):
        if self.websocket and self.connected:
            try:
                await self.websocket.send(json.dumps(message))
                print(f"[WebSocket] Sent: {message['type']} - is_final={message.get('is_final')}")
            except Exception as e:
                print(f"[WebSocket] Send error: {e}")
                self.connected = False
    
    def stop(self):
        self._stop_flag = True
        self.connected = False
        
        # Close websocket connection
        if self.websocket and self.loop and self.loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
                future.result(timeout=2)
            except Exception:
                pass
        
        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        
        print("[WebSocket] Client stopped")
    
    def is_connected(self) -> bool:
        return self.connected
