# WebSocket Streaming Setup Guide

This guide explains how to set up and use the WebSocket streaming feature to broadcast transcription results to web clients.

## Quick Start

### 1. Install Node.js Dependencies

```bash
cd websocket-server
npm install
```

### 2. Start the WebSocket Server

```bash
npm start
```

You should see:
```
[Server] WebSocket server running on ws://localhost:8765
[Server] Web interface available at http://localhost:8765
[Server] Waiting for connections...
```

### 3. Start Your Python Application

```bash
python main.py
```

The Python app will automatically connect to the WebSocket server. Look for this log:
```
[WebSocket] Client started, connecting to ws://localhost:8765
[WebSocket] Connected to ws://localhost:8765
```

### 4. Open the Web Interface

Open your browser and navigate to:
```
http://localhost:8765
```

You should see the "Live Transcription Monitor" interface with a green "Connected" status.

### 5. Start Transcribing

Use your Python application as normal. All transcription results will automatically stream to the web interface in real-time!

## Architecture Overview

```
┌─────────────────────┐
│   Python App        │
│   (ui.py)           │
│                     │
│  - Captures audio   │
│  - Transcribes      │
│  - Sends to WS      │
└──────────┬──────────┘
           │ WebSocket Client
           │ (websocket_client.py)
           ↓
┌─────────────────────┐
│  Node.js Server     │
│  (server.js)        │
│                     │
│  - Receives data    │
│  - Broadcasts       │
└──────────┬──────────┘
           │ Broadcasts to all clients
           ↓
┌─────────────────────┐
│  Web Clients        │
│  (Browser)          │
│                     │
│  - Display live     │
│  - Show history     │
│  - Export data      │
└─────────────────────┘
```

## Files Created

### Python Side
- **`src/websocket_client.py`** - WebSocket client that sends transcription data
  - Auto-reconnects on disconnect
  - Thread-safe async operations
  - Integrated into `src/ui.py`

### Node.js Server
- **`websocket-server/server.js`** - Main WebSocket server
- **`websocket-server/package.json`** - Node.js dependencies
- **`websocket-server/public/index.html`** - Web client interface
- **`websocket-server/README.md`** - Detailed server documentation

## Features

### Real-time Streaming
- **Live text**: Shows interim transcription results as they arrive
- **Final text**: Displays completed transcriptions with timestamps
- **Auto-update**: No refresh needed, updates appear instantly

### Web Interface Features
- 📊 **Statistics**: Total transcriptions and word count
- 📜 **History**: Scrollable list of all transcriptions
- 💾 **Export**: Download transcriptions as text file
- 🗑️ **Clear**: Remove all history
- 🔄 **Auto-reconnect**: Automatically reconnects if disconnected

## Configuration

### Change WebSocket Port

If port 8765 is in use, you can change it:

**In the Node.js server:**
```bash
PORT=8766 npm start
```

**In the Python app** (`src/ui.py` line 31):
```python
self.websocket_client = WebSocketClient("ws://localhost:8766")
```

## Troubleshooting

### "Disconnected - Reconnecting..." in web interface
- **Cause**: WebSocket server is not running
- **Solution**: Start the server with `npm start` in the `websocket-server` directory

### Python app shows "[WebSocket] Not connected, skipping send"
- **Cause**: Server not running or connection failed
- **Solution**: 
  1. Start the WebSocket server first
  2. Then start the Python app
  3. Check for firewall blocking port 8765

### Port already in use
- **Error**: `EADDRINUSE: address already in use`
- **Solution**: 
  - Kill the process using port 8765: `lsof -ti:8765 | xargs kill -9`
  - Or use a different port (see Configuration above)

### Web page doesn't load
- **Cause**: Server not serving static files
- **Solution**: Ensure `public/index.html` exists and server is running

## Multiple Web Clients

You can open multiple browser tabs/windows to `http://localhost:8765`. All clients will receive the same transcription stream simultaneously.

## Development Tips

### Watch Server Logs
The server logs all connections and messages:
```
[WebSocket] New connection from ::1
[WebSocket] Total clients: 1
[WebSocket] Received: transcription - is_final=true
[WebSocket] Broadcasted to 0 clients
```

### Watch Python Logs
The Python app logs WebSocket activity:
```
[WebSocket] Client started, connecting to ws://localhost:8765
[WebSocket] Connected to ws://localhost:8765
[WebSocket] Sent: transcription - is_final=true
```

### Development Mode
For auto-reload during development:
```bash
cd websocket-server
npm run dev
```

## Next Steps

- Customize the web interface styling in `public/index.html`
- Add authentication if deploying publicly
- Implement message filtering or processing in `server.js`
- Add more data fields to the transcription messages

## Support

For detailed server documentation, see `websocket-server/README.md`.
