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

const LiveText = ({ finalizedText, liveText }) => {
    const hasContent = finalizedText || liveText;
    
    if (!hasContent) {
        return html`
            <div class="live-text active">
                Listening...
            </div>
        `;
    }

    return html`
        <div class="live-text active">
            <div class="live-text-line">
                ${finalizedText && html`<span class="finalized-text">${finalizedText}</span>`}
                ${liveText && html`<span class="live-text-updating">${liveText}</span>`}
            </div>
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
    const [finalizedText, setFinalizedText] = useState('');
    const [liveText, setLiveText] = useState('');
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
                    handleFinalTranscription(data.text, data.timestamp);
                } else {
                    console.log('[DEBUG] Non-final transcription:', data.text);
                    handleLiveTranscription(data.text);
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

    const handleFinalTranscription = (text, timestamp) => {
        if (!text || text.trim().length === 0) return;
        
        const trimmedText = text.trim();
        
        setFinalizedText(prev => {
            const newFinalized = prev ? prev + trimmedText : trimmedText;
            console.log('[DEBUG] Finalized text accumulated:', newFinalized);
            return newFinalized;
        });
        
        setLiveText('');
        
        addTranscription(trimmedText, timestamp);
    };
    
    const handleLiveTranscription = (text) => {
        if (!text || text.trim().length === 0) {
            setLiveText('');
            return;
        }
        
        const trimmedText = text.trim();
        setLiveText(trimmedText);
        console.log('[DEBUG] Live text updated:', trimmedText);
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
                        finalizedText=${finalizedText}
                        liveText=${liveText}
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