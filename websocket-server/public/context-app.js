import { h, render } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { WebSocketManager } from './websocket-manager.js';
import { Markdown } from './components/Markdown.js';
import { useWebSocketHandler } from './hooks/useWebSocketHandler.js';

const html = htm.bind(h);

const ROLES = ['host', 'speaker'];
const ROLE_LABEL = { host: 'Host', speaker: 'Speaker' };
// Typing stops for this long -> the draft is written to the selected file.
const SAVE_DEBOUNCE_MS = 800;

const noop = () => {};

const EMPTY_STATE = {
    selection: { host: null, speaker: null },
    problems: { host: null, speaker: null },
    history: { host: [], speaker: [] },
    contents: { host: '', speaker: '' },
    revision: { host: 0, speaker: 0 }
};

const PROBLEM_TEXT = {
    missing: 'file not found',
    too_large: 'file too large (>64 KB)'
};

/** "14:07:52" — the local time the backend confirmed the save. */
const clockLabel = () => new Date().toLocaleTimeString();

const fileName = (p) => {
    if (!p) return '';
    const parts = String(p).split(/[\\/]/);
    return parts[parts.length - 1] || p;
};

const ContextApp = () => {
    const [, setConnected] = useState(false);
    const [contextState, setContextState] = useState(EMPTY_STATE);
    const [tab, setTab] = useState('host');
    const [draft, setDraft] = useState({ host: '', speaker: '' });
    const [saveStatus, setSaveStatus] = useState({ host: null, speaker: null });
    const [notice, setNotice] = useState({ host: '', speaker: '' });
    const [preview, setPreview] = useState(false);

    const wsManager = useRef(null);
    // Latest values for callbacks that outlive a render (the debounce timers).
    const stateRef = useRef(EMPTY_STATE);
    const draftRef = useRef({ host: '', speaker: '' });
    const dirtyRef = useRef({ host: false, speaker: false });
    const timersRef = useRef({ host: null, speaker: null });
    // Last content the backend reported, to spot an edit made outside the pane.
    const knownRef = useRef({ host: '', speaker: '' });
    const tabRef = useRef('host');

    useEffect(() => {
        tabRef.current = tab;
    }, [tab]);

    /** Send a control message back to the Python app / Node service. */
    const sendControl = useCallback((payload) => {
        const ws = wsManager.current && wsManager.current.ws;
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(payload));
        }
    }, []);

    /** Set (or clear) one role's save status; accepts a value or an updater. */
    const setStatus = useCallback((role, updater) => {
        setSaveStatus((current) => ({
            ...current,
            [role]: typeof updater === 'function' ? updater(current[role]) : updater
        }));
    }, []);

    /** Write the current draft now (cancels the pending debounce). */
    const flush = useCallback((role) => {
        if (timersRef.current[role]) {
            clearTimeout(timersRef.current[role]);
            timersRef.current[role] = null;
        }
        if (!dirtyRef.current[role]) return;
        const path = stateRef.current.selection[role];
        if (!path) return;
        const text = draftRef.current[role];
        sendControl({ type: 'context_save', role, path, text });
        setStatus(role, { kind: 'saving', text: 'Saving…' });
    }, [sendControl, setStatus]);

    const handleInput = useCallback((role, value) => {
        draftRef.current[role] = value;
        dirtyRef.current[role] = true;
        setDraft((current) => ({ ...current, [role]: value }));
        setNotice((current) => ({ ...current, [role]: '' }));
        setStatus(role, { kind: 'saving', text: 'Saving…' });
        if (timersRef.current[role]) clearTimeout(timersRef.current[role]);
        timersRef.current[role] = setTimeout(() => {
            timersRef.current[role] = null;
            flush(role);
        }, SAVE_DEBOUNCE_MS);
    }, [flush, setStatus]);

    const handleContextState = useCallback((data) => {
        const next = {
            selection: { ...EMPTY_STATE.selection, ...(data.selection || {}) },
            problems: { ...EMPTY_STATE.problems, ...(data.problems || {}) },
            history: { ...EMPTY_STATE.history, ...(data.history || {}) },
            contents: { ...EMPTY_STATE.contents, ...(data.contents || {}) },
            revision: { ...EMPTY_STATE.revision, ...(data.revision || {}) }
        };
        stateRef.current = next;
        setContextState(next);

        ROLES.forEach((role) => {
            const incoming = next.contents[role] || '';
            const known = knownRef.current[role];
            if (!dirtyRef.current[role]) {
                draftRef.current[role] = incoming;
                setDraft((current) => ({ ...current, [role]: incoming }));
                setStatus(role, (current) => (current && current.kind === 'saving' ? null : current));
            } else if (incoming === draftRef.current[role]) {
                // Our own save came back: the file now holds exactly the draft.
                dirtyRef.current[role] = false;
                setStatus(role, { kind: 'saved', text: `Saved ${clockLabel()}` });
            } else if (incoming !== known) {
                setNotice((current) => ({
                    ...current,
                    [role]: 'File changed on disk — the next save overwrites it'
                }));
            }
            knownRef.current[role] = incoming;
        });
    }, [setStatus]);

    const handleContextStatus = useCallback((status, message) => {
        if (status === 'saved') return;
        setStatus(tabRef.current, { kind: 'error', text: message || 'Save failed' });
    }, [setStatus]);

    const handleConnection = useCallback(() => {
        sendControl({ type: 'context_get' });
    }, [sendControl]);

    const handleContextMessage = useWebSocketHandler({
        // This pane renders nothing but the context editor, so every other
        // stream is ignored — but the handlers must still be functions, since
        // the dispatcher calls some of them unconditionally.
        handleFinalTranscription: noop,
        handleLiveTranscription: noop,
        handleFinalTranslation: noop,
        handleLiveTranslation: noop,
        handleCorrectionResponse: noop,
        handleContextState,
        handleContextStatus,
        handleConnection
    });

    /** `context_flush` is sent by the app when the pane hides or the app closes. */
    const handleMessage = useCallback((data) => {
        if (data && data.type === 'context_flush') {
            ROLES.forEach(flush);
            return;
        }
        handleContextMessage(data);
    }, [flush, handleContextMessage]);

    useEffect(() => {
        wsManager.current = new WebSocketManager(setConnected, handleMessage);
        wsManager.current.connect();
        return () => {
            if (wsManager.current) wsManager.current.disconnect();
        };
    }, [handleMessage]);

    /** Drop the local draft and load `path` (or clear) for one role. */
    const resetDraft = useCallback((role) => {
        dirtyRef.current[role] = false;
        draftRef.current[role] = '';
        setDraft((current) => ({ ...current, [role]: '' }));
        setNotice((current) => ({ ...current, [role]: '' }));
        setStatus(role, null);
    }, [setStatus]);

    const handleSelect = useCallback((role, path) => {
        flush(role);
        resetDraft(role);
        sendControl({ type: 'context_select', role, path });
    }, [flush, resetDraft, sendControl]);

    const handleClear = useCallback((role) => {
        flush(role);
        resetDraft(role);
        sendControl({ type: 'context_clear_selection', role });
    }, [flush, resetDraft, sendControl]);

    const role = tab;
    const selected = contextState.selection[role];
    const problem = contextState.problems[role];
    const history = contextState.history[role] || [];
    const editable = Boolean(selected) && !problem;
    const status = saveStatus[role];

    const selectionRow = html`
        <div class="context-row">
            <select
                class="context-select"
                value=${selected || ''}
                onChange=${(event) => {
                    const value = event.target.value;
                    if (!value) handleClear(role);
                    else if (value !== selected) handleSelect(role, value);
                }}
            >
                <option value="">— none —</option>
                ${history.map((entry) => html`
                    <option value=${entry} selected=${entry === selected}>
                        ${fileName(entry)}
                    </option>
                `)}
                ${selected && !history.includes(selected) && html`
                    <option value=${selected} selected>${fileName(selected)}</option>
                `}
            </select>
            <button
                class="pane-control-btn context-btn"
                title="Pick an existing .txt / .md file anywhere on disk"
                onClick=${() => sendControl({ type: 'context_browse', role })}
            >Browse…</button>
            <button
                class="pane-control-btn context-btn"
                title="Create a new context file"
                onClick=${() => sendControl({ type: 'context_new_request', role })}
            >New…</button>
        </div>
    `;

    const chips = history.length > 0 && html`
        <div class="context-chips">
            ${history.map((entry) => html`
                <span
                    class="context-chip ${entry === selected ? 'selected' : ''} ${entry === selected && problem ? 'problem' : ''}"
                    title=${entry}
                    onClick=${() => entry !== selected && handleSelect(role, entry)}
                >
                    <span class="context-chip-label">${fileName(entry)}</span>
                    <button
                        class="context-chip-forget"
                        title="Remove from the recent list"
                        onClick=${(event) => {
                            event.stopPropagation();
                            sendControl({ type: 'context_forget', role, path: entry });
                        }}
                    >×</button>
                </span>
            `)}
        </div>
    `;

    const editor = editable
        ? (preview
            ? html`<div class="context-preview"><${Markdown} text=${draft[role]} /></div>`
            : html`<textarea
                    class="context-textarea"
                    value=${draft[role]}
                    spellcheck="false"
                    placeholder="Write what the AI should know about this role…"
                    onInput=${(event) => handleInput(role, event.target.value)}
                    onBlur=${() => flush(role)}
                ></textarea>`)
        : html`<textarea
                class="context-textarea"
                disabled
                value=""
                placeholder=${selected
                    ? 'File not available — pick another file or fix the path'
                    : 'No context file selected. Use Browse… or New…'}
            ></textarea>`;

    return html`
        <div class="card context-card">
            <div class="pane-controls">
                <button
                    class="pane-control-btn"
                    title="Move to left edge"
                    aria-label="Move to left edge"
                    onClick=${() => sendControl({ type: 'set_context_window_edge', edge: 'left' })}
                >⇤</button>
                <button
                    class="pane-control-btn"
                    title="Move to right edge"
                    aria-label="Move to right edge"
                    onClick=${() => sendControl({ type: 'set_context_window_edge', edge: 'right' })}
                >⇥</button>
                <button
                    class="pane-control-btn"
                    title="Hide"
                    aria-label="Hide"
                    onClick=${() => sendControl({ type: 'hide_context_window' })}
                >−</button>
            </div>

            <div class="context-header">
                <div class="bullet-tabs" role="tablist">
                    ${ROLES.map((name) => html`
                        <button
                            class="bullet-tab ${tab === name ? 'active' : ''}"
                            role="tab"
                            aria-selected=${tab === name}
                            onClick=${() => {
                                if (name === tab) return;
                                flush(role);
                                setTab(name);
                            }}
                        >${ROLE_LABEL[name]}</button>
                    `)}
                </div>
                <div class="context-row" style="margin-bottom:0">
                    ${problem && html`<span class="context-badge">${PROBLEM_TEXT[problem] || problem}</span>`}
                    ${editable && html`
                        <button
                            class="pane-control-btn context-btn"
                            title="Preview the Markdown"
                            onClick=${() => setPreview((current) => !current)}
                        >${preview ? 'Write' : 'Preview'}</button>
                        <button
                            class="pane-control-btn context-btn"
                            title="Save now"
                            onClick=${() => flush(role)}
                        >Save</button>
                    `}
                </div>
            </div>

            ${selectionRow}
            ${chips}
            <div class="context-editor">${editor}</div>
            <div class="context-footer">
                <span class="context-hint" title=${selected || ''}>
                    ${selected
                        ? selected
                        : `${ROLE_LABEL[role]} context: what the AI should know about this role`}
                    ${notice[role] ? ` · ${notice[role]}` : ''}
                </span>
                ${status && html`
                    <span class="context-save-status ${status.kind}">${status.text}</span>
                `}
            </div>
        </div>
    `;
};

render(html`<${ContextApp} />`, document.getElementById('context-root'));
