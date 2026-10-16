import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef, useState } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

// Keep in sync with the `.bullet-text` transition in index.css.
const FADE_MS = 180;

// Padlock glyph: closed shackle when locked, open/tilted when unlocked.
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

/**
 * One bullet, keyed by index so a text change at the same index crossfades:
 * fade the old text out, swap, then fade the new text in. A newly mounted
 * index (i.e. the list grew) fades in on its first paint.
 *
 * The lock toggle sits after the text; its number marker stays outside the
 * crossfading span so only the text animates.
 */
const BulletItem = ({ text, index, locked, onToggleLock }) => {
    const [shown, setShown] = useState(text);
    const [phase, setPhase] = useState('in');
    const firstRender = useRef(true);
    const timers = useRef([]);

    useEffect(() => {
        if (firstRender.current) {
            // New index: fade in on first paint, then settle.
            firstRender.current = false;
            timers.current.push(setTimeout(() => setPhase('idle'), FADE_MS));
            return;
        }
        // Same index, new text: fade out, swap while invisible, fade in.
        setPhase('out');
        timers.current.push(setTimeout(() => {
            setShown(text);
            setPhase('in');
            timers.current.push(setTimeout(() => setPhase('idle'), FADE_MS));
        }, FADE_MS));
    }, [text]);

    useEffect(() => () => {
        timers.current.forEach(clearTimeout);
        timers.current = [];
    }, []);

    return html`
        <li class="bullet-item ${locked ? 'locked' : ''}">
            <span class="bullet-number" aria-hidden="true">${index + 1}.</span>
            <span class="bullet-text ${phase}">${shown}</span>
            <button
                type="button"
                class="bullet-lock ${locked ? 'locked' : ''}"
                aria-pressed=${locked ? 'true' : 'false'}
                title=${locked ? 'Unlock' : 'Lock this point (kept on Rebuild)'}
                aria-label=${locked ? 'Unlock this point' : 'Lock this point'}
                onClick=${() => onToggleLock && onToggleLock(index)}
            >
                <${LockIcon} locked=${locked} />
            </button>
        </li>
    `;
};

/** Rolling bullet-point list with a numbered marker + lock toggle per item. */
export const BulletPointsList = ({ items, status, locks, onToggleLock }) => {
    const hasItems = Array.isArray(items) && items.length > 0;
    const lockAt = (index) => Array.isArray(locks) && locks[index] === true;

    return html`
        <div class="live-text bullet-view">
            ${status && html`<div class="bullet-status">${status}</div>`}
            ${hasItems
                ? html`
                    <ul class="bullet-list">
                        ${items.map((text, index) => html`
                            <${BulletItem}
                                key=${index}
                                text=${text}
                                index=${index}
                                locked=${lockAt(index)}
                                onToggleLock=${onToggleLock}
                            />
                        `)}
                    </ul>
                `
                : html`
                    <div class="bullet-empty">
                        Waiting for the conversation… (enable Auto Bullet Points in Settings,
                        or use Fetch new / press CTRL+ALT+P to update)
                    </div>
                `}
        </div>
    `;
};
