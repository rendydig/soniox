function isAsianLanguage(lang) {
    return ['ja-JP', 'zh-CN', 'zh-TW', 'ko-KR'].includes(lang);
}

function normalizeTextForWordBased(text) {
    return text
        .toLowerCase()
        .replace(/'/g, '')
        .replace(/-/g, ' ')
        .replace(/[.,!?;:"()\[\]{}]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

function normalizeTextForAsian(text) {
    return text
        .toLowerCase()
        .replace(/[\s　]/g, '')
        .replace(/[.,!?;:"()\[\]{}。、！？；：「」『』（）【】]/g, '')
        .replace(/[ァ-ン]/g, (match) => {
            return String.fromCharCode(match.charCodeAt(0) - 0x60);
        })
        .trim();
}

export function normalizeText(text, lang = 'en-US') {
    if (isAsianLanguage(lang)) {
        return normalizeTextForAsian(text);
    }
    return normalizeTextForWordBased(text);
}

function calculateSimilarityWordBased(str1, str2) {
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

function calculateSimilarityCharacterBased(str1, str2) {
    if (!str1 || !str2) return 0;
    
    const len1 = str1.length;
    const len2 = str2.length;
    const maxLen = Math.max(len1, len2);
    
    if (maxLen === 0) return 1;
    
    const matrix = Array(len1 + 1).fill(null).map(() => Array(len2 + 1).fill(0));
    
    for (let i = 0; i <= len1; i++) matrix[i][0] = i;
    for (let j = 0; j <= len2; j++) matrix[0][j] = j;
    
    for (let i = 1; i <= len1; i++) {
        for (let j = 1; j <= len2; j++) {
            const cost = str1[i - 1] === str2[j - 1] ? 0 : 1;
            matrix[i][j] = Math.min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost
            );
        }
    }
    
    const distance = matrix[len1][len2];
    return 1 - (distance / maxLen);
}

export function calculateSimilarity(str1, str2, lang = 'en-US') {
    if (isAsianLanguage(lang)) {
        return calculateSimilarityCharacterBased(str1, str2);
    }
    return calculateSimilarityWordBased(str1, str2);
}
