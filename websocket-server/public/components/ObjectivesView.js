import { h } from 'https://esm.sh/preact@10.19.3';
import { useState } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

// Padlock glyph: closed shackle when locked, open/tilted when unlocked
// (same drawing as BulletPointsList, so the two lock affordances read alike).
const LockIcon = ({ locked }) => html`
    <svg
        class="bullet-lock-icon"
        viewBox="0 0 24 24"
        width="12"
        height="12"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
    >
        <rect x="4" y="11" width="16" height="10" rx="2" ry="2"></rect>
        ${locked
            ? html`<path d="M8 11V7a4 4 0 0 1 8 0v4"></path>`
            : html`<path d="M8 11V7a4 4 0 0 1 7.5-2"></path>`}
    </svg>
`;

/** "14:03:27" for a history entry's ISO timestamp. */
const formatTime = (ts) => {
    const date = new Date(ts);
    return isNaN(date.getTime()) ? '' : date.toLocaleTimeString();
};

/**
 * Objectives tab: the session-level list of what the conversation is working
 * towards, which one is currently active, and a timeline of the transitions.
 *
 * The tracker lives in Python (`ObjectiveController`); this view only renders
 * the state it is sent and sends back the four control messages:
 * `add_objective`, `remove_objective`, `set_objective_lock` and
 * `trigger_objective_prediction`. A locked objective is pinned: the tracker
 * cannot move the focus away from it, and the reply prompt is told to serve it.
 *
 * Every block is rendered **unconditionally** and hidden with an `empty` class
 * instead of a conditional child. Each of these sections appears and disappears
 * as the frames arrive, and Preact's diff mis-inserts a child when a falsy slot
 * in the middle of the children list turns into an element while a following
 * slot changes shape (observed as "Failed to execute 'insertBefore' on 'Node'",
 * which also dropped the timeline block from the DOM).
 */
export const ObjectivesView = ({
    items,
    locks,
    active,
    history,
    status,
    onToggleLock,
    onAdd,
    onRemove,
    onPredict
}) => {
    const list = Array.isArray(items) ? items : [];
    const lockAt = (index) => Array.isArray(locks) && locks[index] === true;
    const timeline = Array.isArray(history) ? history : [];
    const focus = active && typeof active === 'object' ? active : {};
    const hasFocus = typeof focus.text === 'string' && focus.text.length > 0;
    const statusText = typeof status === 'string' ? status : '';
    const [draft, setDraft] = useState('');

    const submit = (event) => {
        if (event && typeof event.preventDefault === 'function') event.preventDefault();
        const text = draft.trim();
        if (!text) return;
        if (typeof onAdd === 'function') onAdd(text);
        setDraft('');
    };

    return html`
        <div class="live-text objectives-view">
            <div class="objectives-actions">
                <span class="consulting-title">Session objectives</span>
                <div class="consulting-actions-right">
                    <button
                        class="pane-control-btn bullet-action-btn"
                        title="Ask the tracker which objective the conversation is on right now"
                        aria-label="Predict the active objective"
                        onClick=${() => typeof onPredict === 'function' && onPredict()}
                    >Predict now</button>
                </div>
            </div>

            <div class=${'objectives-active' + (hasFocus ? '' : ' empty')}>
                <span class="objectives-active-label">Working towards</span>
                <strong class="objectives-active-text">${focus.text || ''}</strong>
                <span class=${'consulting-badge confirmed' + (focus.locked ? '' : ' empty')}>
                    Locked
                </span>
            </div>

            <form class="objectives-add" onSubmit=${submit}>
                <input
                    class="objectives-input"
                    type="text"
                    value=${draft}
                    spellcheck="false"
                    placeholder="Add an objective…"
                    aria-label="New objective"
                    onInput=${(event) => setDraft(event.target.value)}
                />
                <button
                    class="pane-control-btn bullet-action-btn"
                    type="submit"
                    title="Add this objective to the session"
                    aria-label="Add objective"
                >Add</button>
            </form>

            <div class=${'bullet-status' + (statusText ? '' : ' empty')}>${statusText}</div>

            <ul class="bullet-list objectives-list">
                ${list.map((text, index) => html`
                    <li
                        class="bullet-item objective-item ${lockAt(index) ? 'locked' : ''} ${index === focus.index ? 'active' : ''}"
                    >
                        <span class="bullet-number" aria-hidden="true">${index + 1}.</span>
                        <span class="bullet-text">${text}</span>
                        <button
                            type="button"
                            class="bullet-lock ${lockAt(index) ? 'locked' : ''}"
                            aria-pressed=${lockAt(index) ? 'true' : 'false'}
                            title=${lockAt(index)
                                ? 'Unlock (the tracker may move off this objective)'
                                : 'Lock this objective (the tracker cannot move off it)'}
                            aria-label=${lockAt(index) ? 'Unlock this objective' : 'Lock this objective'}
                            onClick=${() => typeof onToggleLock === 'function'
                                && onToggleLock(index, text, !lockAt(index))}
                        >
                            <${LockIcon} locked=${lockAt(index)} />
                        </button>
                        <button
                            type="button"
                            class="objective-remove"
                            title="Remove this objective"
                            aria-label="Remove this objective"
                            onClick=${() => typeof onRemove === 'function' && onRemove(index)}
                        >×</button>
                    </li>
                `)}
            </ul>

            <div class=${'bullet-empty' + (list.length ? ' empty' : '')}>
                No objectives yet. Add the outcomes this conversation should reach —
                the tracker then follows which one is being worked on.
            </div>

            <div class=${'objectives-history' + (timeline.length ? '' : ' empty')}>
                <div class="consulting-title">History</div>
                <ul class="objectives-timeline">
                    ${timeline.map((entry) => html`
                        <li class="objectives-timeline-item">
                            <span class="objectives-timeline-time">
                                ${formatTime(entry && entry.ts)}
                            </span>
                            <span class="objectives-timeline-text">
                                ${String((entry && entry.text) || '')}
                            </span>
                            <span class="objectives-timeline-meta">
                                ${String(Math.round((Number(entry && entry.confidence) || 0) * 100)) + '%'}
                                ${(entry && entry.source) ? ` · ${entry.source}` : ''}
                            </span>
                        </li>
                    `)}
                </ul>
            </div>
        </div>
    `;
};
