import { USER_SPEAKER, MAX_ATTEMPTS, ACCEPT_THRESHOLD, RETRY_THRESHOLD, MIN_WORD_COUNT } from './constants.js';
import { calculateSimilarity, normalizeText } from './similarity.js';

export class ConversationManager {
    constructor(ui, progress, speechRecognition, audioCacheManager) {
        this.ui = ui;
        this.progress = progress;
        this.speechRecognition = speechRecognition;
        this.audioCacheManager = audioCacheManager;
        
        this.conversation = null;
        this.dialogue = [];
        this.state = 'idle';
        this.botReadyForNext = false;
        this.turnResolved = false;
        this.isFirstRender = true;
    }

    async loadConversation(conversationFile) {
        this.setState('loadingTurn');
        this.ui.elements.fileNameStat.textContent = conversationFile;

        try {
            const response = await fetch(`./assets/${encodeURIComponent(conversationFile)}`);
            if (!response.ok) {
                throw new Error(`Unable to load conversation file: ${conversationFile}`);
            }

            this.conversation = await response.json();
            this.dialogue = Array.isArray(this.conversation.dialogue) ? this.conversation.dialogue : [];
            
            await this.audioCacheManager.initialize(conversationFile);
            const cacheStats = this.audioCacheManager.getStats();
            console.log('[AudioCache] Stats:', cacheStats);
            
            this.progress.restore();
            this.ui.renderConversationMeta(this.conversation);
            this.renderTurn();
        } catch (error) {
            this.ui.elements.title.textContent = 'Failed to load conversation';
            this.ui.elements.meta.textContent = error.message;
            this.ui.updateResult(error.message, false);
            this.setState('idle');
        }
    }

    getCurrentTurn() {
        return this.dialogue[this.progress.currentTurnIndex] || null;
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
        this.speechRecognition.reset();
        this.ui.clearManualInput();
        this.ui.hideExpectedLine();
        this.ui.elements.retryBtn.disabled = true;
        this.ui.updateTranscript('Your speech will appear here.', false, true);
        this.ui.updateResult('Waiting for this turn to start.', false, true);
        this.ui.updateStats(turn, this.progress.score, this.progress.completedTurns.length, this.progress.streak);

        const totalTurns = this.dialogue.length;
        this.ui.updateProgress(this.progress.currentTurnIndex, totalTurns);
        this.ui.elements.attemptInfo.textContent = `Attempts: ${this.progress.getAttemptsForTurn(this.progress.currentTurnIndex)}`;

        this.ui.renderConversationHistory(this.dialogue, this.progress.currentTurnIndex, (turnIndex) => this.handleHistoryReplay(turnIndex));

        if (this.isUserTurn(turn)) {
            this.renderUserTurn(turn);
        } else {
            this.renderBotTurn(turn);
        }

        this.progress.persist();
    }

    renderBotTurn(turn) {
        console.log('[Bot Turn] Starting bot turn:', turn.speaker, turn.english);
        this.setState('botSpeaking');
        this.ui.elements.turnPrompt.textContent = `${turn.speaker} is speaking`;
        this.ui.updateMicStatus('Microphone off during bot turn', 'idle');
        
        if (this.isFirstRender) {
            this.isFirstRender = false;
            this.ui.elements.turnHint.textContent = 'Click the Replay button below to hear the audio.';
            this.ui.updateResult('Click the Replay button to start the audio (browser autoplay blocked on first load).', false);
            this.botReadyForNext = false;
            this.turnResolved = false;
            this.ui.elements.retryBtn.disabled = false;
            this.ui.elements.retryBtn.textContent = 'continue playing';
            this.ui.elements.retryBtn.onclick = () => {
                this.ui.elements.retryBtn.textContent = 'Retry';
                this.ui.elements.retryBtn.onclick = null;
                this.playBotAudio(turn);
            };
            return;
        }
        
        this.playBotAudio(turn);
    }
    
    playBotAudio(turn) {
        this.ui.elements.turnHint.textContent = 'Listen to the AI line. Next becomes available when playback finishes.';
        this.audioCacheManager.playAudio(turn.english, {
            onEnd: () => {
                console.log('[Bot Turn] Speech ended, advancing to next turn');
                this.botReadyForNext = true;
                this.turnResolved = true;
                this.ui.updateResult('Bot turn completed. Advancing to next turn...', true);
                this.setState('turnResult');
                setTimeout(() => this.advanceTurn(), 800);
            },
            onUnavailable: () => {
                console.log('[Bot Turn] Audio unavailable');
                this.botReadyForNext = true;
                this.turnResolved = true;
                this.ui.updateResult('Audio is unavailable. Read the line and continue manually.', false);
                this.setState('turnResult');
            },
            useTTSFallback: true
        });
    }

    renderUserTurn() {
        this.setState('userListening');
        this.ui.elements.turnPrompt.textContent = 'Your turn';
        this.ui.elements.turnHint.textContent = 'Please speak, it will auto submit when you stop talking. Listening stops after 1.5 seconds of silence.';
        this.ui.updateResult('Speak now, or use the typed fallback if needed.', false);
        this.ui.updateMicStatus('Preparing microphone', 'idle');
        this.startUserTurn();
    }

    startUserTurn() {
        if (!this.speechRecognition.isSupported() || this.speechRecognition.isPermissionDenied()) {
            this.ui.updateMicStatus('Microphone unavailable. Use manual input.', 'idle');
            this.ui.elements.retryBtn.disabled = false;
            return;
        }

        this.ui.elements.retryBtn.disabled = true;

        const started = this.speechRecognition.start();
        if (!started) {
            this.ui.updateMicStatus('Microphone busy. You can retry or type.', 'idle');
            this.ui.elements.retryBtn.disabled = false;
        }
    }

    finishUserListening(transcript) {
        if (!this.isUserTurn(this.getCurrentTurn()) || this.turnResolved) {
            return;
        }

        this.setState('userProcessing');
        this.ui.updateMicStatus('Processing your answer', 'processing');

        setTimeout(() => {
            const finalTranscript = transcript.trim();

            if (!finalTranscript) {
                this.ui.updateResult('We did not catch that. Try again or type your answer.', false);
                this.ui.elements.retryBtn.disabled = false;
                this.setState('turnResult');
                this.ui.updateMicStatus('Click to retry talking', 'idle');
                return;
            }

            this.ui.updateTranscript(finalTranscript, true);
            this.evaluateUserAttempt(finalTranscript);
        }, 300);
    }

    submitManualInput() {
        if (!this.isUserTurn(this.getCurrentTurn())) {
            return;
        }
        const value = this.ui.getManualInputValue();
        if (!value) {
            this.ui.updateResult('Type an answer before submitting.', false);
            return;
        }
        this.speechRecognition.stop();
        this.ui.updateTranscript(value, true);
        this.evaluateUserAttempt(value);
    }

    evaluateUserAttempt(transcript) {
        console.log({transcript})
        const turn = this.getCurrentTurn();
        const expected = turn?.english || '';
        const attempts = this.progress.incrementAttemptsForTurn(this.progress.currentTurnIndex);
        const similarity = calculateSimilarity(transcript, expected);
        const normalizedTranscript = normalizeText(transcript);
        // const tooShort = normalizedTranscript.split(' ').filter(Boolean).length < MIN_WORD_COUNT;

        this.progress.addToHistory(this.progress.currentTurnIndex, transcript, similarity, attempts);
        this.ui.elements.attemptInfo.textContent = `Attempts: ${attempts}`;

        // if (tooShort) {
        //     this.turnResolved = false;
        //     this.ui.updateResult('Your answer is too short. Please say more of the sentence.', false);
        //     this.ui.elements.retryBtn.disabled = false;
        //     this.setState('turnResult');
        //     this.progress.persist();
        //     return;
        // }

        if (similarity >= ACCEPT_THRESHOLD) {
            this.turnResolved = true;
            this.progress.addSimilarityScore(similarity);
            this.progress.incrementStreak();
            this.progress.markTurnCompleted(this.progress.currentTurnIndex);
            this.ui.updateResult(`Accepted. Similarity ${(similarity * 100).toFixed(0)}%. Average score: ${this.progress.score}%`, true);
            this.ui.elements.retryBtn.disabled = true;
            this.setState('turnResult');
            this.progress.persist();
            setTimeout(() => this.advanceTurn(), 1500);
            return;
        }

        this.turnResolved = false;
        this.progress.resetStreak();
        this.ui.updateResult(`Retry needed. Similarity ${(similarity * 100).toFixed(0)}%. Listen again and try once more.`, false);
        this.ui.elements.retryBtn.disabled = false;
        
        // Play wrong sound
        const wrongSound = new Audio('assets/wav/wrong.mp3');
        wrongSound.play().catch(err => console.error('Failed to play wrong sound:', err));
        
        // Add shake and red color to retry button
        this.ui.elements.retryBtn.classList.add('retry-error');
        
        this.setState('turnResult');
        this.progress.persist();
    }

    handleRetry() {
        if (!this.isUserTurn(this.getCurrentTurn())) {
            return;
        }
        this.turnResolved = false;
        
        // Remove error styling from retry button
        this.ui.elements.retryBtn.classList.remove('retry-error');
        
        this.speechRecognition.reset();
        this.ui.updateTranscript('Your speech will appear here.', false, true);
        this.ui.updateResult('Retry the line now.', false);
        this.ui.hideExpectedLine();
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

        this.speechRecognition.cancel();
        this.audioCacheManager.stop();
        this.progress.advanceTurn();
        this.progress.persist();
        this.renderTurn();
    }

    handleHistoryReplay(turnIndex) {
        const turn = this.dialogue[turnIndex];
        if (!turn?.english) {
            return;
        }

        const isCurrent = turnIndex === this.progress.currentTurnIndex;

        if (isCurrent && this.isUserTurn(turn)) {
            this.speechRecognition.cancel();
            this.audioCacheManager.playAudio(turn.english, {
                onEnd: () => {
                    if (!this.turnResolved) {
                        this.startUserTurn();
                    }
                },
                onUnavailable: () => {
                    this.ui.updateResult('Replay is unavailable. Please read the line and answer.', false);
                },
                useTTSFallback: true
            });
            return;
        }

        this.audioCacheManager.playAudio(turn.english, {
            onEnd: () => {},
            onUnavailable: () => {
                this.ui.updateResult('Replay is unavailable.', false);
            },
            useTTSFallback: true
        });
    }

    renderCompletedState() {
        this.setState('completed');
        this.ui.updateMicStatus('', 'idle'); // session is completed
        this.ui.elements.turnCounter.textContent = `Turn ${this.dialogue.length} / ${this.dialogue.length}`;
        this.ui.elements.progressFill.style.height = '100%';
        this.ui.elements.turnPrompt.textContent = 'Session finished';
        this.ui.elements.turnHint.textContent = 'You can restart the session at any time. All conversation history is shown above.';
        
        const userTurns = this.dialogue.filter((turn) => this.isUserTurn(turn)).length;
        const averageScore = this.progress.getAverageScore();
        this.ui.updateResult(`Final average score: ${averageScore.toFixed(1)}%`, true);
        this.ui.updateTranscript('All turns completed.', false);
        this.ui.elements.retryBtn.disabled = true;
        this.ui.hideExpectedLine();
        this.ui.elements.currentSpeakerStat.textContent = '-';
        
        this.ui.renderCompletedHistory(this.dialogue, (turnIndex) => this.handleHistoryReplay(turnIndex));
        
        this.progress.persist();
        
        this.ui.showCelebrationPopup({
            averageScore: averageScore,
            totalTurns: userTurns,
            completedTurns: this.progress.completedTurns.length,
            streak: this.progress.streak
        });
    }

    restartSession() {
        this.speechRecognition.stop();
        this.audioCacheManager.stop();
        this.progress.reset();
        this.isFirstRender = false;
        this.renderTurn();
    }

    setState(nextState) {
        this.state = nextState;
        this.ui.setState(nextState);
    }
}
