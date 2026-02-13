export class WebSocketManager {
    constructor(onStatusChange, onMessage) {
        this.ws = null;
        this.reconnectInterval = null;
        this.onStatusChange = onStatusChange;
        this.onMessage = onMessage;
    }

    connect() {
        const wsUrl = `ws://${window.location.hostname}:${window.location.port || 8765}`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('[WebSocket] Connected');
            this.onStatusChange(true);
            if (this.reconnectInterval) {
                clearInterval(this.reconnectInterval);
                this.reconnectInterval = null;
            }
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.onMessage(data);
            } catch (error) {
                console.error('[WebSocket] Parse error:', error);
            }
        };

        this.ws.onclose = () => {
            console.log('[WebSocket] Disconnected');
            this.onStatusChange(false);
            if (!this.reconnectInterval) {
                this.reconnectInterval = setInterval(() => {
                    console.log('[WebSocket] Attempting to reconnect...');
                    this.connect();
                }, 3000);
            }
        };

        this.ws.onerror = (error) => {
            console.error('[WebSocket] Error:', error);
        };
    }

    disconnect() {
        if (this.reconnectInterval) {
            clearInterval(this.reconnectInterval);
        }
        if (this.ws) {
            this.ws.close();
        }
    }
}
