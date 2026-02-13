import { h } from 'https://esm.sh/preact@10.19.3';
import { useEffect, useRef } from 'https://esm.sh/preact@10.19.3/hooks';
import htm from 'https://esm.sh/htm@3.1.1';

const html = htm.bind(h);

function splitIntoSentences(text) {
    if (!text) return [];
    return text.split(/([.?!])/).reduce((acc, part, i, arr) => {
        if (i % 2 === 0 && part.trim()) {
            const sentence = part + (arr[i + 1] || '');
            acc.push(sentence.trim());
        }
        return acc;
    }, []);
}

export const LiveTranslationDisplayer = ({ finalizedTranslations, liveTranslationHost, liveTranslationSpeaker }) => {
    const translationRef = useRef(null);
    const hasContent = finalizedTranslations.length > 0 || liveTranslationHost || liveTranslationSpeaker;
    
    useEffect(() => {
        if (translationRef.current) {
            translationRef.current.scrollTop = translationRef.current.scrollHeight;
        }
    }, [finalizedTranslations, liveTranslationHost, liveTranslationSpeaker]);
    
    const getSourceBadge = (source) => {
        if (!source) return null;
        const isHost = source.toLowerCase() === 'host';
        const badgeClass = isHost ? 'source-badge-host' : 'source-badge-speakers';
        const emoji = isHost ? '🎤' : '🔊';
        return html`<span class="${badgeClass}">${emoji} ${source}</span>`;
    };
    
    if (!hasContent) {
        return html`
            <div class="live-text active translation-view">
                Waiting for translation...
            </div>
        `;
    }

    const recentTranslations = finalizedTranslations.slice(-10);
    
    const translationsWithSentences = recentTranslations.flatMap(translationObj => {
        const sentences = splitIntoSentences(translationObj.text);
        if (sentences.length === 0) {
            return [translationObj];
        }
        return sentences.map((sentence, idx) => ({
            ...translationObj,
            text: sentence,
            id: translationObj.id + '_' + idx
        }));
    });

    return html`
        <div class="live-text active translation-view" ref=${translationRef}>
            ${translationsWithSentences.map((translationObj, index) => {
                const isLatest = index === translationsWithSentences.length - 1;
                const style = isLatest 
                    ? { opacity: '1', fontWeight: '600', fontSize: '24px' }
                    : { opacity: '0.7', fontWeight: 'normal', fontSize: '18px' };
                
                return html`
                    <div class="live-text-line" style=${style} key=${translationObj.id}>
                        ${getSourceBadge(translationObj.source)}
                        <span class="finalized-text">${translationObj.text}</span>
                    </div>
                `;
            })}
            ${liveTranslationHost && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('host')}
                    <span class="live-text-updating">${liveTranslationHost}</span>
                </div>
            `}
            ${liveTranslationSpeaker && html`
                <div class="live-text-line" style=${{ opacity: '1', fontStyle: 'normal' }}>
                    ${getSourceBadge('speaker')}
                    <span class="live-text-updating">${liveTranslationSpeaker}</span>
                </div>
            `}
        </div>
    `;
};
