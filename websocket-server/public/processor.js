import { h, render, Component } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from './websocket-manager.js';

const html = htm.bind(h);

const MAX_LIVE_LINES = 5;

function endsWithSentenceTerminator(text) {
    if (!text || text.length === 0) return false;
    const trimmed = text.trim();
    const lastChar = trimmed[trimmed.length - 1];
    return lastChar === '.' || lastChar === '!' || lastChar === '?';
}

function formatTime(timestamp) {
    if (!timestamp) return 'Just now';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

const StatusIndicator = ({ connected }) => {
    return html`
        <div class="status">
            <div>Status : </div>
            <div class="status-indicator ${connected ? 'connected' : ''}"></div>
            <span>${connected ? 'Connected' : 'Disconnected - Reconnecting...'}</span>
        </div>
    `;
};

const LiveText = ({ liveTextBuffer, currentLiveSentence }) => {
    const displayLines = [];
    
    if (currentLiveSentence) {
        displayLines.push({ text: currentLiveSentence, isCurrent: true });
    }
    
    liveTextBuffer.slice().reverse().forEach(line => {
        displayLines.push({ text: line, isCurrent: false });
    });

    if (displayLines.length === 0) {
        return html`
            <div class="live-text active">
                Listening...
            </div>
        `;
    }

    return html`
        <div class="live-text active">
            ${displayLines.map((line, index) => {
                const fadeLevel = line.isCurrent ? '' : `fade-${Math.min(5, index)}`;
                const className = `live-text-line ${line.isCurrent ? 'current' : fadeLevel}`;
                return html`<div key=${index} class=${className}>${line.text}</div>`;
            })}
        </div>
    `;
};

const TranscriptionItem = ({ text, timestamp, isIncomplete }) => {
    const style = isIncomplete ? { opacity: '0.7', borderLeftColor: '#f59e0b' } : {};
    
    return html`
        <div class="transcription-item" style=${style}>
            <div class="transcription-text">${text}</div>
            <div class="transcription-time">${formatTime(timestamp)}</div>
        </div>
    `;
};

const EmptyState = () => {
    return html`
        <div class="empty-state">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path>
            </svg>
            <p>No transcriptions yet</p>
        </div>
    `;
};

const TranscriptionList = ({ transcriptions, currentSentence }) => {
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
        return html`<${EmptyState} />`;
    }

    return html`
        <div>
            ${allItems.map((item, index) => html`
                <${TranscriptionItem}
                    key=${index}
                    text=${item.text}
                    timestamp=${item.timestamp}
                    isIncomplete=${item.isIncomplete || false}
                />
            `)}
        </div>
    `;
};

const App = () => {
    const [connected, setConnected] = useState(false);
    const [transcriptions, setTranscriptions] = useState([]);
    const [currentSentence, setCurrentSentence] = useState(null);
    const [liveTextBuffer, setLiveTextBuffer] = useState([]);
    const [currentLiveSentence, setCurrentLiveSentence] = useState('');
    const wsManager = useRef(null);

    useEffect(() => {
        const handleMessage = (data) => {
            if (data.type === 'connection') {
                console.log('[WebSocket]', data.message);
                return;
            }

            if (data.type === 'transcription') {
                console.log('[WebSocket]', data);
                if (data.is_final) {
                    console.log('[DEBUG] Final transcription:', data.text);
                    addTranscription(data.text, data.timestamp);
                    updateLiveText(data.text, true);
                } else {
                    console.log('[DEBUG] Non-final (ignored for display):', data.text);
                }
            }
        };

        wsManager.current = new WebSocketManager(setConnected, handleMessage);
        wsManager.current.connect();

        return () => {
            if (wsManager.current) {
                wsManager.current.disconnect();
            }
        };
    }, []);

    const updateLiveText = (text, isFinal) => {
        if (!text || text.trim().length === 0) {
            return;
        }

        const trimmedText = text.trim();
        const isSentenceEnd = endsWithSentenceTerminator(trimmedText);

        if (isSentenceEnd) {
            // Complete sentence - move to buffer and clear current
            setCurrentLiveSentence(prev => {
                const newSentence = prev ? prev + ' ' + trimmedText : trimmedText;
                setLiveTextBuffer(prevBuffer => {
                    const newBuffer = [...prevBuffer, newSentence];
                    if (newBuffer.length > MAX_LIVE_LINES) {
                        newBuffer.shift();
                    }
                    console.log({liveTextBuffer: newBuffer});
                    return newBuffer;
                });
                return '';
            });
        } else {
            // Incomplete sentence - accumulate in currentLiveSentence
            setCurrentLiveSentence(prev => prev ? prev + ' ' + trimmedText : trimmedText);
        }
    };

    const addTranscription = (text, timestamp) => {
        if (!text || text.trim().length === 0) return;

        const trimmedText = text.trim();
        const isSentenceEnd = endsWithSentenceTerminator(trimmedText);

        setCurrentSentence(prev => {
            if (prev === null) {
                const newSentence = {
                    text: trimmedText,
                    timestamp: timestamp,
                    isComplete: isSentenceEnd
                };

                if (isSentenceEnd) {
                    setTranscriptions(prevTranscriptions => [newSentence, ...prevTranscriptions]);
                    return null;
                }
                
                return newSentence;
            } else {
                const updatedSentence = {
                    text: prev.text + ' ' + trimmedText,
                    timestamp: timestamp,
                    isComplete: isSentenceEnd
                };

                if (isSentenceEnd) {
                    setTranscriptions(prevTranscriptions => [updatedSentence, ...prevTranscriptions]);
                    return null;
                }
                
                return updatedSentence;
            }
        });
    };

    return html`
        <div class="container">
            <div class="header">
                <${StatusIndicator} connected=${connected} />
            </div>

            <div class="main-content">
                <div class="card center-content">
                    <h2>📝 Live Transcription</h2>
                    <${LiveText} 
                        liveTextBuffer=${liveTextBuffer} 
                        currentLiveSentence=${currentLiveSentence}
                    />
                    
                    <h2>📜 Transcription History</h2>
                    <div class="transcription-list">
                        <${TranscriptionList} 
                            transcriptions=${transcriptions}
                            currentSentence=${currentSentence}
                        />
                    </div>
                </div>
            </div>
        </div>
    `;
};

render(html`<${App} />`, document.body);