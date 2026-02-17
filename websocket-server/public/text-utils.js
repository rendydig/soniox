export function normalizeText(text) {
    return text
        .toLowerCase()
        .replace(/'/g, '')
        .replace(/-/g, ' ')
        .replace(/[.,!?;:"()\[\]{}]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

export function calculateSimilarity(str1, str2) {
    const words1 = str1.split(' ');
    const words2 = str2.split(' ');
    
    let matchCount = 0;
    const maxLength = Math.max(words1.length, words2.length);
    
    for (let word of words1) {
        if (words2.includes(word)) {
            matchCount++;
        }
    }
    
    return matchCount / maxLength;
}
