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

const textOf = (value) => (typeof value === 'string' ? value.trim() : '');
const listOf = (value) => (Array.isArray(value) ? value.filter((e) => textOf(e)) : []);

/**
 * KYC "Know Your Customer" profile of the [speaker], maintained by the same
 * bullet-points AI call. Renders identity rows (Name / Location / Occupation)
 * and the four list sections; entirely blank profile → empty-state hint.
 */
export const SpeakerProfile = ({ profile, status }) => {
    const p = profile && typeof profile === 'object' ? profile : {};

    const rows = IDENTITY_ROWS
        .map((row) => ({ ...row, value: textOf(p[row.key]) }))
        .filter((row) => row.value);
    const sections = SECTIONS
        .map((sec) => ({ ...sec, items: listOf(p[sec.key]) }))
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
                                </div>
                            `)}
                        </div>
                    `}
                    ${sections.map((sec) => html`
                        <div class="kyc-section" key=${sec.key}>
                            <div class="kyc-heading">${sec.label}</div>
                            <ul class="kyc-list">
                                ${sec.items.map((entry, index) => html`
                                    <li
                                        class="bullet-item kyc-item ${sec.key === 'pain_points' ? 'kyc-pain' : ''}"
                                        key=${index}
                                    >
                                        <span class="kyc-marker" aria-hidden="true">•</span>
                                        <span class="bullet-text">${textOf(entry)}</span>
                                    </li>
                                `)}
                            </ul>
                        </div>
                    `)}
                `}
        </div>
    `;
};
