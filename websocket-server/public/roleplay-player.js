import { DEFAULT_CONVERSATION_FILE } from './modules/constants.js';
import { UIManager } from './modules/ui-manager.js';
import { ProgressManager } from './modules/progress-manager.js';
import { SpeechRecognitionManager } from './modules/speech-recognition.js';
import { ConversationManager } from './modules/conversation-manager.js';
import { GameSelector } from './modules/game-selector.js';

class RoleplayConversationPlayer {
    constructor() {
        this.currentFile = this.getConversationFile();
        this.audioCacheManager = new AudioCacheManager();
        
        this.ui = new UIManager();
        this.progress = new ProgressManager(`roleplay-progress:${this.currentFile}`);
        this.gameSelector = new GameSelector();
        
        this.speechRecognition = new SpeechRecognitionManager({
            onUnavailable: (message) => {
                this.ui.updateMicStatus(message, 'idle');
            },
            onStart: () => {
                this.ui.updateMicStatus('Waiting for your answer', 'listening');
            },
            onResult: (transcript) => {
                this.ui.updateTranscript(transcript, true);
            },
            onError: (errorType, message) => {
                if (errorType === 'permission-denied') {
                    this.ui.updateMicStatus(message, 'idle');
                    this.ui.updateResult('Microphone permission denied. You can type your answer instead.', false);
                } else if (errorType === 'no-speech') {
                    this.ui.updateMicStatus('We did not catch that. Try again.', 'idle');
                    this.ui.updateResult(message, false);
                    this.ui.elements.retryBtn.disabled = false;
                } else {
                    this.ui.updateMicStatus(message, 'idle');
                    this.ui.updateResult(message, false);
                }
            },
            onEnd: (transcript) => {
                this.conversationManager.finishUserListening(transcript);
            }
        });
        
        this.conversationManager = new ConversationManager(
            this.ui,
            this.progress,
            this.speechRecognition,
            this.audioCacheManager
        );
        
        this.bindEvents();
        this.loadConversation();
    }

    getConversationFile() {
        const params = new URLSearchParams(window.location.search);
        return params.get('file') || DEFAULT_CONVERSATION_FILE;
    }

    async loadConversation() {
        await this.conversationManager.loadConversation(this.currentFile);
    }

    bindEvents() {
        this.ui.elements.retryBtn.addEventListener('click', () => {
            this.conversationManager.handleRetry();
        });
        
        this.ui.elements.submitManualBtn.addEventListener('click', () => {
            this.conversationManager.submitManualInput();
        });
        
        this.ui.elements.restartBtn.addEventListener('click', () => {
            this.conversationManager.restartSession();
        });
        
        this.ui.elements.sidebarToggle.addEventListener('click', () => {
            this.ui.toggleSidebar();
        });
        
        document.addEventListener('celebration-restart', () => {
            this.conversationManager.restartSession();
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new RoleplayConversationPlayer();
});
