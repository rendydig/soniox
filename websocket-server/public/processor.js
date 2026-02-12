let ws;
let transcriptions = [];
let reconnectInterval;
let currentSentence = null;

function connect() {
    const wsUrl = `ws://${window.location.hostname}:${window.location.port || 8765}`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('[WebSocket] Connected');
        updateStatus(true);
        if (reconnectInterval) {
            clearInterval(reconnectInterval);
            reconnectInterval = null;
        }
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleMessage(data);
        } catch (error) {
            console.error('[WebSocket] Parse error:', error);
        }
    };

    ws.onclose = () => {
        console.log('[WebSocket] Disconnected');
        updateStatus(false);
        if (!reconnectInterval) {
            reconnectInterval = setInterval(() => {
                console.log('[WebSocket] Attempting to reconnect...');
                connect();
            }, 3000);
        }
    };

    ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error);
    };
}

function handleMessage(data) {
    if (data.type === 'connection') {
        console.log('[WebSocket]', data.message);
        return;
    }

    if (data.type === 'transcription') {
        if (data.is_final) {
            addTranscription(data.text, data.timestamp);
            document.getElementById('liveText').textContent = 'Waiting for audio input...';
            document.getElementById('liveText').classList.remove('active');
        } else {
            document.getElementById('liveText').textContent = data.text || 'Listening...';
            document.getElementById('liveText').classList.add('active');
        }
    }
}

function endsWithSentenceTerminator(text) {
    if (!text || text.length === 0) return false;
    const trimmed = text.trim();
    const lastChar = trimmed[trimmed.length - 1];
    return lastChar === '.' || lastChar === '!' || lastChar === '?';
}

function endsWithContinuation(text) {
    if (!text || text.length === 0) return false;
    const trimmed = text.trim();
    const lastChar = trimmed[trimmed.length - 1];
    return lastChar === ',' || lastChar === ';';
}

function addTranscription(text, timestamp) {
    if (!text || text.trim().length === 0) return;

    const trimmedText = text.trim();
    const isSentenceEnd = endsWithSentenceTerminator(trimmedText);
    const isContinuation = endsWithContinuation(trimmedText);

    if (currentSentence === null) {
        currentSentence = {
            text: trimmedText,
            timestamp: timestamp,
            isComplete: isSentenceEnd
        };
    } else {
        currentSentence.text += ' ' + trimmedText;
        currentSentence.timestamp = timestamp;
        currentSentence.isComplete = isSentenceEnd;
    }

    if (isSentenceEnd) {
        transcriptions.unshift({
            text: currentSentence.text,
            timestamp: currentSentence.timestamp
        });
        currentSentence = null;
    }

    renderTranscriptions();
}

function renderTranscriptions() {
    const listElement = document.getElementById('transcriptionList');
    listElement.innerHTML = '';

    const allItems = [];
    
    if (currentSentence !== null && !currentSentence.isComplete) {
        allItems.push({
            text: currentSentence.text,
            timestamp: currentSentence.timestamp,
            isIncomplete: true
        });
    }

    allItems.push(...transcriptions);

    if (allItems.length === 0) {
        listElement.innerHTML = `
            <div class="empty-state">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path>
                </svg>
                <p>No transcriptions yet</p>
            </div>
        `;
    } else {
        allItems.forEach(item => {
            const div = document.createElement('div');
            div.className = 'transcription-item';
            if (item.isIncomplete) {
                div.style.opacity = '0.7';
                div.style.borderLeftColor = '#f59e0b';
            }
            div.innerHTML = `
                <div class="transcription-text">${escapeHtml(item.text)}</div>
                <div class="transcription-time">${formatTime(item.timestamp)}</div>
            `;
            listElement.appendChild(div);
        });
    }

    updateStats();
}

function updateStats() {
    document.getElementById('totalCount').textContent = transcriptions.length;
    const totalWords = transcriptions.reduce((sum, item) =>
        sum + item.text.split(/\s+/).filter(w => w.length > 0).length, 0
    );
    document.getElementById('wordCount').textContent = totalWords;
}

function updateStatus(connected) {
    const indicator = document.getElementById('statusIndicator');
    const text = document.getElementById('statusText');

    if (connected) {
        indicator.classList.add('connected');
        text.textContent = 'Connected';
    } else {
        indicator.classList.remove('connected');
        text.textContent = 'Disconnected - Reconnecting...';
    }
}

function clearTranscriptions() {
    if (confirm('Clear all transcriptions?')) {
        transcriptions = [];
        currentSentence = null;
        renderTranscriptions();
    }
}

function exportTranscriptions() {
    if (transcriptions.length === 0) {
        alert('No transcriptions to export');
        return;
    }

    const content = transcriptions
        .map(item => `[${formatTime(item.timestamp)}] ${item.text}`)
        .join('\n\n');

    const blob = new Blob([content], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `transcription_${new Date().toISOString().slice(0, 10)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
}

function formatTime(timestamp) {
    if (!timestamp) return 'Just now';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

connect();