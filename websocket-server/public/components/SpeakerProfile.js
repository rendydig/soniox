import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

/** Identity rows: shown only when the field is a non-empty string. */
const IDENTITY_ROWS = [
    { key: 'name', label: 'Name' },
    { key: 'location', label: 'Location' },
    { key: 'occupation', label: 'Occupation' }
];

/** List sections: shown only when the field is a non-empty array. */
const SECTIONS = [
    { key: 'interests', label: 'Interests' },
    { key: 'goals', label: 'Goals' },
    { key: 'pain_points', label: 'Pain Points' },
    { key: 'facts', label: 'Other Facts' }
];

// Padlock glyph: closed shackle when locked, open/tilted when unlocked (same
// drawing as BulletPointsList/ObjectivesView, so every lock reads alike).
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

const textOf = (value) => (typeof value === 'string' ? value.trim() : '');

/**
 * A list field's items with their **original** index, so a padlock click can
 * address the entry the backend knows even after empty slots are filtered out.
 */
const itemsOf = (value) => (Array.isArray(value)
    ? value
        .map((entry, index) => ({ text: textOf(entry), index }))
        .filter((item) => item.text)
    : []);

/**
 * KYC "Know Your Customer" profile of the [speaker], maintained by the same
 * bullet-points AI call. Renders identity rows (Name / Location / Occupation)
 * and the four list sections; entirely blank profile → empty-state hint.
 *
 * Every value carries a padlock: a **locked** value is kept verbatim by the
 * backend (`BulletPointsController._merge_speaker`), so an AI update can neither
 * overwrite, reword nor drop it — a locked list field only ever grows. Locks are
 * sent back with `set_speaker_lock`; the pane renders the flags the app echoes.
 */
export const SpeakerProfile = ({ profile, locks, status, onToggleLock }) => {
    const p = profile && typeof profile === 'object' ? profile : {};
    const l = locks && typeof locks === 'object' ? locks : {};
    const rowLocked = (field) => l[field] === true;
    const itemLocked = (field, index) => Array.isArray(l[field]) && l[field][index] === true;

    const toggle = (field, index, item, locked) => {
        if (typeof onToggleLock === 'function') onToggleLock(field, index, item, locked);
    };

    const rows = IDENTITY_ROWS
        .map((row) => ({ ...row, value: textOf(p[row.key]) }))
        .filter((row) => row.value);
    const sections = SECTIONS
        .map((sec) => ({ ...sec, items: itemsOf(p[sec.key]) }))
        .filter((sec) => sec.items.length > 0);
    const isEmpty = rows.length === 0 && sections.length === 0;

    return html`
        <div class="live-text speaker-view">
            ${status && html`<div class="bullet-status">${status}</div>`}
            ${isEmpty
                ? html`
                    <div class="bullet-empty">
                        Nothing known about the speaker yet… (enable Auto Bullet Points
                        in Settings, or press CTRL+ALT+P to update)
                    </div>
                `
                : html`
                    ${rows.length > 0 && html`
                        <div class="kyc-section">
                            ${rows.map((row) => html`
                                <div class="kyc-row" key=${row.key}>
                                    <span class="kyc-label">${row.label}</span>
                                    <span class="kyc-value">${row.value}</span>
                                    <button
                                        type="button"
                                        class="bullet-lock ${rowLocked(row.key) ? 'locked' : ''}"
                                        aria-pressed=${rowLocked(row.key) ? 'true' : 'false'}
                                        title=${rowLocked(row.key)
                                            ? 'Unlock (the AI may update this again)'
                                            : 'Lock this value (the AI keeps it verbatim)'}
                                        aria-label=${rowLocked(row.key)
                                            ? 'Unlock this profile value'
                                            : 'Lock this profile value'}
                                        onClick=${() => toggle(row.key, null, row.value, !rowLocked(row.key))}
                                    >
                                        <${LockIcon} locked=${rowLocked(row.key)} />
                                    </button>
                                </div>
                            `)}
                        </div>
                    `}
                    ${sections.map((sec) => html`
                        <div class="kyc-section" key=${sec.key}>
                            <div class="kyc-heading">${sec.label}</div>
                            <ul class="kyc-list">
                                ${sec.items.map((item) => html`
                                    <li
                                        class="bullet-item kyc-item ${sec.key === 'pain_points' ? 'kyc-pain' : ''} ${itemLocked(sec.key, item.index) ? 'locked' : ''}"
                                        key=${item.index}
                                    >
                                        <span class="kyc-marker" aria-hidden="true">•</span>
                                        <span class="bullet-text">${item.text}</span>
                                        <button
                                            type="button"
                                            class="bullet-lock ${itemLocked(sec.key, item.index) ? 'locked' : ''}"
                                            aria-pressed=${itemLocked(sec.key, item.index) ? 'true' : 'false'}
                                            title=${itemLocked(sec.key, item.index)
                                                ? 'Unlock (the AI may reword or drop this)'
                                                : 'Lock this item (kept on every update)'}
                                            aria-label=${itemLocked(sec.key, item.index)
                                                ? 'Unlock this profile item'
                                                : 'Lock this profile item'}
                                            onClick=${() => toggle(sec.key, item.index, item.text,
                                                !itemLocked(sec.key, item.index))}
                                        >
                                            <${LockIcon} locked=${itemLocked(sec.key, item.index)} />
                                        </button>
                                    </li>
                                `)}
                            </ul>
                        </div>
                    `)}
                `}
        </div>
    `;
};
