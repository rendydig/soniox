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
                
                this.checkImmediateMatch();
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
        if (this.player.playlistManager.getCurrentIndex() === -1) {
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
        this.player.practicePanel.style.display = 'flex';
        this.player.micToggleBtn.classList.add('active');
        this.player.micToggleBtn.title = 'Practice Mode (On)';
        this.player.micToggleBtn.querySelector('.material-icons').textContent = 'mic';
        
        const playbackControls = document.getElementById('playbackControls');
        if (playbackControls) {
            playbackControls.classList.add('hidden');
        }
        
        const progressContainer = document.getElementById('progressContainer');
        if (progressContainer) {
            progressContainer.classList.add('hidden');
        }
        
        this.player.recognitionText = '';
        this.player.pendingSpeechText = '';
        this.player.lastSpeechTime = null;
        this.player.recognitionTextEl.textContent = 'Starting microphone...';
        this.updatePracticeStatus('Starting...', 'listening');
        
        if (this.player.subtitleManager.subtitles.length > 0) {
            const resumeIndex = this.player.subtitleManager.findFirstUnmatchedIndex();
            this.player.currentPracticeLineIndex = resumeIndex;
            this.loadPracticeLine(resumeIndex);
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
        
        const playbackControls = document.getElementById('playbackControls');
        if (playbackControls) {
            playbackControls.classList.remove('hidden');
        }
        
        const progressContainer = document.getElementById('progressContainer');
        if (progressContainer) {
            progressContainer.classList.remove('hidden');
        }
        
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
        if (index < 0 || index >= this.player.subtitleManager.subtitles.length) {
            return;
        }
        
        const previousActive = this.player.subtitleManager.subtitleList.querySelector('.subtitle-line-item.practice-active');
        if (previousActive) {
            previousActive.classList.remove('practice-active');
        }
        
        const practiceItem = this.player.subtitleManager.subtitleList.querySelector(`.subtitle-line-item[data-index="${index}"]`);
        if (practiceItem) {
            practiceItem.classList.add('practice-active');
            practiceItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            const subtitleText = this.player.subtitleManager.subtitles[index].text;
        }
    }
    
    checkImmediateMatch() {
        if (!this.player.practiceMode || this.player.currentPracticeLineIndex === -1) {
            return;
        }
        
        const currentText = this.player.recognitionText.trim();
        if (!currentText) {
            return;
        }
        
        const lang = this.player.recognition.lang || 'en-US';
        const normalizedSpoken = normalizeText(currentText, lang);
        const currentSubtitle = this.player.subtitleManager.subtitles[this.player.currentPracticeLineIndex];
        const normalizedSubtitle = normalizeText(currentSubtitle.text, lang);
        
        const similarity = calculateSimilarity(normalizedSpoken, normalizedSubtitle, lang);
        
        console.log(`Immediate check - Spoken: "${currentText}" vs Line ${this.player.currentPracticeLineIndex}: "${currentSubtitle.text}" - Similarity: ${Math.round(similarity * 100)}%`);
        
        if (similarity >= 0.7) {
            this.player.recognitionText = '';
            this.player.pendingSpeechText = '';
            this.player.lastSpeechTime = null;
            this.player.recognitionTextEl.textContent = 'Listening...';
            
            const practiceItem = this.player.subtitleManager.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
            if (practiceItem) {
                practiceItem.classList.remove('practice-wrong');
            }
            
            this.player.subtitleManager.markSubtitleAsMatched(this.player.currentPracticeLineIndex);
            this.updatePracticeStatus('Match found! (' + Math.round(similarity * 100) + '%)', 'success');
            
            const nextIndex = this.player.currentPracticeLineIndex + 1;
            if (nextIndex < this.player.subtitleManager.subtitles.length) {
                this.player.currentPracticeLineIndex = nextIndex;
                this.loadPracticeLine(nextIndex);
            } else {
                this.updatePracticeStatus('Practice completed! 🎉', 'success');
                this.player.currentPracticeLineIndex = -1;
            }
        }
    }
    
    compareWithCurrentLine(spokenText) {
        if (this.player.subtitleManager.subtitles.length === 0 || !spokenText || this.player.currentPracticeLineIndex === -1) {
            return;
        }
        
        const lang = this.player.recognition.lang || 'en-US';
        const normalizedSpoken = normalizeText(spokenText, lang);
        const currentSubtitle = this.player.subtitleManager.subtitles[this.player.currentPracticeLineIndex];
        const normalizedSubtitle = normalizeText(currentSubtitle.text, lang);
        
        let similarity = calculateSimilarity(normalizedSpoken, normalizedSubtitle, lang);
        let matchedText = currentSubtitle.text;
        let matchSource = 'original';
        
        console.log(`Comparing spoken: "${spokenText}" with line ${this.player.currentPracticeLineIndex}: "${currentSubtitle.text}" - Similarity: ${Math.round(similarity * 100)}%`);
        
        if (similarity < 0.7) {
            const similarContexts = this.player.subtitleManager.getSimilarContexts(this.player.currentPracticeLineIndex);
            
            if (similarContexts.length > 0) {
                console.log(`Checking ${similarContexts.length} similar contexts for better match...`);
                
                for (const context of similarContexts) {
                    const normalizedContext = normalizeText(context, lang);
                    const contextSimilarity = calculateSimilarity(normalizedSpoken, normalizedContext, lang);
                    
                    console.log(`  - Similar context: "${context}" - Similarity: ${Math.round(contextSimilarity * 100)}%`);
                    
                    if (contextSimilarity > similarity) {
                        similarity = contextSimilarity;
                        matchedText = context;
                        matchSource = 'similar';
                    }
                }
                
                if (matchSource === 'similar') {
                    console.log(`Better match found in similar contexts: "${matchedText}" - Similarity: ${Math.round(similarity * 100)}%`);
                }
            }
        }
        
        this.player.recognitionText = '';
        this.player.recognitionTextEl.textContent = 'Listening...';
        
        if (similarity >= 0.7) {
            const practiceItem = this.player.subtitleManager.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
            if (practiceItem) {
                practiceItem.classList.remove('practice-wrong');
            }
            
            this.player.subtitleManager.markSubtitleAsMatched(this.player.currentPracticeLineIndex);
            
            const statusMessage = matchSource === 'similar' 
                ? `Match found via similar context! (${Math.round(similarity * 100)}%)`
                : `Match found! (${Math.round(similarity * 100)}%)`;
            
            this.updatePracticeStatus(statusMessage, 'success');
            
            setTimeout(() => {
                if (this.player.practiceMode) {
                    const nextIndex = this.player.currentPracticeLineIndex + 1;
                    if (nextIndex < this.player.subtitleManager.subtitles.length) {
                        this.player.currentPracticeLineIndex = nextIndex;
                        this.loadPracticeLine(nextIndex);
                    } else {
                        this.updatePracticeStatus('Practice completed! 🎉', 'success');
                        this.player.currentPracticeLineIndex = -1;
                    }
                }
            }, 2000);
        } else {
            const practiceItem = this.player.subtitleManager.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
            if (practiceItem) {
                practiceItem.classList.add('practice-wrong');
            }
            
            this.updatePracticeStatus(`Try again (${Math.round(similarity * 100)}%)`, 'warning');
            
            setTimeout(() => {
                if (this.player.practiceMode) {
                    const currentItem = this.player.subtitleManager.subtitleList.querySelector(`.subtitle-line-item[data-index="${this.player.currentPracticeLineIndex}"]`);
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
