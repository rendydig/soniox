import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

function formatTime(timestamp) {
    if (!timestamp) return 'Just now';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

export const TranscriptionItem = ({ text, timestamp, isIncomplete }) => {
    const style = isIncomplete ? { opacity: '0.7', borderLeftColor: '#f59e0b' } : {};
    
    return html`
        <div class="transcription-item" style=${style}>
            <div class="transcription-text">${text}</div>
            <div class="transcription-time">${formatTime(timestamp)}</div>
        </div>
    `;
};
