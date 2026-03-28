export function normalizeText(text) {
    return text
        .toLowerCase()
        .replace(/[^a-z0-9\s']/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

export function calculateSimilarity(actual, expected) {
    const normalizedActual = normalizeText(actual);
    const normalizedExpected = normalizeText(expected);

    if (!normalizedActual || !normalizedExpected) {
        return 0;
    }

    if (normalizedActual === normalizedExpected) {
        return 1;
    }

    const actualTokens = normalizedActual.split(' ').filter(Boolean);
    const expectedTokens = normalizedExpected.split(' ').filter(Boolean);
    const actualSet = new Set(actualTokens);
    const expectedSet = new Set(expectedTokens);
    const overlap = expectedTokens.filter((token) => actualSet.has(token)).length;
    const union = new Set([...actualSet, ...expectedSet]).size || 1;
    const jaccard = overlap / union;
    const editRatio = 1 - (levenshtein(normalizedActual, normalizedExpected) / Math.max(normalizedActual.length, normalizedExpected.length, 1));

    return (jaccard * 0.45) + (editRatio * 0.55);
}

export function levenshtein(source, target) {
    const rows = source.length + 1;
    const cols = target.length + 1;
    const table = Array.from({ length: rows }, () => new Array(cols).fill(0));

    for (let row = 0; row < rows; row += 1) {
        table[row][0] = row;
    }

    for (let col = 0; col < cols; col += 1) {
        table[0][col] = col;
    }

    for (let row = 1; row < rows; row += 1) {
        for (let col = 1; col < cols; col += 1) {
            const cost = source[row - 1] === target[col - 1] ? 0 : 1;
            table[row][col] = Math.min(
                table[row - 1][col] + 1,
                table[row][col - 1] + 1,
                table[row - 1][col - 1] + cost
            );
        }
    }

    return table[source.length][target.length];
}
