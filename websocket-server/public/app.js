import { h, render, Component } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from './websocket-manager.js';
import { StatusIndicator } from './components/StatusIndicator.js';
import { LiveTextDisplayer } from './components/LiveTextDisplayer.js';
import { LiveTranslationDisplayer } from './components/LiveTranslationDisplayer.js';
import { useWebSocketHandler } from './hooks/useWebSocketHandler.js';
import { useTranscriptionHandlers } from './hooks/useTranscriptionHandlers.js';

const html = htm.bind(h);

const MAX_LIVE_LINES = 5;

const App = () => {
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
        handleCorrectionResponse
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

    const handleMessage = useWebSocketHandler({
        /** Transcriptions Handlers */
        handleFinalTranscription,
        handleLiveTranscription,
        /** Translations Handlers */
        handleFinalTranslation,
        handleLiveTranslation,
        /** Corrections Handlers */
        handleCorrectionResponse
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

render(html`<${App} />`, document.body);