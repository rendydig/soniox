export class SubtitleManager {
    constructor(player) {
        this.player = player;
        this.subtitles = [];
        this.currentSubtitleIndex = -1;
        this.romajiSubtitles = [];
        this.currentRomajiIndex = -1;
        this.translationEnSubtitles = [];
        this.translationIdSubtitles = [];
        this.currentTranslationIndex = -1;
        this.currentTranslationLang = 'en';
        this.currentActiveIndex = -1;
        this.similarContexts = [];
        this.currentSrtUrl = null;
        this.matchedSubtitles = new Set();
        
        this.subtitleList = document.getElementById('subtitleList');
        this.translationLanguageSelector = document.getElementById('translationLanguage');
        this.showSubtitleCheckbox = document.getElementById('showSubtitle');
        this.showRomajiCheckbox = document.getElementById('showRomaji');
        this.showTranslationCheckbox = document.getElementById('showTranslation');
        
        this.speechSynthesis = window.speechSynthesis;
        this.currentUtterance = null;
    }

    parseSRT(srtText) {
        const subtitles = [];
        const blocks = srtText.trim().split(/\n\s*\n/);
        
        for (const block of blocks) {
            const lines = block.split('\n');
            if (lines.length < 3) continue;
            
            const timeLine = lines[1];
            const timeMatch = timeLine.match(/(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-+>\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})/);
            
            if (timeMatch) {
                const startTime = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 + parseInt(timeMatch[3]) + parseInt(timeMatch[4]) / 1000;
                const endTime = parseInt(timeMatch[5]) * 3600 + parseInt(timeMatch[6]) * 60 + parseInt(timeMatch[7]) + parseInt(timeMatch[8]) / 1000;
                const text = lines.slice(2).join('\n');
                
                subtitles.push({
                    start: startTime,
                    end: endTime,
                    text: text
                });
            }
        }
        
        return subtitles;
    }

    async loadSubtitles(srtUrl, romajiUrl, translationEnUrl, translationIdUrl) {
        if (!srtUrl) {
            this.subtitles = [];
            this.romajiSubtitles = [];
            this.translationEnSubtitles = [];
            this.translationIdSubtitles = [];
            this.similarContexts = [];
            this.currentSrtUrl = null;
            this.matchedSubtitles.clear();
            this.renderSubtitleList();
            return;
        }
        
        this.currentSrtUrl = srtUrl;
        this.loadMatchedProgress();
        
        try {
            const response = await fetch(srtUrl);
            const srtText = await response.text();
            this.subtitles = this.parseSRT(srtText);
            this.currentSubtitleIndex = -1;
            console.log(`Loaded ${this.subtitles.length} subtitles`);
        } catch (error) {
            console.error('Error loading subtitles:', error);
            this.subtitles = [];
        }
        
        await this.loadSimilarContexts(srtUrl);
        
        if (romajiUrl) {
            try {
                const response = await fetch(romajiUrl);
                const romajiText = await response.text();
                this.romajiSubtitles = this.parseSRT(romajiText);
                this.currentRomajiIndex = -1;
                console.log(`Loaded ${this.romajiSubtitles.length} romaji subtitles`);
            } catch (error) {
                console.error('Error loading romaji subtitles:', error);
                this.romajiSubtitles = [];
            }
        } else {
            this.romajiSubtitles = [];
        }
        
        let hasEnTranslation = false;
        let hasIdTranslation = false;
        
        if (translationEnUrl) {
            try {
                const response = await fetch(translationEnUrl);
                const translationText = await response.text();
                this.translationEnSubtitles = this.parseSRT(translationText);
                hasEnTranslation = true;
                console.log(`Loaded ${this.translationEnSubtitles.length} English translation subtitles`);
            } catch (error) {
                console.error('Error loading English translation subtitles:', error);
                this.translationEnSubtitles = [];
            }
        } else {
            this.translationEnSubtitles = [];
        }
        
        if (translationIdUrl) {
            try {
                const response = await fetch(translationIdUrl);
                const translationText = await response.text();
                this.translationIdSubtitles = this.parseSRT(translationText);
                hasIdTranslation = true;
                console.log(`Loaded ${this.translationIdSubtitles.length} Indonesian translation subtitles`);
            } catch (error) {
                console.error('Error loading Indonesian translation subtitles:', error);
                this.translationIdSubtitles = [];
            }
        } else {
            this.translationIdSubtitles = [];
        }
        
        if (hasEnTranslation || hasIdTranslation) {
            this.currentTranslationIndex = -1;
            
            if (hasEnTranslation && hasIdTranslation) {
                this.translationLanguageSelector.style.display = 'block';
                this.currentTranslationLang = 'en';
                this.translationLanguageSelector.value = 'en';
            } else if (hasEnTranslation) {
                this.translationLanguageSelector.style.display = 'none';
                this.currentTranslationLang = 'en';
            } else if (hasIdTranslation) {
                this.translationLanguageSelector.style.display = 'none';
                this.currentTranslationLang = 'id';
            }
        } else {
            this.translationLanguageSelector.style.display = 'none';
        }
        
        this.renderSubtitleList();
    }

    renderSubtitleList() {
        if (this.subtitles.length === 0) {
            this.subtitleList.innerHTML = '<div class="empty-subtitle-state">No subtitles available</div>';
            return;
        }
        
        const showSubtitle = this.showSubtitleCheckbox.checked;
        const showRomaji = this.showRomajiCheckbox.checked && this.romajiSubtitles.length > 0;
        const showTranslation = this.showTranslationCheckbox.checked && 
            (this.translationEnSubtitles.length > 0 || this.translationIdSubtitles.length > 0);
        
        const activeTranslationSubtitles = this.currentTranslationLang === 'en' 
            ? this.translationEnSubtitles 
            : this.translationIdSubtitles;
        
        this.subtitleList.innerHTML = this.subtitles.map((subtitle, index) => {
            const romaji = this.romajiSubtitles[index] || null;
            const translation = activeTranslationSubtitles[index] || null;
            
            let content = '';
            
            if (showSubtitle) {
                content += `<div class="subtitle-line-text" data-original-text="${this.escapeHtml(subtitle.text)}">${subtitle.text}</div>`;
            }
            
            if (showRomaji && romaji) {
                content += `<div class="subtitle-line-romaji">${romaji.text}</div>`;
            }
            
            if (showTranslation && translation) {
                content += `<div class="subtitle-line-translation">${translation.text}</div>`;
            }
            
            const similarContexts = this.getSimilarContexts(index);
            const isMatched = this.matchedSubtitles.has(index);
            const matchedClass = isMatched ? 'matched' : '';
            const checkmarkDisplay = isMatched ? 'inline-block' : 'none';
         
            return `
                <div class="subtitle-line-item ${matchedClass}" data-index="${index}" data-start="${subtitle.start}" data-end="${subtitle.end}">
                    <div class="subtitle-content">
                        ${content}
                    </div>
                    <div class="subtitle-actions">
                        <span class="subtitle-checkmark" data-index="${index}" style="display: ${checkmarkDisplay};">✓</span>
                        <button class="subtitle-tts-btn" data-index="${index}" data-text="${this.escapeHtml(subtitle.text)}" title="Play subtitle text">
                            <span class="material-icons">volume_up</span>
                        </button>
                        <button class="subtitle-repeat-btn" data-index="${index}" data-start="${subtitle.start}" data-end="${subtitle.end}" title="Repeat this subtitle">
                            <span class="material-icons">repeat</span>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        
        document.querySelectorAll('.subtitle-line-item').forEach(item => {
            item.addEventListener('click', (e) => {
                if (!e.target.closest('.subtitle-repeat-btn')) {
                    const start = parseFloat(item.dataset.start);
                    this.player.audioPlayer.currentTime = start;
                }
            });
        });
        
        document.querySelectorAll('.subtitle-repeat-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const start = parseFloat(btn.dataset.start);
                const end = parseFloat(btn.dataset.end);
                this.player.repeatLoopManager.toggleSubtitleRepeat(start, end, btn);
            });
        });
        
        document.querySelectorAll('.subtitle-tts-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const text = btn.dataset.text;
                this.speakSubtitleText(text, btn);
            });
        });
    }
    
    updateSubtitle() {
        const currentTime = this.player.audioPlayer.currentTime;
        
        if (this.subtitles.length === 0) return;
        
        if (this.player.repeatLoopManager.repeatLoopActive) {
            return;
        }
        
        let foundIndex = -1;
        for (let i = 0; i < this.subtitles.length; i++) {
            const subtitle = this.subtitles[i];
            if (currentTime >= subtitle.start && currentTime <= subtitle.end) {
                foundIndex = i;
                break;
            }
        }
        
        if (foundIndex !== this.currentActiveIndex) {
            const previousActive = this.subtitleList.querySelector('.subtitle-line-item.active');
            if (previousActive) {
                previousActive.classList.remove('active');
            }
            
            if (foundIndex !== -1) {
                const activeItem = this.subtitleList.querySelector(`.subtitle-line-item[data-index="${foundIndex}"]`);
                if (activeItem) {
                    activeItem.classList.add('active');
                    activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
            
            this.currentActiveIndex = foundIndex;
        }
    }

    markSubtitleAsMatched(index) {
        const checkmark = this.subtitleList.querySelector(`.subtitle-checkmark[data-index="${index}"]`);
        if (checkmark) {
            checkmark.style.display = 'inline-block';
            checkmark.classList.add('checkmark-appear');
            
            const subtitleItem = checkmark.closest('.subtitle-line-item');
            if (subtitleItem) {
                subtitleItem.classList.add('matched');
            }
            
            this.matchedSubtitles.add(index);
            this.saveMatchedProgress();
        }
    }

    findFirstUnmatchedIndex() {
        for (let i = 0; i < this.subtitles.length; i++) {
            const subtitleItem = this.subtitleList.querySelector(`.subtitle-line-item[data-index="${i}"]`);
            if (subtitleItem && !subtitleItem.classList.contains('matched')) {
                return i;
            }
        }
        return 0;
    }
    
    toggleSubtitleVisibility() {
        this.renderSubtitleList();
    }

    switchTranslationLanguage() {
        this.currentTranslationLang = this.translationLanguageSelector.value;
        this.currentTranslationIndex = -1;
        this.renderSubtitleList();
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    async loadSimilarContexts(srtUrl) {
        this.similarContexts = [];
        
        if (!srtUrl) return;
        
        const jsonUrl = srtUrl.replace(/\.srt$/, '.srt.json');
        
        try {
            const response = await fetch(jsonUrl);
            if (!response.ok) {
                console.log('No similar contexts file found:', jsonUrl);
                return;
            }
            
            const jsonData = await response.json();
            
            if (Array.isArray(jsonData)) {
                this.similarContexts = jsonData;
                console.log(`Loaded ${this.similarContexts.length} similar context entries`);
            } else if (jsonData && typeof jsonData === 'object') {
                this.similarContexts = [jsonData];
                console.log(`Loaded 1 similar context entry (converted from object)`);
            } else {
                console.warn('Similar contexts file has invalid format');
            }
        } catch (error) {
            console.log('Could not load similar contexts:', error.message);
        }
    }
    
    getSimilarContexts(index) {
        if (this.similarContexts.length === 0) {
            return [];
        }
        
        const srtIndex = index + 1;
        
        const entry = this.similarContexts.find(item => item.index === srtIndex);
        if (entry && Array.isArray(entry.similarContexts)) {
            return entry.similarContexts;
        }
        
        return [];
    }
    
    getStorageKey() {
        if (!this.currentSrtUrl) return null;
        const key = `subtitle_progress_${this.currentSrtUrl}`;
        console.log('[Storage] Generated key:', key);
        return key;
    }
    
    saveMatchedProgress() {
        const key = this.getStorageKey();
        if (!key) {
            console.log('[Storage] No key available for saving progress');
            return;
        }
        
        try {
            const progressData = {
                matchedIndices: Array.from(this.matchedSubtitles),
                lastUpdated: new Date().toISOString()
            };
            localStorage.setItem(key, JSON.stringify(progressData));
            console.log(`[Storage] Saved progress: ${this.matchedSubtitles.size} matched subtitles`, Array.from(this.matchedSubtitles));
        } catch (error) {
            console.error('[Storage] Error saving progress to localStorage:', error);
        }
    }
    
    loadMatchedProgress() {
        const key = this.getStorageKey();
        if (!key) {
            console.log('[Storage] No key available for loading progress');
            return;
        }
        
        try {
            const stored = localStorage.getItem(key);
            console.log('[Storage] Retrieved from localStorage:', stored);
            if (stored) {
                const progressData = JSON.parse(stored);
                this.matchedSubtitles = new Set(progressData.matchedIndices || []);
                console.log(`[Storage] Loaded progress: ${this.matchedSubtitles.size} matched subtitles`, Array.from(this.matchedSubtitles));
            } else {
                console.log('[Storage] No stored progress found');
                this.matchedSubtitles.clear();
            }
        } catch (error) {
            console.error('[Storage] Error loading progress from localStorage:', error);
            this.matchedSubtitles.clear();
        }
    }
    
    clearMatchedProgress() {
        const key = this.getStorageKey();
        if (!key) return;
        
        try {
            localStorage.removeItem(key);
            this.matchedSubtitles.clear();
            this.renderSubtitleList();
            console.log('Cleared subtitle progress');
        } catch (error) {
            console.error('Error clearing progress from localStorage:', error);
        }
    }
    
    speakSubtitleText(text, button) {
        if (!this.speechSynthesis) {
            console.error('Speech Synthesis API not supported');
            return;
        }
        
        if (this.currentUtterance && this.speechSynthesis.speaking) {
            this.speechSynthesis.cancel();
            button.classList.remove('speaking');
            button.querySelector('.material-icons').textContent = 'volume_up';
            if (this.currentUtterance.text === text) {
                this.currentUtterance = null;
                return;
            }
        }
        
        const utterance = new SpeechSynthesisUtterance(text);
        
        const recognitionLang = this.player.recognitionLanguageSelector ? 
            this.player.recognitionLanguageSelector.value : 'en-US';
        utterance.lang = recognitionLang;
        
        utterance.rate = 0.9;
        utterance.pitch = 1.0;
        utterance.volume = 1.0;
        
        button.classList.add('speaking');
        button.querySelector('.material-icons').textContent = 'volume_off';
        
        utterance.onend = () => {
            button.classList.remove('speaking');
            button.querySelector('.material-icons').textContent = 'volume_up';
            this.currentUtterance = null;
        };
        
        utterance.onerror = (event) => {
            console.error('Speech synthesis error:', event);
            button.classList.remove('speaking');
            button.querySelector('.material-icons').textContent = 'volume_up';
            this.currentUtterance = null;
        };
        
        this.currentUtterance = utterance;
        this.speechSynthesis.speak(utterance);
    }
}
