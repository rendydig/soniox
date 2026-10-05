import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';
import { Markdown } from './Markdown.js';

const html = htm.bind(h);

const MODE_LABELS = {
    manual: 'Manual',
    auto_reply: 'Auto-reply'
};

export const GeminiDisplayer = ({ geminiResults, geminiStatus }) => {
    const geminiRef = useRef(null);
    const latest = geminiResults[geminiResults.length - 1];
    const hasContent = geminiResults.length > 0 || geminiStatus;

    useEffect(() => {
        if (geminiRef.current) {
            geminiRef.current.scrollTop = 0;
        }
    }, [geminiResults, geminiStatus]);

    const getModeBadge = (mode) => {
        if (!mode) return null;
        const label = MODE_LABELS[mode] || mode;
        const badgeClass = mode === 'auto_reply' ? 'gemini-badge-auto' : 'gemini-badge-manual';
        return html`<span class="${badgeClass}">${label}</span>`;
    };

    if (!hasContent) {
        return html`
            <div class="live-text gemini-view" ref=${geminiRef}>
                Waiting for Gemini suggestion...
            </div>
        `;
    }

    return html`
        <div class="live-text gemini-view" ref=${geminiRef}>
            ${latest && html`
                <div class="live-text-line gemini-line" key=${latest.id}>
                    ${getModeBadge(latest.mode)}
                    <div class="gemini-text"><${Markdown} text=${latest.text} /></div>
                </div>
            `}
            ${geminiStatus && html`
                <div class="gemini-status">${geminiStatus}</div>
            `}
        </div>
    `;
};
