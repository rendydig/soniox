import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

/**
 * Connection dot. ``showText`` may be false (the live pane) to render only the
 * colored circle; the state stays available via title/aria-label.
 */
export const StatusIndicator = ({ connected, showText = true }) => {
    const label = connected ? 'Connected' : 'Disconnected - Reconnecting...';

    if (!showText) {
        return html`
            <div class="status status-compact">
                <div
                    class="status-indicator ${connected ? 'connected' : ''}"
                    title=${label}
                    aria-label=${label}
                    role="status"
                ></div>
            </div>
        `;
    }

    return html`
        <div class="status">
            <div>Status : </div>
            <div class="status-indicator ${connected ? 'connected' : ''}"></div>
            <span>${label}</span>
        </div>
    `;
};
