import { normalizeText, calculateSimilarity } from './text-utils.js';

export class PracticeModeManager {
    constructor(mp3Player) {
        this.player = mp3Player;
    }

    initSpeechRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        
        if (!SpeechRecognition) {
            console.error('Speech Recognition API not supported in this browser');
            this.player.micToggleBtn.disabled = true;
            this.player.micToggleBtn.title = 'Speech recognition not supported';
            return;
        }
        
        this.player.recognition = new SpeechRecognition();
        this.player.recognition.continuous = true;
        this.player.recognition.interimResults = true;
        this.player.recognition.maxAlternatives = 1;
        this.player.recognition.lang = this.player.recognitionLanguageSelector ? this.player.recognitionLanguageSelector.value : 'en-US';
        
        this.player.recognition.onstart = () => {
            console.log('Speech recognition started');
            this.player.isRecognizing = true;
            this.updatePracticeStatus('Listening...', 'listening');
        };
        
        this.player.recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';
            
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript + ' ';
                } else {
                    interimTranscript += transcript;
                }
            }
            
            if (finalTranscript) {
                this.player.recognitionText += finalTranscript;
                this.player.pendingSpeechText += finalTranscript;
                this.player.lastSpeechTime = Date.now();
                this.player.recognitionTextEl.textContent = this.player.recognitionText || 'Listening...';
            } else if (interimTranscript) {
                this.player.lastSpeechTime = Date.now();
                this.player.recognitionTextEl.textContent = (this.player.recognitionText + interimTranscript) || 'Listening...';
            }
        };
        
        this.player.recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            
            if (event.error === 'no-speech') {
                this.updatePracticeStatus('No speech detected', 'warning');
            } else if (event.error === 'network') {
                this.updatePracticeStatus('Network error', 'error');
            } else if (event.error === 'not-allowed') {
                this.updatePracticeStatus('Microphone access denied', 'error');
                this.stopPracticeMode();
            } else {
                this.updatePracticeStatus('Error: ' + event.error, 'error');
            }
        };
        
        this.player.recognition.onend = () => {
            console.log('Speech recognition ended');
            this.player.isRecognizing = false;
            
            if (this.player.practiceMode) {
                this.player.recognitionRestartTimeout = setTimeout(() => {
                    if (this.player.practiceMode) {
                        try {
                            this.player.recognition.start();
                            this.updatePracticeStatus('Restarting...', 'listening');
                        } catch (error) {
                            console.error('Error restarting recognition:', error);
                        }
                    }
                }, 300);
            } else {
                this.updatePracticeStatus('Stopped', 'ready');
            }
        };
    }

    updateMicButtonState() {
        if (this.player.currentIndex === -1) {
            this.player.micToggleBtn.disabled = true;
            this.player.micToggleBtn.title = 'Load a track to enable practice mode';
        } else {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (SpeechRecognition) {
                this.player.micToggleBtn.disabled = false;
                this.player.micToggleBtn.title = this.player.practiceMode ? 'Practice Mode (On)' : 'Practice Mode (Off)';
            }
        }
    }

    togglePracticeMode() {
        this.player.practiceMode = !this.player.practiceMode;
        
        if (this.player.practiceMode) {
            this.startPracticeMode();
        } else {
            this.stopPracticeMode();
        }
    }
    
    startPracticeMode() {
        this.player.practicePanel.style.display = 'block';
        this.player.micToggleBtn.classList.add('active');
        this.player.micToggleBtn.title = 'Practice Mode (On)';
        this.player.micToggleBtn.querySelector('.material-icons').textContent = 'mic';
        
        this.player.recognitionText = '';
        this.player.pendingSpeechText = '';
        this.player.lastSpeechTime = null;
        this.player.recognitionTextEl.textContent = 'Starting microphone...';
        this.updatePracticeStatus('Starting...', 'listening');
        
        if (this.player.subtitles.length > 0) {
            this.player.currentPracticeLineIndex = 0;
            this.loadPracticeLine(0);
        } else {
            this.updatePracticeStatus('No subtitles loaded', 'error');
            this.player.currentPracticeLineIndex = -1;
        }
        
        this.startSilenceDetection();
        
        try {
            this.player.recognition.start();
        } catch (error) {
            console.error('Error starting recognition:', error);
            this.updatePracticeStatus('Failed to start', 'error');
        }
    }
    
    stopPracticeMode() {
        this.player.practiceMode = false;
        this.player.practicePanel.style.display = 'none';
        this.player.micToggleBtn.classList.remove('active');
        this.player.micToggleBtn.title = 'Practice Mode (Off)';
        this.player.micToggleBtn.querySelector('.material-icons').textContent = 'mic_off';
        
        if (this.player.recognitionRestartTimeout) {
            clearTimeout(this.player.recognitionRestartTimeout);
            this.player.recognitionRestartTimeout = null;
        }
        
        if (this.player.silenceCheckInterval) {
            clearInterval(this.player.silenceCheckInterval);
            this.player.silenceCheckInterval = null;
        }
        
        if (this.player.isRecognizing) {
            try {
                this.player.recognition.stop();
            } catch (error) {
                console.error('Error stopping recognition:', error);
            }
        }
        
        this.player.currentPracticeLineIndex = -1;
        this.player.lastSpeechTime = null;
        this.player.pendingSpeechText = '';
        
        this.updatePracticeStatus('Ready', 'ready');
    }
    
    updatePracticeStatus(text, type) {
        this.player.practiceStatus.textContent = text;
        this.player.practiceStatus.className = 'status-badge status-' + type;
    }
    
    clearRecognitionText() {
        this.player.recognitionText = '';
        this.player.pendingSpeechText = '';
        this.player.recognitionTextEl.textContent = this.player.practiceMode ? 'Listening...' : 'Click microphone to start...';
    }
    
    startSilenceDetection() {
        if (this.player.silenceCheckInterval) {
            clearInterval(this.player.silenceCheckInterval);
        }
        
        this.player.silenceCheckInterval = setInterval(() => {
            if (!this.player.practiceMode || !this.player.lastSpeechTime) {
                return;
            }
            
            const silenceDuration = Date.now() - this.player.lastSpeechTime;
            
            if (silenceDuration >= 2000 && this.player.pendingSpeechText.trim()) {
                this.compareWithCurrentLine(this.player.pendingSpeechText.trim());
                this.player.pendingSpeechText = '';
                this.player.lastSpeechTime = null;
            }
        }, 500);
    }

    loadPracticeLine(index) {
        if (index < 0 || index >= this.player.subtitles.length) {
            return;
        }
        
        const previousActive = this.player.subtitleList.querySelector('.subtitle-line-item.practice-active');
        if (previousActive) {
            previousActive.classList.remove('practice-active');
        }
        
        const practiceItem = this.player.subtitleList.querySelector(`.subtitle-line-item[data-index="${index}"]`);
        if (practiceItem) {
            practiceItem.classList.add('practice-active');
            practiceItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            const subtitleText = this.player.subtitles[index].text;
            this.updatePracticeStatus(`Practice: "${subtitleText.substring(0, 50)}${subtitleText.length > 50 ? '...' : ''}"`, 'listening');
        }
    }
    
    compareWithCurrentLine(spokenText) {
        if (this.player.subtitles.length === 0 || !spokenText || this.player.currentPracticeLineIndex === -1) {
            return;
        }
        
        const normalizedSpoken = normalizeText(spokenText);
        const currentSubtitle = this.player.subtitles[this.player.currentPracticeLineIndex];
        const normalizedSubtitle = normalizeText(currentSubtitle.text);
        
        const similarity = calculateSimilarity(normalizedSpoken, normalizedSubtitle);
        
        console.log(`Comparing spoken: "${spokenText}" with line ${this.player.currentPracticeLineIndex}: "${currentSubtitle.text}" - Similarity: ${Math.round(similarity * 100)}%`);
        
        this.player.recognitionText = '';
        this.player.recognitionTextEl.textContent = 'Listening...';
        
        if (similarity >= 0.7) {
            const practiceItem = this.player.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
            if (practiceItem) {
                practiceItem.classList.remove('practice-wrong');
            }
            
            this.player.markSubtitleAsMatched(this.player.currentPracticeLineIndex);
            this.updatePracticeStatus('Match found! (' + Math.round(similarity * 100) + '%)', 'success');
            
            setTimeout(() => {
                if (this.player.practiceMode) {
                    const nextIndex = this.player.currentPracticeLineIndex + 1;
                    if (nextIndex < this.player.subtitles.length) {
                        this.player.currentPracticeLineIndex = nextIndex;
                        this.loadPracticeLine(nextIndex);
                    } else {
                        this.updatePracticeStatus('Practice completed! 🎉', 'success');
                        this.player.currentPracticeLineIndex = -1;
                    }
                }
            }, 2000);
        } else {
            const practiceItem = this.player.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
            if (practiceItem) {
                practiceItem.classList.add('practice-wrong');
            }
            
            this.updatePracticeStatus(`Try again (${Math.round(similarity * 100)}% match)`, 'warning');
            
            setTimeout(() => {
                if (this.player.practiceMode) {
                    const currentItem = this.player.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
                    if (currentItem) {
                        currentItem.classList.remove('practice-wrong');
                    }
                    this.loadPracticeLine(this.player.currentPracticeLineIndex);
                }
            }, 2000);
        }
    }

    changeRecognitionLanguage() {
        if (!this.player.recognition) return;
        
        const newLang = this.player.recognitionLanguageSelector.value;
        const wasRecognizing = this.player.isRecognizing;
        
        if (wasRecognizing) {
            try {
                this.player.recognition.stop();
            } catch (error) {
                console.error('Error stopping recognition:', error);
            }
        }
        
        this.player.recognition.lang = newLang;
        console.log('Speech recognition language changed to:', newLang);
        
        if (wasRecognizing && this.player.practiceMode) {
            setTimeout(() => {
                try {
                    this.player.recognition.start();
                    this.updatePracticeStatus('Language changed, listening...', 'listening');
                } catch (error) {
                    console.error('Error restarting recognition:', error);
                }
            }, 300);
        }
    }
}
