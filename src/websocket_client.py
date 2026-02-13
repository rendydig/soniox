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
        self.loop.run_until_complete(self._connect_loop())
    
    async def _connect_loop(self):
        while True:
            try:
                await self._connect()
            except Exception as e:
                print(f"[WebSocket] Connection error: {e}")
            
            if not self.connected:
                print(f"[WebSocket] Reconnecting in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
    
    async def _connect(self):
        try:
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                self.connected = True
                print(f"[WebSocket] Connected to {self.uri}")
                
                await websocket.wait_closed()
        except ConnectionClosed:
            print("[WebSocket] Connection closed")
        except Exception as e:
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
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=2)
        print("[WebSocket] Client stopped")
    
    def is_connected(self) -> bool:
        return self.connected
