import { h } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from '../websocket-manager.js';
import { StatusIndicator } from './StatusIndicator.js';
import { LiveTextDisplayer } from './LiveTextDisplayer.js';
import { LiveTranslationDisplayer } from './LiveTranslationDisplayer.js';
import { useWebSocketHandler } from '../hooks/useWebSocketHandler.js';
import { useTranscriptionHandlers } from '../hooks/useTranscriptionHandlers.js';

const html = htm.bind(h);

const MAX_LIVE_LINES = 5;

export const App = ({ hideControlType, edgeControlType } = {}) => {
    const [connected, setConnected] = useState(false);
    const [finalizedSentences, setFinalizedSentences] = useState([]);
    const [liveTextHost, setLiveTextHost] = useState('');
    const [liveTextSpeaker, setLiveTextSpeaker] = useState('');
    const [finalizedTranslations, setFinalizedTranslations] = useState([]);
    const [liveTranslationHost, setLiveTranslationHost] = useState('');
    const [liveTranslationSpeaker, setLiveTranslationSpeaker] = useState('');
    const [translationEnabled, setTranslationEnabled] = useState(true);
    const [correctionEnabled, setCorrectionEnabled] = useState(false);
    const [corrections, setCorrections] = useState({});
    const wsManager = useRef(null);
    
    const {
        /** Transcriptions Handlers */
        handleFinalTranscription,
        handleLiveTranscription,
        /** Translations Handlers */
        handleFinalTranslation,
        handleLiveTranslation,
        /** Corrections Handlers */
        handleCorrectionResponse,
        /** Session restore */
        handleSessionState
    } = useTranscriptionHandlers({
        setFinalizedSentences,
        setLiveTextHost,
        setLiveTextSpeaker,
        setFinalizedTranslations,
        setLiveTranslationHost,
        setLiveTranslationSpeaker,
        setCorrections,
        correctionEnabled,
        corrections,
        wsManager
    });

    /** Send a control message back to the Python app. */
    const sendControl = useCallback((payload) => {
        const ws = wsManager.current && wsManager.current.ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(payload));
        }
    }, []);

    /** On (re)connect, ask Python for the persisted session state. */
    const handleConnection = useCallback(() => {
        sendControl({ type: 'request_session_state' });
    }, [sendControl]);

    const handleMessage = useWebSocketHandler({
        /** Transcriptions Handlers */
        handleFinalTranscription,
        handleLiveTranscription,
        /** Translations Handlers */
        handleFinalTranslation,
        handleLiveTranslation,
        /** Corrections Handlers */
        handleCorrectionResponse,
        handleSessionState,
        handleConnection
    });

    /** Use Effects */
    useEffect(() => {
        wsManager.current = new WebSocketManager(setConnected, handleMessage);
        wsManager.current.connect();

        return () => {
            if (wsManager.current) {
                wsManager.current.disconnect();
            }
        };
    }, [handleMessage]);

    return html`
        <div class="container">
            ${hideControlType && html`
                <div class="pane-controls">
                    ${edgeControlType && html`
                        <button
                            class="pane-control-btn"
                            title="Move to left edge"
                            aria-label="Move to left edge"
                            onClick=${() => sendControl({ type: edgeControlType, edge: 'left' })}
                        >⇤</button>
                        <button
                            class="pane-control-btn"
                            title="Move to right edge"
                            aria-label="Move to right edge"
                            onClick=${() => sendControl({ type: edgeControlType, edge: 'right' })}
                        >⇥</button>
                    `}
                    <button
                        class="pane-control-btn"
                        title="Hide"
                        aria-label="Hide"
                        onClick=${() => sendControl({ type: hideControlType })}
                    >−</button>
                </div>
            `}
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
                            <${LiveTranslationDisplayer} 
                                finalizedTranslations=${finalizedTranslations}
                                liveTranslationHost=${liveTranslationHost}
                                liveTranslationSpeaker=${liveTranslationSpeaker}
                            />
                        </div>
                    `}
                </div>

            </div>
        </div>
    `;
};
