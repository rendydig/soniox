const WebSocket = require('ws');
const http = require('http');
const express = require('express');
const path = require('path');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

const PORT = process.env.PORT || 8765;
const WEB_PORT = process.env.WEB_PORT || 3000;

const clients = new Set();

app.use(express.static(path.join(__dirname, 'public')));

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

wss.on('connection', (ws, req) => {
  const clientIp = req.socket.remoteAddress;
  console.log(`[WebSocket] New connection from ${clientIp}`);
  
  clients.add(ws);
  console.log(`[WebSocket] Total clients: ${clients.size}`);
  
  ws.send(JSON.stringify({
    type: 'connection',
    message: 'Connected to transcription server',
    timestamp: new Date().toISOString()
  }));
  
  ws.on('message', (data) => {
    try {
      const message = JSON.parse(data.toString());
      console.log(`[WebSocket] Received: ${message.type} - is_final=${message.is_final}`);
      
      message.timestamp = new Date().toISOString();
      
      const broadcastData = JSON.stringify(message);
      let broadcastCount = 0;
      
      clients.forEach((client) => {
        if (client !== ws && client.readyState === WebSocket.OPEN) {
          client.send(broadcastData);
          broadcastCount++;
        }
      });
      
      console.log(`[WebSocket] Broadcasted to ${broadcastCount} clients`);
      
    } catch (error) {
      console.error('[WebSocket] Error processing message:', error);
    }
  });
  
  ws.on('close', () => {
    clients.delete(ws);
    console.log(`[WebSocket] Client disconnected. Total clients: ${clients.size}`);
  });
  
  ws.on('error', (error) => {
    console.error('[WebSocket] Error:', error);
    clients.delete(ws);
  });
});

server.listen(PORT, () => {
  console.log(`[Server] WebSocket server running on ws://localhost:${PORT}`);
  console.log(`[Server] Web interface available at http://localhost:${PORT}`);
  console.log(`[Server] Waiting for connections...`);
});

process.on('SIGINT', () => {
  console.log('\n[Server] Shutting down gracefully...');
  wss.clients.forEach((client) => {
    client.close();
  });
  server.close(() => {
    console.log('[Server] Server closed');
    process.exit(0);
  });
});
