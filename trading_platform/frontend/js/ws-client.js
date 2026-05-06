/**
 * ws-client.js — WebSocket client for real-time updates.
 */
const WS = {
    socket: null,
    reconnectInterval: 3000,
    handlers: {},

    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws`;

        try {
            this.socket = new WebSocket(url);
        } catch (e) {
            console.error('[WS] Connection failed:', e);
            this._updateStatus(false);
            setTimeout(() => this.connect(), this.reconnectInterval);
            return;
        }

        this.socket.onopen = () => {
            console.log('[WS] Connected');
            this._updateStatus(true);
        };

        this.socket.onclose = () => {
            console.log('[WS] Disconnected, reconnecting...');
            this._updateStatus(false);
            setTimeout(() => this.connect(), this.reconnectInterval);
        };

        this.socket.onerror = (err) => {
            console.error('[WS] Error:', err);
        };

        this.socket.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                const type = msg.type;
                if (type && this.handlers[type]) {
                    this.handlers[type].forEach(fn => {
                        try { fn(msg); } catch (e) { console.error(`[WS] Handler error for ${type}:`, e); }
                    });
                }
            } catch (e) {
                console.error('[WS] Parse error:', e);
            }
        };
    },

    on(eventType, handler) {
        if (!this.handlers[eventType]) {
            this.handlers[eventType] = [];
        }
        this.handlers[eventType].push(handler);
    },

    off(eventType) {
        delete this.handlers[eventType];
    },

    _updateStatus(connected) {
        const dot = document.getElementById('ws-status');
        const label = document.getElementById('ws-label');
        if (dot) {
            dot.classList.toggle('disconnected', !connected);
        }
        if (label) {
            label.textContent = connected ? 'Connected' : 'Reconnecting...';
        }
    }
};

// Connect on load
WS.connect();
