import { h } from 'https://esm.sh/preact@10.19.3';
import htm from 'https://esm.sh/htm@3.1.1';
import { TranscriptionItem } from './TranscriptionItem.js';
import { EmptyState } from './EmptyState.js';

const html = htm.bind(h);

export const TranscriptionList = ({ transcriptions, currentSentence }) => {
    const allItems = [];
    
    if (currentSentence !== null && !currentSentence.isComplete) {
        allItems.push({
            text: currentSentence.text,
            timestamp: currentSentence.timestamp,
            isIncomplete: true
        });
    }

    allItems.push(...transcriptions);

    if (allItems.length === 0) {
        return html`<${EmptyState} />`;
    }

    return html`
        <div>
            ${allItems.map((item, index) => html`
                <${TranscriptionItem}
                    key=${index}
                    text=${item.text}
                    timestamp=${item.timestamp}
                    isIncomplete=${item.isIncomplete || false}
                />
            `)}
        </div>
    `;
};
