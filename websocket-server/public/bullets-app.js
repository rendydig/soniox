import { h, render } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from './websocket-manager.js';
import { BulletPointsList } from './components/BulletPointsList.js';
import { SpeakerProfile } from './components/SpeakerProfile.js';
import { useWebSocketHandler } from './hooks/useWebSocketHandler.js';
import { useTranscriptionHandlers } from './hooks/useTranscriptionHandlers.js';

const html = htm.bind(h);

const noop = () => {};

const BulletPointsApp = () => {
    const [, setConnected] = useState(false);
    const [items, setItems] = useState([]);
    const [speaker, setSpeaker] = useState({});
    const [countdown, setCountdown] = useState(null);
    const [now, setNow] = useState(() => Date.now());
    const [status, setStatus] = useState('');
    const [tab, setTab] = useState('bullets');
    const [lastPickup, setLastPickup] = useState('');
    const [lastPickupStatus, setLastPickupStatus] = useState('');
    const [autoPickup, setAutoPickup] = useState(false);
    const wsManager = useRef(null);

    const {
        handleBulletPoints,
        handleBulletPointsStatus,
        handleBulletPointsCountdown,
        handleLastPickup,
        handleLastPickupStatus,
        handleSessionState
    } = useTranscriptionHandlers({
        /** Unused on this page — only the bullet list is shown. */
        setFinalizedSentences: noop,
        setLiveTextHost: noop,
        setLiveTextSpeaker: noop,
        setFinalizedTranslations: noop,
        setLiveTranslationHost: noop,
        setLiveTranslationSpeaker: noop,
        setCorrections: noop,
        correctionEnabled: false,
        corrections: {},
        setBulletPoints: setItems,
        setBulletPointsStatus: setStatus,
        setBulletCountdown: setCountdown,
        setSpeakerProfile: setSpeaker,
        setLastPickup,
        setLastPickupStatus,
        setLastPickupAuto: setAutoPickup,
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
        handleFinalTranscription: noop,
        handleLiveTranscription: noop,
        handleFinalTranslation: noop,
        handleLiveTranslation: noop,
        handleCorrectionResponse: noop,
        handleBulletPoints,
        handleBulletPointsStatus,
        handleBulletPointsCountdown,
        handleLastPickup,
        handleLastPickupStatus,
        handleSessionState,
        handleConnection
    });

    useEffect(() => {
        wsManager.current = new WebSocketManager(setConnected, handleMessage);
        wsManager.current.connect();

        return () => {
            if (wsManager.current) {
                wsManager.current.disconnect();
            }
        };
    }, [handleMessage]);

    // Ticks the clock the countdown is measured against. The deadline itself
    // comes from the backend QTimer, so both sides count down from one instant.
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 500);
        return () => clearInterval(id);
    }, []);

    /** "4:32" left until the next automatic flush (null when auto is off). */
    const countdownLabel = (() => {
        if (!countdown) return null;
        const remaining = Math.max(0, Math.ceil(countdown.at * 1000 - now));
        const minutes = Math.floor(remaining / 60000);
        const seconds = String(Math.floor((remaining % 60000) / 1000)).padStart(2, '0');
        return `${minutes}:${seconds}`;
    })();

    const toggleAutoPickup = useCallback((enabled) => {
        setAutoPickup(enabled);
        sendControl({ type: 'set_last_pickup_auto', enabled });
    }, [sendControl]);

    const bulletsView = html`
        <${BulletPointsList} items=${items} status=${status} />
    `;

    const speakerView = html`
        <${SpeakerProfile} profile=${speaker} status=${status} />
    `;

    const pickupView = html`
        <div class="live-text pickup-view">
            <label class="pickup-toggle">
                <input
                    type="checkbox"
                    checked=${autoPickup}
                    onChange=${(e) => toggleAutoPickup(e.target.checked)}
                />
                <span>Auto pickup aktif</span>
            </label>
            ${lastPickup
                ? html`<div class="pickup-text">${lastPickup}</div>`
                : html`<div class="bullet-empty">
                    Belum ada yang terambil. Nyalakan "Auto pickup" dan mulailah
                    percakapan.
                </div>`}
            ${lastPickupStatus && html`<div class="bullet-status">${lastPickupStatus}</div>`}
        </div>
    `;

    return html`
        <div class="card bullet-card">
            <div class="pane-controls">
                <button
                    class="pane-control-btn"
                    title="Move to left edge"
                    aria-label="Move to left edge"
                    onClick=${() => sendControl({ type: 'set_bullet_points_window_edge', edge: 'left' })}
                >⇤</button>
                <button
                    class="pane-control-btn"
                    title="Move to right edge"
                    aria-label="Move to right edge"
                    onClick=${() => sendControl({ type: 'set_bullet_points_window_edge', edge: 'right' })}
                >⇥</button>
                <button
                    class="pane-control-btn"
                    title="Hide"
                    aria-label="Hide"
                    onClick=${() => sendControl({ type: 'hide_bullet_points_window' })}
                >−</button>
            </div>
            <div class="bullet-header">
                <div class="bullet-header-row">
                    <div class="bullet-tabs" role="tablist">
                        <button
                            class="bullet-tab ${tab === 'bullets' ? 'active' : ''}"
                            role="tab"
                            aria-selected=${tab === 'bullets'}
                            onClick=${() => setTab('bullets')}
                        >Bullet Points</button>
                        <button
                            class="bullet-tab ${tab === 'speaker' ? 'active' : ''}"
                            role="tab"
                            aria-selected=${tab === 'speaker'}
                            onClick=${() => setTab('speaker')}
                        >Speaker</button>
                        <button
                            class="bullet-tab ${tab === 'pickup' ? 'active' : ''}"
                            role="tab"
                            aria-selected=${tab === 'pickup'}
                            onClick=${() => setTab('pickup')}
                        >Last Picked Up</button>
                    </div>
                    ${tab === 'bullets' && html`
                        <button
                            class="pane-control-btn bullet-rebuild-btn"
                            title="Rebuild the list from the whole conversation"
                            aria-label="Rebuild bullet points"
                            onClick=${() => sendControl({ type: 'regenerate_bullet_points' })}
                        >Rebuild</button>
                    `}
                </div>
                ${countdownLabel && html`
                    <div
                        class="bullet-countdown"
                        role="timer"
                        title="Time left until the next automatic bullet-points update"
                    >
                        <span class="bullet-countdown-dot" aria-hidden="true"></span>
                        Next update in ${countdownLabel}
                    </div>
                `}
            </div>
            ${tab === 'bullets' ? bulletsView : tab === 'speaker' ? speakerView : pickupView}
        </div>
    `;
};

render(html`<${BulletPointsApp} />`, document.getElementById('bullets-root'));
