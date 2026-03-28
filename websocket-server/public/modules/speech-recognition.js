import { SILENCE_TIMEOUT_MS } from './constants.js';

export class SpeechRecognitionManager {
    constructor(callbacks) {
        this.callbacks = callbacks;
        this.recognition = null;
        this.recognitionSupported = false;
        this.recognitionActive = false;
        this.permissionDenied = false;
        this.lastSpeechAt = 0;
        this.silenceTimer = null;
        this.currentTranscript = '';
        this.finalTranscript = '';
        this.shouldEvaluateOnRecognitionEnd = false;
        
        this.initSpeechRecognition();
    }

    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            this.recognitionSupported = false;
            this.callbacks.onUnavailable?.('Speech recognition unavailable');
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
            this.callbacks.onStart?.();
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
            this.callbacks.onResult?.(this.currentTranscript || 'Listening...');
        };

        this.recognition.onerror = (event) => {
            this.stopSilenceMonitor();
            this.recognitionActive = false;

            if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                this.permissionDenied = true;
                this.callbacks.onError?.('permission-denied', 'Microphone permission denied. Use manual input.');
                return;
            }

            if (event.error === 'no-speech') {
                this.callbacks.onError?.('no-speech', 'We did not catch that. Try speaking again or type your answer.');
                return;
            }

            this.callbacks.onError?.(event.error, `Recognition error: ${event.error}`);
        };

        this.recognition.onend = () => {
            this.stopSilenceMonitor();
            const shouldEvaluate = this.shouldEvaluateOnRecognitionEnd;
            this.recognitionActive = false;
            this.shouldEvaluateOnRecognitionEnd = false;
            if (!shouldEvaluate) {
                return;
            }
            this.callbacks.onEnd?.(this.finalTranscript || this.currentTranscript || '');
        };
    }

    start() {
        if (!this.recognitionSupported || this.permissionDenied) {
            return false;
        }

        this.finalTranscript = '';
        this.currentTranscript = '';
        this.shouldEvaluateOnRecognitionEnd = true;

        try {
            this.recognition.start();
            return true;
        } catch (error) {
            this.callbacks.onError?.('busy', 'Microphone busy. You can retry or type.');
            return false;
        }
    }

    stop() {
        if (!this.recognition || !this.recognitionActive) {
            return;
        }
        this.stopSilenceMonitor();
        this.recognition.stop();
    }

    cancel() {
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

    startSilenceMonitor() {
        this.stopSilenceMonitor();
        this.silenceTimer = window.setInterval(() => {
            if (!this.recognitionActive) {
                return;
            }
            const elapsed = Date.now() - this.lastSpeechAt;
            if (this.currentTranscript && elapsed >= SILENCE_TIMEOUT_MS) {
                this.stop();
            }
        }, 250);
    }

    stopSilenceMonitor() {
        if (this.silenceTimer) {
            window.clearInterval(this.silenceTimer);
            this.silenceTimer = null;
        }
    }

    reset() {
        this.finalTranscript = '';
        this.currentTranscript = '';
    }

    isSupported() {
        return this.recognitionSupported;
    }

    isPermissionDenied() {
        return this.permissionDenied;
    }
}
