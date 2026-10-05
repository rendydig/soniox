import { h, render } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from './websocket-manager.js';
import { GeminiDisplayer } from './components/GeminiDisplayer.js';
import { useWebSocketHandler } from './hooks/useWebSocketHandler.js';
import { useTranscriptionHandlers } from './hooks/useTranscriptionHandlers.js';

const html = htm.bind(h);

const noop = () => {};

const GeminiApp = () => {
    const [, setConnected] = useState(false);
    const [geminiResults, setGeminiResults] = useState([]);
    const [geminiStatus, setGeminiStatus] = useState('');
    const wsManager = useRef(null);

    const {
        /** Gemini Handlers */
        handleGeminiResult,
        handleGeminiStatus
    } = useTranscriptionHandlers({
        /** Unused on this page — only the Gemini output is shown. */
        setFinalizedSentences: noop,
        setLiveTextHost: noop,
        setLiveTextSpeaker: noop,
        setFinalizedTranslations: noop,
        setLiveTranslationHost: noop,
        setLiveTranslationSpeaker: noop,
        setCorrections: noop,
        correctionEnabled: false,
        corrections: {},
        setGeminiResults,
        setGeminiStatus,
        wsManager
    });

    const handleMessage = useWebSocketHandler({
        handleFinalTranscription: noop,
        handleLiveTranscription: noop,
        handleFinalTranslation: noop,
        handleLiveTranslation: noop,
        handleCorrectionResponse: noop,
        handleGeminiResult,
        handleGeminiStatus
    });

    /** Send a control message back to the Python app. */
    const sendControl = (payload) => {
        const ws = wsManager.current && wsManager.current.ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(payload));
        }
    };

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
        <div class="card gemini-card">
            <button
                class="gemini-minimize-btn"
                title="Hide"
                aria-label="Hide"
                onClick=${() => sendControl({ type: 'hide_gemini_window' })}
            >−</button>
            <h2>
                ✨ Gemini Suggestion
                <button class="btn-gemini" onClick=${() => sendControl({ type: 'auto_reply_request' })}>
                    Reply now
                </button>
            </h2>
            <${GeminiDisplayer}
                geminiResults=${geminiResults}
                geminiStatus=${geminiStatus}
            />
        </div>
    `;
};

render(html`<${GeminiApp} />`, document.getElementById('gemini-root'));
