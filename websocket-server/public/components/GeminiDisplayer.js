import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

const MODE_LABELS = {
    manual: 'Manual',
    auto_reply: 'Auto-reply'
};

export const GeminiDisplayer = ({ geminiResults, geminiStatus }) => {
    const geminiRef = useRef(null);
    const hasContent = geminiResults.length > 0 || geminiStatus;

    useEffect(() => {
        if (geminiRef.current) {
            geminiRef.current.scrollTop = geminiRef.current.scrollHeight;
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

    const recentResults = geminiResults.slice(-10);

    return html`
        <div class="live-text gemini-view" ref=${geminiRef}>
            ${recentResults.map((resultObj, index) => {
                const isLatest = index === recentResults.length - 1;
                const style = isLatest
                    ? { opacity: '1', fontWeight: '600', fontSize: '14px' }
                    : { opacity: '0.7', fontWeight: 'normal', fontSize: '13px' };

                return html`
                    <div class="live-text-line gemini-line" style=${style} key=${resultObj.id}>
                        ${getModeBadge(resultObj.mode)}
                        <div class="gemini-text">${resultObj.text}</div>
                    </div>
                `;
            })}
            ${geminiStatus && html`
                <div class="gemini-status">${geminiStatus}</div>
            `}
        </div>
    `;
};
