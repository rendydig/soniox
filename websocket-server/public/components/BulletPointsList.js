import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

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
                            <li class="bullet-item" key=${index}>
                                <span class="bullet-number" aria-hidden="true">${index + 1}.</span>
                                <span class="bullet-text">${text}</span>
                            </li>
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
