export class GameProgressTracker {
    constructor() {
        this.storageKey = 'roleplay-game-progress';
    }

    getProgress() {
        try {
            const data = localStorage.getItem(this.storageKey);
            return data ? JSON.parse(data) : {};
        } catch (error) {
            console.error('Error reading game progress:', error);
            return {};
        }
    }

    getGameStatus(filename) {
        const progress = this.getProgress();
        return progress[filename] || null;
    }

    markGameAsStarted(filename) {
        const progress = this.getProgress();
        
        if (!progress[filename]) {
            progress[filename] = {
                status: 'in-progress',
                startedAt: new Date().toISOString(),
                lastPlayedAt: new Date().toISOString()
            };
        } else {
            progress[filename].lastPlayedAt = new Date().toISOString();
            if (progress[filename].status === 'finished') {
                progress[filename].status = 'in-progress';
            }
        }
        
        this.saveProgress(progress);
    }

    markGameAsFinished(filename) {
        const progress = this.getProgress();
        
        if (!progress[filename]) {
            progress[filename] = {
                status: 'finished',
                startedAt: new Date().toISOString(),
                finishedAt: new Date().toISOString(),
                lastPlayedAt: new Date().toISOString()
            };
        } else {
            progress[filename].status = 'finished';
            progress[filename].finishedAt = new Date().toISOString();
            progress[filename].lastPlayedAt = new Date().toISOString();
        }
        
        this.saveProgress(progress);
    }

    resetGameProgress(filename) {
        const progress = this.getProgress();
        delete progress[filename];
        this.saveProgress(progress);
    }

    saveProgress(progress) {
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(progress));
        } catch (error) {
            console.error('Error saving game progress:', error);
        }
    }

    getAllProgress() {
        return this.getProgress();
    }
}
