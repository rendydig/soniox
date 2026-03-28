export class ProgressManager {
    constructor(storageKey) {
        this.storageKey = storageKey;
        this.currentTurnIndex = 0;
        this.score = 0;
        this.streak = 0;
        this.completedTurns = [];
        this.attemptsPerTurn = {};
        this.history = {};
    }

    setStorageKey(key) {
        this.storageKey = key;
    }

    restore() {
        if (!this.storageKey) {
            return;
        }

        const saved = window.localStorage.getItem(this.storageKey);
        if (!saved) {
            return;
        }

        try {
            const parsed = JSON.parse(saved);
            this.currentTurnIndex = Number.isInteger(parsed.currentTurnIndex) ? parsed.currentTurnIndex : 0;
            this.score = Number.isFinite(parsed.score) ? parsed.score : 0;
            this.attemptsPerTurn = parsed.attemptsPerTurn || {};
            this.completedTurns = Array.isArray(parsed.completedTurns) ? parsed.completedTurns : [];
            this.history = parsed.history || {};
            this.streak = Number.isFinite(parsed.streak) ? parsed.streak : 0;
        } catch (error) {
            window.localStorage.removeItem(this.storageKey);
        }
    }

    persist() {
        if (!this.storageKey) {
            return;
        }

        window.localStorage.setItem(this.storageKey, JSON.stringify({
            currentTurnIndex: this.currentTurnIndex,
            score: this.score,
            attemptsPerTurn: this.attemptsPerTurn,
            completedTurns: this.completedTurns,
            lastPlayedAt: new Date().toISOString(),
            history: this.history,
            streak: this.streak
        }));
    }

    reset() {
        this.currentTurnIndex = 0;
        this.score = 0;
        this.streak = 0;
        this.completedTurns = [];
        this.attemptsPerTurn = {};
        this.history = {};
        this.persist();
    }

    markTurnCompleted(turnIndex) {
        if (!this.completedTurns.includes(turnIndex)) {
            this.completedTurns.push(turnIndex);
        }
    }

    getAttemptsForTurn(turnIndex) {
        return this.attemptsPerTurn[turnIndex] || 0;
    }

    incrementAttemptsForTurn(turnIndex) {
        const nextValue = this.getAttemptsForTurn(turnIndex) + 1;
        this.attemptsPerTurn[turnIndex] = nextValue;
        return nextValue;
    }

    addToHistory(turnIndex, transcript, similarity, attempts) {
        const historyKey = String(turnIndex);
        if (!this.history[historyKey]) {
            this.history[historyKey] = [];
        }
        this.history[historyKey].push({ 
            transcript, 
            similarity, 
            attempts, 
            createdAt: new Date().toISOString() 
        });
    }

    incrementScore() {
        this.score += 1;
    }

    incrementStreak() {
        this.streak += 1;
    }

    resetStreak() {
        this.streak = 0;
    }

    advanceTurn() {
        this.currentTurnIndex += 1;
    }

    getState() {
        return {
            currentTurnIndex: this.currentTurnIndex,
            score: this.score,
            streak: this.streak,
            completedTurns: this.completedTurns,
            attemptsPerTurn: this.attemptsPerTurn,
            history: this.history
        };
    }
}
