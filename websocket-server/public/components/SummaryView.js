import { h } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { Markdown } from './Markdown.js';

const html = htm.bind(h);

/** Status text shown while a summary call is in flight (set by the handler). */
const BUSY_STATUS = 'Summarizing…';
// Typing stops for this long -> the draft is persisted to the session.
const SAVE_DEBOUNCE_MS = 800;
// How long the "Saved" confirmation stays on screen.
const SAVED_HIDE_MS = 1500;

/**
 * Whole-session summary tab.
 *
 * Defaults to a **preview** of the rendered structured markdown. A double-click
 * enters **edit mode** (a raw-markdown textarea); edits are auto-saved on typing
 * with a debounce and persisted in the session via
 * `{"type":"summary_save","text":...}`. The **Back** button flushes the pending
 * edit and returns to preview. One click on **Summarize** instead sends the whole
 * transcript (plus bullets + speaker profile) to the AI, whose reply replaces the
 * text.
 */
export const SummaryView = ({ summary, status, onSummarize, onEdit }) => {
    const text = typeof summary === 'string' ? summary : '';
    const busy = status === BUSY_STATUS;

    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saveState, setSaveState] = useState('');  // '' | 'saving' | 'saved'

    const editorRef = useRef(null);
    const draftRef = useRef('');
    const dirtyRef = useRef(false);
    const timerRef = useRef(null);
    const savedTimerRef = useRef(null);
    // Keep the latest callback reachable from the stable unmount cleanup.
    const onEditRef = useRef(onEdit);

    useEffect(() => {
        onEditRef.current = onEdit;
    }, [onEdit]);

    /** Persist the current draft now (cancels the pending debounce). */
    const flush = useCallback(() => {
        if (savedTimerRef.current) {
            clearTimeout(savedTimerRef.current);
            savedTimerRef.current = null;
        }
        if (timerRef.current) {
            clearTimeout(timerRef.current);
            timerRef.current = null;
        }
        if (!dirtyRef.current) return;
        dirtyRef.current = false;
        if (typeof onEditRef.current === 'function') {
            onEditRef.current(draftRef.current);
        }
        setSaveState('saved');
        savedTimerRef.current = setTimeout(() => setSaveState(''), SAVED_HIDE_MS);
    }, []);

    // Flush a pending edit when the tab is switched away (this component unmounts).
    useEffect(() => () => {
        if (timerRef.current) clearTimeout(timerRef.current);
        if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
        if (dirtyRef.current && typeof onEditRef.current === 'function') {
            onEditRef.current(draftRef.current);
        }
    }, []);

    const enterEdit = useCallback(() => {
        if (busy) return;
        draftRef.current = text;
        dirtyRef.current = false;
        setDraft(text);
        setSaveState('');
        setEditing(true);
    }, [text, busy]);

    const exitEdit = useCallback(() => {
        flush();
        setEditing(false);
    }, [flush]);

    const handleInput = useCallback((event) => {
        const value = event.target.value;
        draftRef.current = value;
        dirtyRef.current = true;
        setDraft(value);
        if (savedTimerRef.current) {
            clearTimeout(savedTimerRef.current);
            savedTimerRef.current = null;
        }
        setSaveState('saving');
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(flush, SAVE_DEBOUNCE_MS);
    }, [flush]);

    // Focus the editor as soon as edit mode opens.
    useEffect(() => {
        if (editing && editorRef.current) {
            editorRef.current.focus();
        }
    }, [editing]);

    const rightControls = editing
        ? html`
            ${saveState && html`
                <span class="summary-save-status ${saveState}">
                    ${saveState === 'saving' ? 'Saving…' : 'Saved'}
                </span>
            `}
            <button
                class="pane-control-btn bullet-action-btn"
                title="Back to preview (your edits are saved)"
                aria-label="Back to preview"
                onClick=${exitEdit}
            >Back</button>
        `
        : html`
            <button
                class="pane-control-btn bullet-action-btn"
                title="Summarize the whole conversation with the AI"
                aria-label="Summarize the session"
                disabled=${busy}
                onClick=${onSummarize}
            >${busy ? 'Summarizing…' : 'Summarize'}</button>
        `;

    const body = editing
        ? html`<textarea
                class="summary-editor"
                ref=${editorRef}
                value=${draft}
                spellcheck="false"
                placeholder="Write or edit the summary (markdown)…"
                onInput=${handleInput}
                onBlur=${flush}
            ></textarea>`
        : (text
            ? html`<div
                    class="summary-text"
                    title="Double-click to edit"
                    onDblClick=${enterEdit}
                ><${Markdown} text=${text} /></div>`
            : html`<div
                    class="bullet-empty summary-editable"
                    title="Double-click to write a summary"
                    onDblClick=${enterEdit}
                >No summary yet. Click Summarize to send the whole conversation to the AI,
                    or double-click here to write one.</div>`);

    return html`
        <div class="live-text summary-view">
            <div class="summary-actions">
                <span class="summary-title">${editing ? 'Editing summary' : 'Session summary'}</span>
                <div class="summary-actions-right">${rightControls}</div>
            </div>
            ${body}
            ${!editing && status && html`<div class="bullet-status">${status}</div>`}
        </div>
    `;
};
