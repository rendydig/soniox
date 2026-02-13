import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

export const StatusIndicator = ({ connected }) => {
    return html`
        <div class="status">
            <div>Status : </div>
            <div class="status-indicator ${connected ? 'connected' : ''}"></div>
            <span>${connected ? 'Connected' : 'Disconnected - Reconnecting...'}</span>
        </div>
    `;
};
