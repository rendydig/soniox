# WebSocket Transcription Server

This Node.js WebSocket server broadcasts real-time transcription results from the Python application to web clients.

## Architecture

```
Python App (ui.py) 
    ↓ (sends transcription via WebSocket)
Node.js WebSocket Server (server.js)
    ↓ (broadcasts to all connected clients)
Web Clients (index.html)
```

## Installation

1. Navigate to the websocket-server directory:
```bash
cd websocket-server
```

2. Install dependencies:
```bash
npm install
```

## Running the Server

### Production Mode
```bash
npm start
```

### Development Mode (with auto-reload)
```bash
npm run dev
```

The server will start on:
- **WebSocket**: `ws://localhost:8765`
- **Web Interface**: `http://localhost:8765`

## Features

### Server Features
- Real-time WebSocket broadcasting
- Automatic reconnection handling
- Multiple client support
- Connection status monitoring
- Graceful shutdown

### Web Client Features
- Live transcription display
- Transcription history with timestamps
- Statistics (total transcriptions, word count)
- Export transcriptions to text file
- Clear history
- Auto-reconnect on disconnect
- Beautiful, responsive UI

## Message Format

The server expects JSON messages in the following format:

```json
{
  "type": "transcription",
  "text": "transcribed text here",
  "is_final": true,
  "timestamp": "2024-01-01T12:00:00.000Z"
}
```

- `type`: Message type (currently only "transcription")
- `text`: The transcribed text
- `is_final`: Boolean indicating if this is a final transcription or interim
- `timestamp`: ISO timestamp (added by server if not provided)

## Configuration

You can configure the server ports via environment variables:

```bash
PORT=8765 npm start
```

Default port: `8765`

## Python Integration

The Python application automatically connects to the WebSocket server when started. The connection is managed by `src/websocket_client.py`.

### Key Features:
- Automatic reconnection with 5-second delay
- Non-blocking async operation
- Thread-safe message sending
- Graceful cleanup on application close

## Accessing the Web Interface

1. Start the WebSocket server
2. Start your Python application
3. Open a browser and navigate to: `http://localhost:8765`
4. Begin transcribing - results will appear in real-time

## Troubleshooting

### Server won't start
- Check if port 8765 is already in use
- Try a different port: `PORT=8766 npm start`

### Python app can't connect
- Ensure the WebSocket server is running first
- Check the URI in `src/ui.py` matches the server port
- Look for connection logs in the Python console

### Web client shows "Disconnected"
- Refresh the browser page
- Check browser console for errors
- Ensure the server is running

## Development

To modify the web interface, edit:
- `public/index.html` - Main web client

To modify server behavior, edit:
- `server.js` - WebSocket server logic

Changes to `server.js` will auto-reload if using `npm run dev`.
