const DEFAULT_CONVERSATION_FILE = 'english-1.json';
const USER_SPEAKER = 'you';
const MAX_ATTEMPTS = 3;
const ACCEPT_THRESHOLD = 0.78;
const RETRY_THRESHOLD = 0.52;
const MIN_WORD_COUNT = 2;
const SILENCE_TIMEOUT_MS = 1500;

class RoleplayConversationPlayer {
    constructor() {
        this.conversation = null;
        this.dialogue = [];
        this.currentTurnIndex = 0;
        this.score = 0;
        this.streak = 0;
        this.completedTurns = [];
        this.attemptsPerTurn = {};
        this.history = {};
        this.state = 'idle';
        this.recognition = null;
        this.recognitionSupported = false;
        this.recognitionActive = false;
        this.permissionDenied = false;
        this.lastSpeechAt = 0;
        this.silenceTimer = null;
        this.currentTranscript = '';
        this.finalTranscript = '';
        this.shouldEvaluateOnRecognitionEnd = false;
        this.botReadyForNext = false;
        this.turnResolved = false;
        this.storageKey = '';
        this.currentFile = this.getConversationFile();

        this.elements = {
            title: document.getElementById('conversationTitle'),
            meta: document.getElementById('conversationMeta'),
            turnCounter: document.getElementById('turnCounter'),
            stateLabel: document.getElementById('stateLabel'),
            progressFill: document.getElementById('progressFill'),
            speakerBadge: document.getElementById('speakerBadge'),
            turnTime: document.getElementById('turnTime'),
            englishLine: document.getElementById('englishLine'),
            translationLine: document.getElementById('translationLine'),
            turnPrompt: document.getElementById('turnPrompt'),
            turnHint: document.getElementById('turnHint'),
            replayBtn: document.getElementById('replayBtn'),
            // nextBtn: document.getElementById('nextBtn'),
            retryBtn: document.getElementById('retryBtn'),
            micStatusDot: document.getElementById('micStatusDot'),
            micStatusText: document.getElementById('micStatusText'),
            attemptInfo: document.getElementById('attemptInfo'),
            transcriptOutput: document.getElementById('transcriptOutput'),
            resultOutput: document.getElementById('resultOutput'),
            manualInput: document.getElementById('manualInput'),
            submitManualBtn: document.getElementById('submitManualBtn'),
            expectedWrap: document.getElementById('expectedWrap'),
            expectedOutput: document.getElementById('expectedOutput'),
            scoreLabel: document.getElementById('scoreLabel'),
            currentSpeakerStat: document.getElementById('currentSpeakerStat'),
            completedTurnsStat: document.getElementById('completedTurnsStat'),
            streakStat: document.getElementById('streakStat'),
            fileNameStat: document.getElementById('fileNameStat'),
            restartBtn: document.getElementById('restartBtn')
        };

        this.bindEvents();
        this.initSpeechRecognition();
        this.loadConversation();
    }

    getConversationFile() {
        const params = new URLSearchParams(window.location.search);
        return params.get('file') || DEFAULT_CONVERSATION_FILE;
    }

    async loadConversation() {
        this.setState('loadingTurn');
        this.elements.fileNameStat.textContent = this.currentFile;

        try {
            const response = await fetch(`./assets/${encodeURIComponent(this.currentFile)}`);
            if (!response.ok) {
                throw new Error(`Unable to load conversation file: ${this.currentFile}`);
            }

            this.conversation = await response.json();
            this.dialogue = Array.isArray(this.conversation.dialogue) ? this.conversation.dialogue : [];
            this.storageKey = `roleplay-progress:${this.currentFile}`;
            this.restoreProgress();
            this.renderConversationMeta();
            this.renderTurn();
        } catch (error) {
            this.elements.title.textContent = 'Failed to load conversation';
            this.elements.meta.textContent = error.message;
            this.updateResult(error.message, false);
            this.setState('idle');
        }
    }

    bindEvents() {
        this.elements.replayBtn.addEventListener('click', () => this.handleReplay());
        // this.elements.nextBtn.addEventListener('click', () => this.advanceTurn());
        this.elements.retryBtn.addEventListener('click', () => this.handleRetry());
        this.elements.submitManualBtn.addEventListener('click', () => this.submitManualInput());
        this.elements.restartBtn.addEventListener('click', () => this.restartSession());
    }

    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            this.recognitionSupported = false;
            this.elements.micStatusText.textContent = 'Speech recognition unavailable';
            return;
        }

        this.recognitionSupported = true;
        this.recognition = new SpeechRecognition();
        this.recognition.lang = 'en-US';
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.maxAlternatives = 1;

        this.recognition.onstart = () => {
            this.recognitionActive = true;
            this.shouldEvaluateOnRecognitionEnd = true;
            this.lastSpeechAt = Date.now();
            this.updateMicStatus('Listening for your answer', 'listening');
            this.startSilenceMonitor();
        };

        this.recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = this.finalTranscript;

            for (let index = event.resultIndex; index < event.results.length; index += 1) {
                const chunk = event.results[index][0]?.transcript?.trim() || '';
                if (!chunk) {
                    continue;
                }

                if (event.results[index].isFinal) {
                    finalTranscript = `${finalTranscript} ${chunk}`.trim();
                } else {
                    interimTranscript = `${interimTranscript} ${chunk}`.trim();
                }
            }

            this.finalTranscript = finalTranscript;
            this.currentTranscript = `${finalTranscript} ${interimTranscript}`.trim();
            if (this.currentTranscript) {
                this.lastSpeechAt = Date.now();
            }
            this.updateTranscript(this.currentTranscript || 'Listening...', true);
        };

        this.recognition.onerror = (event) => {
            this.stopSilenceMonitor();
            this.recognitionActive = false;

            if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                this.permissionDenied = true;
                this.updateMicStatus('Microphone permission denied. Use manual input.', 'idle');
                this.updateResult('Microphone permission denied. You can type your answer instead.', false);
                return;
            }

            if (event.error === 'no-speech') {
                this.updateMicStatus('We did not catch that. Try again.', 'idle');
                this.updateResult('We did not catch that. Try speaking again or type your answer.', false);
                this.elements.retryBtn.disabled = false;
                return;
            }

            this.updateMicStatus(`Recognition error: ${event.error}`, 'idle');
            this.updateResult(`Recognition error: ${event.error}`, false);
        };

        this.recognition.onend = () => {
            this.stopSilenceMonitor();
            const shouldEvaluate = this.shouldEvaluateOnRecognitionEnd;
            this.recognitionActive = false;
            this.shouldEvaluateOnRecognitionEnd = false;
            if (!shouldEvaluate) {
                return;
            }
            this.finishUserListening();
        };
    }

    renderConversationMeta() {
        this.elements.title.textContent = this.conversation.title || 'Roleplay conversation';
        const duration = this.conversation.estimated_duration_minutes
            ? `${this.conversation.estimated_duration_minutes} min`
            : 'Unknown duration';
        const theme = this.conversation.theme || 'Conversation practice';
        this.elements.meta.textContent = `${theme} • ${duration} • ${this.dialogue.length} turns`;
    }

    restoreProgress() {
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

    persistProgress() {
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

    restartSession() {
        this.stopRecognition();
        window.speechSynthesis.cancel();
        this.currentTurnIndex = 0;
        this.score = 0;
        this.streak = 0;
        this.completedTurns = [];
        this.attemptsPerTurn = {};
        this.history = {};
        this.persistProgress();
        this.renderTurn();
    }

    getCurrentTurn() {
        return this.dialogue[this.currentTurnIndex] || null;
    }

    isUserTurn(turn) {
        return (turn?.speaker || '').trim().toLowerCase() === USER_SPEAKER;
    }

    renderTurn() {
        const turn = this.getCurrentTurn();
        if (!turn) {
            this.renderCompletedState();
            return;
        }

        this.turnResolved = false;
        this.botReadyForNext = false;
        this.finalTranscript = '';
        this.currentTranscript = '';
        this.elements.manualInput.value = '';
        this.elements.expectedWrap.classList.add('hidden');
        this.elements.expectedOutput.textContent = '';
        this.elements.retryBtn.disabled = true;
        // this.elements.nextBtn.disabled = true;
        this.updateTranscript('Your speech will appear here.', false, true);
        this.updateResult('Waiting for this turn to start.', false, true);
        this.updateStats(turn);

        const totalTurns = this.dialogue.length;
        this.elements.turnCounter.textContent = `Turn ${this.currentTurnIndex + 1} / ${totalTurns}`;
        this.elements.progressFill.style.width = `${((this.currentTurnIndex) / totalTurns) * 100}%`;
        this.elements.speakerBadge.textContent = turn.speaker || 'Unknown';
        this.elements.turnTime.textContent = turn.time || '--:--';
        this.elements.englishLine.textContent = turn.english || '';
        this.elements.translationLine.textContent = turn.indonesian || '';
        this.elements.attemptInfo.textContent = `Attempts: ${this.getAttemptsForTurn()}`;

        if (this.isUserTurn(turn)) {
            this.renderUserTurn(turn);
        } else {
            this.renderBotTurn(turn);
        }

        this.persistProgress();
    }

    renderBotTurn(turn) {
        this.setState('botSpeaking');
        this.elements.turnPrompt.textContent = `${turn.speaker} is speaking`;
        this.elements.turnHint.textContent = 'Listen to the AI line. Next becomes available when playback finishes.';
        this.updateMicStatus('Microphone off during bot turn', 'idle');
        this.speakLine(turn.english, {
            onEnd: () => {
                this.botReadyForNext = true;
                this.turnResolved = true;
                this.updateResult('Bot turn completed. Advancing to next turn...', true);
                // this.elements.nextBtn.disabled = false;
                this.setState('turnResult');
                setTimeout(() => this.advanceTurn(), 800);
            },
            onUnavailable: () => {
                this.botReadyForNext = true;
                this.turnResolved = true;
                this.updateResult('TTS is unavailable. Read the line and continue manually.', false);
                // this.elements.nextBtn.disabled = false;
                this.setState('turnResult');
            }
        });
    }

    renderUserTurn() {
        this.setState('userListening');
        this.elements.turnPrompt.textContent = 'Your turn';
        this.elements.turnHint.textContent = 'Speak the English line. Listening stops after 1.5 seconds of silence.';
        this.updateResult('Speak now, or use the typed fallback if needed.', false);
        this.updateMicStatus('Preparing microphone', 'idle');
        this.startUserTurn();
    }

    startUserTurn() {
        if (!this.recognitionSupported || this.permissionDenied) {
            this.updateMicStatus('Microphone unavailable. Use manual input.', 'idle');
            this.elements.retryBtn.disabled = false;
            return;
        }

        this.finalTranscript = '';
        this.currentTranscript = '';
        this.shouldEvaluateOnRecognitionEnd = true;
        this.elements.retryBtn.disabled = true;
        // this.elements.nextBtn.disabled = true;

        try {
            this.recognition.start();
        } catch (error) {
            this.updateMicStatus('Microphone busy. You can retry or type.', 'idle');
            this.elements.retryBtn.disabled = false;
        }
    }

    startSilenceMonitor() {
        this.stopSilenceMonitor();
        this.silenceTimer = window.setInterval(() => {
            if (!this.recognitionActive) {
                return;
            }
            const elapsed = Date.now() - this.lastSpeechAt;
            if (this.currentTranscript && elapsed >= SILENCE_TIMEOUT_MS) {
                this.stopRecognition();
            }
        }, 250);
    }

    stopSilenceMonitor() {
        if (this.silenceTimer) {
            window.clearInterval(this.silenceTimer);
            this.silenceTimer = null;
        }
    }

    stopRecognition() {
        if (!this.recognition || !this.recognitionActive) {
            return;
        }
        this.stopSilenceMonitor();
        this.recognition.stop();
    }

    cancelRecognition() {
        if (!this.recognition) {
            return;
        }

        this.shouldEvaluateOnRecognitionEnd = false;
        this.stopSilenceMonitor();

        if (!this.recognitionActive) {
            return;
        }

        this.recognition.stop();
    }

    finishUserListening() {
        if (!this.isUserTurn(this.getCurrentTurn()) || this.turnResolved) {
            return;
        }

        this.setState('userProcessing');
        this.updateMicStatus('Processing your answer', 'processing');

        setTimeout(() => {
            const transcript = (this.finalTranscript || this.currentTranscript || '').trim();

            if (!transcript) {
                this.updateResult('We did not catch that. Try again or type your answer.', false);
                this.elements.retryBtn.disabled = false;
                this.setState('turnResult');
                this.updateMicStatus('Ready to retry', 'idle');
                return;
            }

            this.updateTranscript(transcript, true);
            this.evaluateUserAttempt(transcript);
        }, 300);
    }

    submitManualInput() {
        if (!this.isUserTurn(this.getCurrentTurn())) {
            return;
        }
        const value = this.elements.manualInput.value.trim();
        if (!value) {
            this.updateResult('Type an answer before submitting.', false);
            return;
        }
        this.stopRecognition();
        this.updateTranscript(value, true);
        this.evaluateUserAttempt(value);
    }

    evaluateUserAttempt(transcript) {
        const turn = this.getCurrentTurn();
        const expected = turn?.english || '';
        const attempts = this.incrementAttemptsForTurn();
        const similarity = this.calculateSimilarity(transcript, expected);
        const normalizedTranscript = this.normalizeText(transcript);
        const tooShort = normalizedTranscript.split(' ').filter(Boolean).length < MIN_WORD_COUNT;
        const historyKey = String(this.currentTurnIndex);

        if (!this.history[historyKey]) {
            this.history[historyKey] = [];
        }
        this.history[historyKey].push({ transcript, similarity, attempts, createdAt: new Date().toISOString() });
        this.elements.attemptInfo.textContent = `Attempts: ${attempts}`;

        if (tooShort) {
            this.turnResolved = false;
            this.updateResult('Your answer is too short. Please say more of the sentence.', false);
            this.elements.retryBtn.disabled = false;
            this.setState('turnResult');
            this.persistProgress();
            return;
        }

        if (similarity >= ACCEPT_THRESHOLD) {
            this.turnResolved = true;
            this.score += 1;
            this.streak += 1;
            this.markTurnCompleted();
            this.updateResult(`Accepted. Similarity ${(similarity * 100).toFixed(0)}%. You earned 1 point.`, true);
            // this.elements.nextBtn.disabled = false;
            this.elements.retryBtn.disabled = true;
            this.setState('turnResult');
            this.persistProgress();
            setTimeout(() => this.advanceTurn(), 1500);
            return;
        }

        if (attempts >= MAX_ATTEMPTS || similarity < RETRY_THRESHOLD) {
            this.turnResolved = true;
            this.streak = 0;
            this.markTurnCompleted();
            this.elements.expectedWrap.classList.remove('hidden');
            this.elements.expectedOutput.textContent = expected;
            this.updateResult(`Skipped after ${attempts} attempt${attempts === 1 ? '' : 's'}. Similarity ${(similarity * 100).toFixed(0)}%.`, false);
            // this.elements.nextBtn.disabled = false;
            this.elements.retryBtn.disabled = true;
            this.setState('turnResult');
            this.persistProgress();
            setTimeout(() => this.advanceTurn(), 2000);
            return;
        }

        this.turnResolved = false;
        this.streak = 0;
        this.updateResult(`Retry needed. Similarity ${(similarity * 100).toFixed(0)}%. Listen again and try once more.`, false);
        this.elements.retryBtn.disabled = false;
        this.setState('turnResult');
        this.persistProgress();
    }

    markTurnCompleted() {
        if (!this.completedTurns.includes(this.currentTurnIndex)) {
            this.completedTurns.push(this.currentTurnIndex);
        }
        this.updateStats(this.getCurrentTurn());
    }

    getAttemptsForTurn() {
        return this.attemptsPerTurn[this.currentTurnIndex] || 0;
    }

    incrementAttemptsForTurn() {
        const nextValue = this.getAttemptsForTurn() + 1;
        this.attemptsPerTurn[this.currentTurnIndex] = nextValue;
        return nextValue;
    }

    updateStats(turn) {
        this.elements.scoreLabel.textContent = `Score: ${this.score}`;
        this.elements.currentSpeakerStat.textContent = turn?.speaker || '-';
        this.elements.completedTurnsStat.textContent = String(this.completedTurns.length);
        this.elements.streakStat.textContent = String(this.streak);
    }

    handleReplay() {
        const turn = this.getCurrentTurn();
        if (!turn?.english) {
            return;
        }

        if (this.isUserTurn(turn)) {
            this.cancelRecognition();
            this.speakLine(turn.english, {
                onEnd: () => {
                    if (!this.turnResolved) {
                        this.startUserTurn();
                    }
                },
                onUnavailable: () => {
                    this.updateResult('Replay is unavailable in this browser. Please read the line and answer.', false);
                }
            });
            return;
        }

        // this.elements.nextBtn.disabled = true;
        this.botReadyForNext = false;
        this.renderBotTurn(turn);
    }

    handleRetry() {
        if (!this.isUserTurn(this.getCurrentTurn())) {
            return;
        }
        this.turnResolved = false;
        this.finalTranscript = '';
        this.currentTranscript = '';
        this.updateTranscript('Your speech will appear here.', false, true);
        this.updateResult('Retry the line now.', false);
        this.elements.expectedWrap.classList.add('hidden');
        this.elements.expectedOutput.textContent = '';
        this.renderUserTurn();
    }

    advanceTurn() {
        const turn = this.getCurrentTurn();
        if (!turn) {
            return;
        }

        if (!this.isUserTurn(turn) && !this.botReadyForNext) {
            return;
        }

        if (this.isUserTurn(turn) && !this.turnResolved) {
            return;
        }

        this.cancelRecognition();
        window.speechSynthesis.cancel();
        this.currentTurnIndex += 1;
        this.persistProgress();
        this.renderTurn();
    }

    renderCompletedState() {
        this.setState('completed');
        this.updateMicStatus('Session completed', 'idle');
        this.elements.turnCounter.textContent = `Turn ${this.dialogue.length} / ${this.dialogue.length}`;
        this.elements.progressFill.style.width = '100%';
        this.elements.speakerBadge.textContent = 'Completed';
        this.elements.turnTime.textContent = '--:--';
        this.elements.englishLine.textContent = 'Conversation completed';
        this.elements.translationLine.textContent = 'Great job finishing the roleplay session.';
        this.elements.turnPrompt.textContent = 'Session finished';
        this.elements.turnHint.textContent = 'You can restart the session at any time.';
        this.updateResult(`Final score: ${this.score} / ${this.dialogue.filter((turn) => this.isUserTurn(turn)).length}`, true);
        this.updateTranscript('All turns completed.', false);
        // this.elements.nextBtn.disabled = true;
        this.elements.retryBtn.disabled = true;
        this.elements.expectedWrap.classList.add('hidden');
        this.elements.currentSpeakerStat.textContent = '-';
        this.persistProgress();
    }

    setState(nextState) {
        this.state = nextState;
        this.elements.stateLabel.textContent = nextState;
    }

    speakLine(text, { onEnd, onUnavailable }) {
        if (!('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
            if (typeof onUnavailable === 'function') {
                onUnavailable();
            }
            return;
        }

        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'en-US';
        utterance.rate = 0.96;
        utterance.onend = () => {
            if (typeof onEnd === 'function') {
                onEnd();
            }
        };
        utterance.onerror = () => {
            if (typeof onUnavailable === 'function') {
                onUnavailable();
            }
        };
        window.speechSynthesis.speak(utterance);
    }

    updateMicStatus(text, tone) {
        this.elements.micStatusText.textContent = text;
        this.elements.micStatusDot.classList.remove('listening', 'processing');
        if (tone === 'listening' || tone === 'processing') {
            this.elements.micStatusDot.classList.add(tone);
        }
    }

    updateTranscript(text, hasValue, forceEmptyStyle = false) {
        this.elements.transcriptOutput.textContent = text;
        this.elements.transcriptOutput.classList.toggle('empty', forceEmptyStyle || !hasValue);
    }

    updateResult(text, success, forceEmptyStyle = false) {
        this.elements.resultOutput.textContent = text;
        this.elements.resultOutput.classList.toggle('empty', forceEmptyStyle);
        this.elements.resultOutput.style.borderColor = success ? 'rgba(34, 197, 94, 0.35)' : 'rgba(148, 163, 184, 0.16)';
    }

    normalizeText(text) {
        return text
            .toLowerCase()
            .replace(/[^a-z0-9\s']/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    calculateSimilarity(actual, expected) {
        const normalizedActual = this.normalizeText(actual);
        const normalizedExpected = this.normalizeText(expected);

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
        const editRatio = 1 - (this.levenshtein(normalizedActual, normalizedExpected) / Math.max(normalizedActual.length, normalizedExpected.length, 1));

        return (jaccard * 0.45) + (editRatio * 0.55);
    }

    levenshtein(source, target) {
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
}

document.addEventListener('DOMContentLoaded', () => {
    new RoleplayConversationPlayer();
});
