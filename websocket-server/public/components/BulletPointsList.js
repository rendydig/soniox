import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef, useState } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

// Keep in sync with the `.bullet-text` transition in index.css.
const FADE_MS = 180;

/**
 * One bullet, keyed by index so a text change at the same index crossfades:
 * fade the old text out, swap, then fade the new text in. A newly mounted
 * index (i.e. the list grew) fades in on its first paint.
 */
const BulletItem = ({ text, index }) => {
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
        <li class="bullet-item">
            <span class="bullet-number" aria-hidden="true">${index + 1}.</span>
            <span class="bullet-text ${phase}">${shown}</span>
        </li>
    `;
};

/** Rolling bullet-point list with a numbered marker per item. */
export const BulletPointsList = ({ items, status }) => {
    const hasItems = Array.isArray(items) && items.length > 0;

    return html`
        <div class="live-text bullet-view">
            ${status && html`<div class="bullet-status">${status}</div>`}
            ${hasItems
                ? html`
                    <ul class="bullet-list">
                        ${items.map((text, index) => html`
                            <${BulletItem} key=${index} text=${text} index=${index} />
                        `)}
                    </ul>
                `
                : html`
                    <div class="bullet-empty">
                        Waiting for the conversation… (enable Auto Bullet Points in Settings,
                        or press CTRL+ALT+P to update)
                    </div>
                `}
        </div>
    `;
};
