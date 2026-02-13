export function formatTime(timestamp) {
    if (!timestamp) return 'Just now';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
}

export function endsWithSentenceTerminator(text) {
    if (!text || text.length === 0) return false;
    const trimmed = text.trim();
    const lastChar = trimmed[trimmed.length - 1];
    return lastChar === '.' || lastChar === '!' || lastChar === '?';
}

export function splitIntoSentences(text) {
    if (!text) return [];
    return text.split(/([.?!])/).reduce((acc, part, i, arr) => {
        if (i % 2 === 0 && part.trim()) {
            const sentence = part + (arr[i + 1] || '');
            acc.push(sentence.trim());
        }
        return acc;
    }, []);
}