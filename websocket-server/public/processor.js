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

function splitIntoSentences(text) {
    if (!text) return [];
    return text.split(/([.?!])/).reduce((acc, part, i, arr) => {
        if (i % 2 === 0 && part.trim()) {
            const sentence = part + (arr[i + 1] || '');
            acc.push(sentence.trim());
        }
        return acc;
    }, []);
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

const LiveTextDisplayer = ({ finalizedSentences, liveTextHost, liveTextSpeaker, corrections, correctionEnabled }) => {
    const liveTextRef = useRef(null);
    const hasContent = finalizedSentences.length > 0 || liveTextHost || liveTextSpeaker;
    
    useEffect(() => {
        if (liveTextRef.current) {
            liveTextRef.current.scrollTop = liveTextRef.current.scrollHeight;
        }
    }, [finalizedSentences, liveTextHost, liveTextSpeaker]);
    
    const getSourceBadge = (source) => {
        if (!source) return null;
        const isHost = source.toLowerCase() === 'host';
        const badgeClass = isHost ? 'source-badge-host' : 'source-badge-speakers';
        const emoji = isHost ? '🎤' : '🔊';
        return html`<span class="${badgeClass}">${emoji} ${source}</span>`;
    };
    
    if (!hasContent) {
        return html`
            <div class="live-text active">
                Listening...
            </div>
        `;
    }

    // Show only the last 10 finalized sentences to avoid clutter
    const recentSentences = finalizedSentences.slice(-10);

    return html`
        <div class="live-text active" ref=${liveTextRef}>
            ${recentSentences.map((sentenceObj, index) => {
                const isLatest = index === recentSentences.length - 1;
                const style = isLatest 
                     ? { opacity: '1', fontWeight: '600', fontSize: '24px' }
                    : { opacity: '0.7', fontWeight: 'normal', fontSize: '18px' };
                const correction = corrections[sentenceObj.text];
                
                return html`
                    <div class="live-text-line" style=${style} key=${sentenceObj.id}>
                        ${getSourceBadge(sentenceObj.source)}
                        ${correctionEnabled && correction ? html`
                            ${correction.status === 'good' ? html`
                                <span class="correction-badge good">✓</span>
                                <span class="finalized-text">${sentenceObj.text}</span>
                            ` : correction.status === 'bad' ? html`
                                <span class="correction-badge bad">✗</span>
                                <span class="finalized-text original">${sentenceObj.text}</span>
                                <span class="correction-suggestion">→ ${correction.corrected}</span>
                            ` : html`
                                <span class="finalized-text">${sentenceObj.text}</span>
                            `}
                        ` : html`
                            <span class="finalized-text">${sentenceObj.text}</span>
                        `}
                    </div>
                `;
            })}
            ${liveTextHost && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('host')}
                    <span class="live-text-updating">${liveTextHost}</span>
                </div>
            `}
            ${liveTextSpeaker && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('speaker')}
                    <span class="live-text-updating">${liveTextSpeaker}</span>
                </div>
            `}
        </div>
    `;
};

const LiveTranslation = ({ finalizedTranslation }) => {
    const translationRef = useRef(null);
    
    useEffect(() => {
        if (translationRef.current) {
            translationRef.current.scrollTop = translationRef.current.scrollHeight;
        }
    }, [finalizedTranslation]);
    
    if (!finalizedTranslation) {
        return html`
            <div class="live-text active translation-view">
                Waiting for translation...
            </div>
        `;
    }

    const sentences = splitIntoSentences(finalizedTranslation);

    return html`
        <div class="live-text active translation-view" ref=${translationRef}>
            ${sentences.map((sentence, index) => {
                const isLatest = index === sentences.length - 1;
                const style = isLatest 
                    ? { opacity: '1', fontWeight: '600' , fontSize: '24px' }
                    : { opacity: '0.7', fontWeight: 'normal' , fontSize: '18px' };
                return html`
                    <div class="live-text-line" style=${style}>
                        <span class="finalized-text">${sentence}</span>
                    </div>
                `;
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
    const [finalizedSentences, setFinalizedSentences] = useState([]);
    const [liveTextHost, setLiveTextHost] = useState('');
    const [liveTextSpeaker, setLiveTextSpeaker] = useState('');
    const [finalizedTranslation, setFinalizedTranslation] = useState('');
    const [translationEnabled, setTranslationEnabled] = useState(true);
    const [correctionEnabled, setCorrectionEnabled] = useState(false);
    const [corrections, setCorrections] = useState({});
    const wsManager = useRef(null);
    const sentenceIdCounter = useRef(0);
    const correctionEnabledRef = useRef(correctionEnabled);
    const correctionsRef = useRef(corrections);
    
    useEffect(() => {
        correctionEnabledRef.current = correctionEnabled;
    }, [correctionEnabled]);
    
    useEffect(() => {
        correctionsRef.current = corrections;
    }, [corrections]);

    useEffect(() => {
        const handleMessage = (data) => {
            if (data.type === 'connection') {
                console.log('[WebSocket]', data.message);
                return;
            }

            if (data.type === 'transcription') {
                console.log('[WebSocket]', data);
                const source = data.input_source || 'Unknown';
                if (data.is_final) {
                    console.log('[DEBUG] Final transcription:', data.text, 'from', source);
                    handleFinalTranscription(data.text, data.timestamp, source);
                } else {
                    console.log('[DEBUG] Non-final transcription:', data.text, 'from', source);
                    handleLiveTranscription(data.text, source);
                }
            }
            
            if (data.type === 'translation') {
                console.log('[WebSocket]', data);
                if (data.is_final) {
                    console.log('[DEBUG] Final translation:', data.text);
                    handleFinalTranslation(data.text);
                }
            }
            
            if (data.type === 'correction_response') {
                console.log('[WebSocket] Correction response:', data);
                handleCorrectionResponse(data);
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

    const handleFinalTranscription = (text, timestamp, source) => {
        if (!text || text.trim().length === 0) return;
        
        const trimmedText = text.trim();
        const isCorrectionEnabled = correctionEnabledRef.current;
        const currentCorrections = correctionsRef.current;
        
        // Split the finalized text into actual sentences
        const sentences = splitIntoSentences(trimmedText);
        
        if (sentences.length === 0) {
            // If no sentences found, store as-is
            setFinalizedSentences(prev => {
                const newSentence = {
                    text: trimmedText,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random()
                };
                return [...prev, newSentence];
            });
        } else {
            // Store each sentence separately with the same source and timestamp
            setFinalizedSentences(prev => {
                const newSentences = sentences.map((sentence, index) => ({
                    text: sentence,
                    source: source,
                    timestamp: timestamp || new Date().toISOString(),
                    id: Date.now() + Math.random() + index
                }));
                
                console.log('[DEBUG] Finalized sentences added:', newSentences);
                
                // Request corrections for each sentence if enabled
                if (isCorrectionEnabled) {
                    newSentences.forEach(sentenceObj => {
                        if (!currentCorrections[sentenceObj.text]) {
                            requestCorrection(sentenceObj.text);
                        }
                    });
                }
                
                return [...prev, ...newSentences];
            });
        }
        
        if (source.toLowerCase() === 'host') {
            setLiveTextHost('');
        } else {
            setLiveTextSpeaker('');
        }
        
        addTranscription(trimmedText, timestamp);
    };
    
    const handleLiveTranscription = (text, source) => {
        if (!text || text.trim().length === 0) {
            if (source.toLowerCase() === 'host') {
                setLiveTextHost('');
            } else {
                setLiveTextSpeaker('');
            }
            return;
        }
        
        const trimmedText = text.trim();
        if (source.toLowerCase() === 'host') {
            setLiveTextHost(trimmedText);
        } else {
            setLiveTextSpeaker(trimmedText);
        }
        console.log('[DEBUG] Live text updated:', trimmedText, 'from', source);
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
    
    const handleFinalTranslation = (text) => {
        if (!text || text.trim().length === 0) return;
        
        const trimmedText = text.trim();
        console.log('[DEBUG] Final translation received:', trimmedText);
        
        setFinalizedTranslation(prev => {
            const newFinalized = prev ? prev + ' ' + trimmedText : trimmedText;
            console.log('[DEBUG] Finalized translation accumulated:', newFinalized);
            return newFinalized;
        });
    };
    
    const requestCorrection = (sentence) => {
        if (!wsManager.current || !wsManager.current.ws) return;
        
        const sentenceId = sentenceIdCounter.current++;
        const request = {
            type: 'correction_request',
            sentenceId: sentenceId,
            sentence: sentence
        };
        
        console.log('[DEBUG] Requesting correction for:', sentence);
        wsManager.current.ws.send(JSON.stringify(request));
    };
    
    const handleCorrectionResponse = (data) => {
        setCorrections(prev => ({
            ...prev,
            [data.original]: {
                status: data.status,
                corrected: data.corrected
            }
        }));
        console.log('[DEBUG] Correction stored:', data.original, '->', data.status);
    };

    return html`
        <div class="container">
            <div class="header">
                <${StatusIndicator} connected=${connected} />
                <div class="translation-toggle">
                    <label class="toggle-label">
                        <input 
                            type="checkbox" 
                            checked=${translationEnabled}
                            onChange=${(e) => setTranslationEnabled(e.target.checked)}
                        />
                        <span class="toggle-text">Enable Translation</span>
                    </label>
                    <label class="toggle-label">
                        <input 
                            type="checkbox" 
                            checked=${correctionEnabled}
                            onChange=${(e) => setCorrectionEnabled(e.target.checked)}
                        />
                        <span class="toggle-text">Enable Correction</span>
                    </label>
                </div>
            </div>

            <div class="main-content">
                <div class="split-view">
                    <div class="card live-view">
                        <h2>📝 Live Transcription</h2>
                        <${LiveTextDisplayer} 
                            finalizedSentences=${finalizedSentences}
                            liveTextHost=${liveTextHost}
                            liveTextSpeaker=${liveTextSpeaker}
                            corrections=${corrections}
                            correctionEnabled=${correctionEnabled}
                        />
                    </div>
                    
                    ${translationEnabled && html`
                        <div class="card live-view">
                            <h2>🌐 Live Translation</h2>
                            <${LiveTranslation} 
                                finalizedTranslation=${finalizedTranslation}
                            />
                        </div>
                    `}
                </div>
                
            </div>
        </div>
    `;
};

render(html`<${App} />`, document.body);