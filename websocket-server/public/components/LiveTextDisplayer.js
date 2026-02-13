import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

export const LiveTextDisplayer = ({ finalizedSentences, liveTextHost, liveTextSpeaker, corrections, correctionEnabled }) => {
    const liveTextRef = useRef(null);
    const hasContent = finalizedSentences.length > 0 || liveTextHost || liveTextSpeaker;
    
    useEffect(() => {
        if (liveTextRef.current) {
            liveTextRef.current.scrollTop = liveTextRef.current.scrollHeight;
        }
    }, [finalizedSentences, liveTextHost, liveTextSpeaker]);
    
    const getSourceBadge = (source) => {
        if (!source) return null;
        const isHost = source.toLowerCase() === 'host';
        const badgeClass = isHost ? 'source-badge-host' : 'source-badge-speakers';
        const emoji = isHost ? '🎤' : '🔊';
        return html`<span class="${badgeClass}">${emoji} ${source}</span>`;
    };
    
    if (!hasContent) {
        return html`
            <div class="live-text active">
                Listening...
            </div>
        `;
    }

    const recentSentences = finalizedSentences.slice(-10);

    return html`
        <div class="live-text active" ref=${liveTextRef}>
            ${recentSentences.map((sentenceObj, index) => {
                const isLatest = index === recentSentences.length - 1;
                const style = isLatest 
                     ? { opacity: '1', fontWeight: '600', fontSize: '24px' }
                    : { opacity: '0.7', fontWeight: 'normal', fontSize: '18px' };
                const correction = corrections[sentenceObj.text];
                
                return html`
                    <div class="live-text-line" style=${style} key=${sentenceObj.id}>
                        ${getSourceBadge(sentenceObj.source)}
                        ${correctionEnabled && correction ? html`
                            ${correction.status === 'good' ? html`
                                <span class="correction-badge good">✓</span>
                                <span class="finalized-text">${sentenceObj.text}</span>
                            ` : correction.status === 'bad' ? html`
                                <span class="correction-badge bad">✗</span>
                                <span class="finalized-text original">${sentenceObj.text}</span>
                                <span class="correction-suggestion">→ ${correction.corrected}</span>
                            ` : html`
                                <span class="finalized-text">${sentenceObj.text}</span>
                            `}
                        ` : html`
                            <span class="finalized-text">${sentenceObj.text}</span>
                        `}
                    </div>
                `;
            })}
            ${liveTextHost && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('host')}
                    <span class="live-text-updating">${liveTextHost}</span>
                </div>
            `}
            ${liveTextSpeaker && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('speaker')}
                    <span class="live-text-updating">${liveTextSpeaker}</span>
                </div>
            `}
        </div>
    `;
};
