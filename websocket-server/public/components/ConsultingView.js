import { h } from 'https://esm.sh/preact@10.19.3';
import { useState, useEffect, useRef, useCallback } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { Markdown } from './Markdown.js';

const html = htm.bind(h);

// Typing stops for this long -> the brief draft is persisted to the session.
const SAVE_DEBOUNCE_MS = 800;
// How long the "Saved" confirmation stays on screen.
const SAVED_HIDE_MS = 1500;

// Button label while a section's AI call is in flight.
const BUSY_LABEL = {
    brief: 'Drafting…',
    gaps: 'Analyzing gaps…',
    roadmap: 'Building roadmap…'
};

/**
 * Consulting tab: a three-step manual pipeline.
 *
 *   1. **Client brief** — AI-drafted, user-editable (double-click to edit; edits
 *      auto-save), then **Confirm** freezes it as the locked reference. Any edit
 *      after a confirmation clears the chip and requires re-confirming.
 *   2. **Gap analysis** — flags thin/contradictory parts of the conversation
 *      against the confirmed brief (or, while unconfirmed, the speaker profile).
 *   3. **Execution roadmap** — turns the confirmed brief + flagged gaps into a
 *      prioritized plan (disabled with a hint until the brief is confirmed).
 *
 * There is no timer and no auto mode: each section runs on its own button.
 */
export const ConsultingView = ({
    brief,
    gaps,
    roadmap,
    briefConfirmed,
    status,
    onDraftBrief,
    onAnalyzeGaps,
    onGenerateRoadmap,
    onConfirmBrief,
    onEdit
}) => {
    const briefText = typeof brief === 'string' ? brief : '';
    const gapsText = typeof gaps === 'string' ? gaps : '';
    const roadmapText = typeof roadmap === 'string' ? roadmap : '';
    const st = status && typeof status === 'object' ? status : {};
    const busyMode = st.status === 'started' ? st.mode : '';
    const anyBusy = !!busyMode;

    // The brief opens in preview; a double-click switches to the raw editor.
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saveState, setSaveState] = useState('');  // '' | 'saving' | 'saved'
    const [dirty, setDirty] = useState(false);

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
        setDirty(false);
        if (typeof onEditRef.current === 'function') {
            onEditRef.current('brief', draftRef.current);
        }
        setSaveState('saved');
        savedTimerRef.current = setTimeout(() => setSaveState(''), SAVED_HIDE_MS);
    }, []);

    // Flush a pending edit when the tab is switched away (this component unmounts).
    useEffect(() => () => {
        if (timerRef.current) clearTimeout(timerRef.current);
        if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
        if (dirtyRef.current && typeof onEditRef.current === 'function') {
            onEditRef.current('brief', draftRef.current);
        }
    }, []);

    const enterEdit = useCallback(() => {
        if (anyBusy) return;
        draftRef.current = briefText;
        dirtyRef.current = false;
        setDraft(briefText);
        setSaveState('');
        setEditing(true);
    }, [briefText, anyBusy]);

    const exitEdit = useCallback(() => {
        flush();
        setEditing(false);
    }, [flush]);

    const handleInput = useCallback((event) => {
        const value = event.target.value;
        draftRef.current = value;
        dirtyRef.current = true;
        setDirty(true);
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

    /** A section's transient notice (error / no_input), keyed to its own mode. */
    const noticeFor = (mode) => {
        if (st.mode !== mode) return '';
        if (st.status === 'error' || st.status === 'failed') {
            return st.message || 'Call failed.';
        }
        if (st.status === 'no_input') {
            return st.message || 'Nothing to work with yet';
        }
        return '';
    };

    // The chip shows Confirmed only while the brief is confirmed AND untouched
    // locally; any keystroke drops it back to Draft until re-confirmed.
    const showConfirmed = !!briefConfirmed && !dirty;

    const briefNotice = noticeFor('brief');
    const gapsNotice = noticeFor('gaps');
    const roadmapNotice = noticeFor('roadmap');

    const briefBody = editing
        ? html`<textarea
                class="consulting-editor"
                ref=${editorRef}
                value=${draft}
                spellcheck="false"
                placeholder="Write or edit the client brief (markdown)…"
                onInput=${handleInput}
                onBlur=${flush}
            ></textarea>`
        : (briefText
            ? html`<div
                    class="consulting-text"
                    title="Double-click to edit"
                    onDblClick=${enterEdit}
                ><${Markdown} text=${briefText} /></div>`
            : html`<div
                    class="bullet-empty consulting-editable"
                    title="Double-click to write the brief by hand"
                    onDblClick=${enterEdit}
                >No brief yet. Click Draft brief to have the AI draft one from the
                    conversation, or double-click here to write it yourself.</div>`);

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
            <span class="consulting-badge ${showConfirmed ? 'confirmed' : ''}">
                ${showConfirmed ? 'Confirmed' : 'Draft'}
            </span>
            <button
                class="pane-control-btn bullet-action-btn"
                title="Draft a client brief from the conversation with the AI"
                aria-label="Draft brief"
                disabled=${anyBusy}
                onClick=${onDraftBrief}
            >${busyMode === 'brief' ? BUSY_LABEL.brief : (briefText ? 'Re-draft' : 'Draft brief')}</button>
            <button
                class="pane-control-btn bullet-action-btn"
                title="Confirm this brief as the locked reference for gap analysis and the roadmap"
                aria-label="Confirm brief"
                disabled=${anyBusy || !briefText || showConfirmed}
                onClick=${onConfirmBrief}
            >Confirm</button>
        `;

    return html`
        <div class="live-text consulting-view">
            <div class="consulting-section">
                <div class="consulting-actions">
                    <span class="consulting-title">
                        ${editing ? 'Editing brief' : 'Client brief'}
                    </span>
                    <div class="consulting-actions-right">${rightControls}</div>
                </div>
                ${briefBody}
                ${!editing && briefNotice && html`<div class="bullet-status">${briefNotice}</div>`}
            </div>

            <div class="consulting-section">
                <div class="consulting-actions">
                    <span class="consulting-title">
                        Gap analysis
                        <span class="consulting-badge ${showConfirmed ? 'confirmed' : ''}">
                            ${showConfirmed ? 'Confirmed brief' : 'Speaker profile'}
                        </span>
                    </span>
                    <div class="consulting-actions-right">
                        <button
                            class="pane-control-btn bullet-action-btn"
                            title="Flag thin or contradictory parts of the conversation"
                            aria-label="Analyze gaps"
                            disabled=${anyBusy}
                            onClick=${onAnalyzeGaps}
                        >${busyMode === 'gaps' ? BUSY_LABEL.gaps : 'Analyze gaps'}</button>
                    </div>
                </div>
                ${gapsText
                    ? html`<div class="consulting-text"><${Markdown} text=${gapsText} /></div>`
                    : html`<div class="bullet-empty">
                        No gaps flagged yet. Analyze the conversation against the
                        reference to surface questions to ask before the meeting ends.
                    </div>`}
                ${gapsNotice && html`<div class="bullet-status">${gapsNotice}</div>`}
            </div>

            <div class="consulting-section">
                <div class="consulting-actions">
                    <span class="consulting-title">Execution roadmap</span>
                    <div class="consulting-actions-right">
                        <button
                            class="pane-control-btn bullet-action-btn"
                            title=${showConfirmed
                                ? 'Turn the confirmed brief and gaps into a prioritized plan'
                                : 'Confirm the brief first to generate a meaningful roadmap'}
                            aria-label="Generate roadmap"
                            disabled=${anyBusy || !showConfirmed}
                            onClick=${onGenerateRoadmap}
                        >${busyMode === 'roadmap' ? BUSY_LABEL.roadmap : 'Generate roadmap'}</button>
                    </div>
                </div>
                ${!showConfirmed && !roadmapText && html`
                    <div class="bullet-empty">Confirm the client brief to unlock the roadmap.</div>
                `}
                ${roadmapText
                    ? html`<div class="consulting-text"><${Markdown} text=${roadmapText} /></div>`
                    : (showConfirmed && html`<div class="bullet-empty">
                        No roadmap yet. Generate one from the confirmed brief and the flagged gaps.
                    </div>`)}
                ${roadmapNotice && html`<div class="bullet-status">${roadmapNotice}</div>`}
            </div>
        </div>
    `;
};
